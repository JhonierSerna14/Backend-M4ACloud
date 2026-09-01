"""
Rutas para gestión de archivos adjuntos.
Upload, descarga y eliminación con validación de tipos.
"""
from pathlib import Path
from typing import List, Optional
import shutil
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.semestre import get_semestre_actual, get_materia_editable, require_editable_semestre
from app.models.archivo import Archivo
from app.models.materia import Materia
from app.models.usuario import Usuario
from app.schemas.archivo import ArchivoResponse
from app.services import storage_service

router = APIRouter(prefix="/archivos", tags=["archivos"])

# Tipos MIME permitidos
ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg", "image/png", "image/gif", "image/webp",
    "text/plain", "text/markdown",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


@router.post("/upload", response_model=ArchivoResponse, status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    materia_id: int = Form(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Sube un archivo a una materia."""
    materia = get_materia_editable(db, current_user, materia_id)

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de archivo no permitido")

    file_size = getattr(file, "size", None)
    if file_size is not None and file_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Archivo muy grande. Máximo: {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    upload_dir = Path(settings.UPLOAD_DIR) / str(current_user.id) / str(materia_id)
    upload_dir.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4()}{Path(file.filename).suffix}"
    file_path = upload_dir / unique_name
    storage_key = storage_service.normalize_storage_key(
        str(Path(str(current_user.id)) / str(materia_id) / unique_name)
    )

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    actual_size = file_path.stat().st_size
    if actual_size > settings.MAX_UPLOAD_SIZE:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=413,
            detail=f"Archivo muy grande. Máximo: {settings.MAX_UPLOAD_SIZE_MB} MB",
        )

    try:
        storage_key = storage_service.upload_file(str(file_path), storage_key)
    except Exception as e:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        error_text = str(e)
        if "Payload too large" in error_text or "statusCode': 413" in error_text or 'statusCode": 413' in error_text:
            raise HTTPException(
                status_code=413,
                detail="El archivo supera el límite de subida del storage.",
            )
        raise HTTPException(status_code=500, detail="Error subiendo archivo al storage")

    if settings.STORAGE_BACKEND == "supabase":
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass

    db_archivo = Archivo(
        nombre=file.filename,
        ruta=storage_key,
        tipo=file.content_type,
        tamaño=file_path.stat().st_size if file_path.exists() else file_size,
        materia_id=materia_id,
    )
    db.add(db_archivo)
    db.commit()
    db.refresh(db_archivo)
    return db_archivo


@router.get("/", response_model=List[ArchivoResponse])
def get_archivos(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    materia_id: Optional[int] = None,
    tipo: Optional[str] = Query(None, description="Filtrar por tipo MIME"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista archivos con filtros opcionales."""
    semestre = get_semestre_actual(db, current_user)
    query = db.query(Archivo).join(Materia).filter(
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == semestre.id,
    )

    if materia_id:
        query = query.filter(Archivo.materia_id == materia_id)
    if tipo:
        query = query.filter(Archivo.tipo.ilike(f"%{tipo}%"))

    return query.order_by(Archivo.fecha_creacion.desc()).offset(skip).limit(limit).all()


@router.get("/{archivo_id}", response_model=ArchivoResponse)
def get_archivo(
    archivo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Obtiene metadata de un archivo."""
    archivo = db.query(Archivo).join(Materia).filter(
        Archivo.id == archivo_id,
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == get_semestre_actual(db, current_user).id,
    ).first()

    if not archivo:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    return archivo


@router.get("/{archivo_id}/download")
def download_archivo(
    archivo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Descarga un archivo."""
    archivo = db.query(Archivo).join(Materia).filter(
        Archivo.id == archivo_id,
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == get_semestre_actual(db, current_user).id,
    ).first()

    if not archivo:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    if settings.STORAGE_BACKEND == "supabase":
        url = storage_service.get_signed_url(archivo.ruta)
        return RedirectResponse(url=url, status_code=302)

    file_path = Path(settings.UPLOAD_DIR) / archivo.ruta
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Archivo físico no encontrado")

    return FileResponse(
        path=file_path,
        filename=archivo.nombre,
        media_type=archivo.tipo,
    )


@router.delete("/{archivo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_archivo(
    archivo_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Elimina un archivo."""
    semestre = get_semestre_actual(db, current_user)
    require_editable_semestre(db, current_user, semestre)

    archivo = db.query(Archivo).join(Materia).filter(
        Archivo.id == archivo_id,
        Materia.usuario_id == current_user.id,
        Materia.semestre_id == semestre.id,
    ).first()

    if not archivo:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    storage_service.delete_file(archivo.ruta)

    if settings.STORAGE_BACKEND == "local":
        file_path = Path(settings.UPLOAD_DIR) / archivo.ruta
        if file_path.exists():
            file_path.unlink()

    db.delete(archivo)
    db.commit()
    return None
