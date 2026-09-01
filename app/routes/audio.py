"""
Rutas para subida de audio.
Valida y sube el audio a storage, crea la nota y la encola para el worker local.
El procesamiento pesado (Whisper + IA) lo realiza el worker en la PC del usuario.
"""
import os
import uuid
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException, status, Form
from sqlalchemy.orm import Session
from loguru import logger

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.semestre import get_materia_editable
from app.core.config import settings
from app.core.sync_events import build_sync_event
from app.core.user_ws import broadcast_user
from app.models.usuario import Usuario
from app.models.nota import Nota
from app.schemas.nota import NotaResponse
from app.services import storage_service
from app.services import dropbox_audio_service


router = APIRouter(prefix="/notas/audio", tags=["audio"])

# Constantes de validación
ALLOWED_AUDIO_TYPES = ["audio/", "video/mp4", "video/webm"]
ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".webm", ".mp4"
}
MIN_FILE_SIZE = 1024           # 1 KB mínimo para considerar un archivo válido
ESTIMATED_MB_PER_MINUTE = 10  # ~10 MB por minuto (para mensaje informativo)


def _validate_audio_file(file: UploadFile) -> int:
    """
    Valida tipo MIME y tamaño del archivo de audio.

    Returns:
        Tamaño del archivo en bytes.

    Raises:
        HTTPException si el archivo no es válido.
    """
    content_type = (file.content_type or "").lower()
    file_ext = Path(file.filename or "").suffix.lower()

    is_valid_type = any(content_type.startswith(t) for t in ALLOWED_AUDIO_TYPES)
    is_generic_type = content_type in {"", "application/octet-stream", "binary/octet-stream"}
    is_valid_ext = file_ext in ALLOWED_AUDIO_EXTENSIONS

    # En móviles (especialmente share targets) algunos navegadores envían MIME genérico.
    # Si la extensión es de audio conocida, permitimos continuar.
    is_valid = is_valid_type or (is_generic_type and is_valid_ext)

    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato no soportado. Use archivos de audio (mp3, wav, m4a, etc.)"
        )

    try:
        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
        file.file.seek(0)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No se pudo leer el archivo"
        )

    if file_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Archivo muy grande. Máximo: {settings.MAX_UPLOAD_SIZE_MB} MB"
        )

    if file_size < MIN_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Archivo muy pequeño o vacío"
        )

    return file_size


@router.post("/upload", response_model=NotaResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_audio(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Archivo de audio a transcribir"),
    materia_id: int = Form(..., description="ID de la materia"),
    titulo: str = Form(..., min_length=1, max_length=200, description="Título de la nota"),
    fecha_clase: str = Form(None, description="Fecha de la clase (YYYY-MM-DD)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """
    Sube un archivo de audio y lo encola para transcripción por el worker local.

    El procesamiento (Whisper + resumen IA) lo realiza el worker en la PC del usuario
    cuando esté disponible. La nota queda en status='queued' hasta que el worker
    la procese y entregue el HTML final.

    **Formatos soportados:** MP3, WAV, M4A, OGG, FLAC, WebM
    """
    # Verificar materia pertenece al semestre activo editable
    materia = get_materia_editable(db, current_user, materia_id)

    # Validar archivo
    file_size = _validate_audio_file(file)
    file_size_mb = file_size / 1024 / 1024

    # Guardar temporalmente en disco local
    upload_dir = Path(settings.UPLOAD_DIR) / str(current_user.id) / str(materia_id) / "audio"
    upload_dir.mkdir(parents=True, exist_ok=True)

    file_ext = Path(file.filename).suffix or ".m4a"
    unique_name = f"{uuid.uuid4()}{file_ext}"
    local_path = upload_dir / unique_name
    storage_key = storage_service.normalize_storage_key(
        str(Path(str(current_user.id)) / str(materia_id) / "audio" / unique_name)
    )

    with open(local_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # Subir audio al backend configurado
    try:
        if settings.AUDIO_STORAGE_BACKEND == "dropbox":
            dropbox_path = dropbox_audio_service.build_audio_path(
                user_id=current_user.id,
                materia_id=materia_id,
                filename=unique_name,
            )
            storage_key = dropbox_audio_service.upload_file(str(local_path), dropbox_path)
            local_path.unlink(missing_ok=True)
        else:
            storage_key = storage_service.upload_file(str(local_path), storage_key)
            if settings.STORAGE_BACKEND == "supabase":
                local_path.unlink(missing_ok=True)
    except Exception as e:
        logger.error(f"Error subiendo audio: {e}")
        local_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error al guardar el archivo de audio"
        )

    # Parsear fecha_clase si se proporciona
    fecha_clase_parsed = None
    if fecha_clase:
        try:
            fecha_clase_parsed = datetime.strptime(fecha_clase, "%Y-%m-%d").date()
        except ValueError:
            pass

    estimated_minutes = file_size_mb / ESTIMATED_MB_PER_MINUTE

    # Crear nota en estado 'queued': el worker la procesará cuando esté disponible
    nota = Nota(
        titulo=titulo,
        contenido=f"""# ⏳ En Cola de Procesamiento

**Archivo:** {file.filename}
**Tamaño:** {file_size_mb:.1f} MB
**Tiempo estimado:** ~{estimated_minutes:.0f} minutos

El audio está en cola. La transcripción comenzará cuando el worker esté activo.
Esta nota se actualizará automáticamente cuando esté lista.""",
        materia_id=materia_id,
        origen_audio=storage_key,
        fecha_clase=fecha_clase_parsed,
        status="queued",
        progreso=0,
        status_message="En cola de procesamiento"
    )

    db.add(nota)
    db.commit()
    db.refresh(nota)

    background_tasks.add_task(
        broadcast_user,
        current_user.id,
        build_sync_event(
            action="created",
            entity="nota",
            entity_id=nota.id,
            payload={
                **NotaResponse.model_validate(nota).model_dump(mode="json"),
                "materia_nombre": materia.nombre,
                "materia_color": materia.color,
            },
            affected_collections=["notas", "dashboard", "materias", f"nota:{nota.id}"],
        ),
    )

    logger.info(
        f"🎬 Audio encolado | nota={nota.id} | key={storage_key} | user={current_user.id}"
    )

    return nota
