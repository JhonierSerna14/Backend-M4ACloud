"""
Endpoints exclusivos para el worker local de transcripción.
Autenticados con X-Worker-Key header (secret key compartida).
El worker corre en la PC del usuario (con GPU) y hace polling a estos endpoints.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from loguru import logger

from app.core.config import settings
from app.core.database import get_db
from app.core.ws import broadcast
from app.models.nota import Nota
from app.models.materia import Materia
from app.services import storage_service
from app.services import dropbox_audio_service

import asyncio

router = APIRouter(prefix="/worker", tags=["worker"])

# ---------------------------------------------------------------------------
# Autenticación del worker
# ---------------------------------------------------------------------------


def verify_worker_key(x_worker_key: str = Header(..., alias="X-Worker-Key")):
    """Valida que el request venga del worker autorizado."""
    if x_worker_key != settings.WORKER_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Worker key inválida"
        )
    return x_worker_key


# ---------------------------------------------------------------------------
# Schemas de request/response
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    nota_id: int
    materia_nombre: str
    audio_download_url: Optional[str] = None   # URL firmada del audio (None si es reprocess)
    transcript_download_url: Optional[str] = None  # URL firmada del transcript (si es reprocess)
    is_reprocess: bool = False  # True si solo debe hacer IA (ya tiene transcript)


class ProgressUpdate(BaseModel):
    percent: float
    message: str


class CompleteUpdate(BaseModel):
    html: str
    transcript_text: Optional[str] = None  # None si era reprocess
    duration_seconds: Optional[int] = None
    language: Optional[str] = None


class FailUpdate(BaseModel):
    error: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/jobs/next", response_model=Optional[JobResponse])
async def get_next_job(
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """
    Devuelve el trabajo de transcripción pendiente más antiguo (status=queued).
    Devuelve null si no hay trabajos en cola.
    El worker debe llamar a /jobs/{id}/claim inmediatamente después.
    """
    nota = (
        db.query(Nota)
        .join(Materia)
        .filter(Nota.status == "queued")
        .order_by(func.coalesce(Nota.fecha_actualizacion, Nota.fecha_creacion).asc())
        .first()
    )

    if not nota:
        return None

    materia_nombre = nota.materia.nombre if nota.materia else ""

    # Determinar si es reprocess (tiene transcripción guardada) o transcripción nueva
    is_reprocess = bool(nota.transcripcion_path)
    audio_url = None
    transcript_url = None

    if is_reprocess:
        # Solo necesita la transcripción para regenerar el HTML con IA
        if nota.transcripcion_path:
            transcript_url = storage_service.get_signed_url(nota.transcripcion_path)
    else:
        # Necesita el audio para transcribir
        if nota.origen_audio:
            dropbox_path = dropbox_audio_service.from_ref(nota.origen_audio)
            if dropbox_path:
                audio_url = dropbox_audio_service.create_temp_download_link(nota.origen_audio)
            else:
                audio_url = storage_service.get_signed_url(nota.origen_audio)

    logger.info(
        f"worker: job asignado nota_id={nota.id} "
        f"is_reprocess={is_reprocess} materia={materia_nombre!r}"
    )

    return JobResponse(
        nota_id=nota.id,
        materia_nombre=materia_nombre,
        audio_download_url=audio_url,
        transcript_download_url=transcript_url,
        is_reprocess=is_reprocess,
    )


@router.post("/jobs/{nota_id}/claim", status_code=status.HTTP_200_OK)
async def claim_job(
    nota_id: int,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """
    El worker reclama el trabajo: cambia status a 'processing'.
    Si ya está en processing (otro worker tomó el trabajo) devuelve 409.
    """
    # Claim atómico para evitar doble toma del job por workers concurrentes.
    rows_updated = (
        db.query(Nota)
        .filter(Nota.id == nota_id, Nota.status == "queued")
        .update(
            {
                Nota.status: "processing",
                Nota.progreso: 1,
                Nota.status_message: "Worker reclamó el trabajo...",
            },
            synchronize_session=False,
        )
    )

    if rows_updated == 0:
        nota = db.query(Nota).filter(Nota.id == nota_id).first()
        if not nota:
            raise HTTPException(status_code=404, detail="Nota no encontrada")
        if nota.status == "processing":
            raise HTTPException(status_code=409, detail="La nota ya está siendo procesada")
        raise HTTPException(
            status_code=400,
            detail=f"La nota no está en cola (status actual: {nota.status})"
        )

    db.commit()

    try:
        asyncio.create_task(broadcast(
            nota_id,
            {"id": nota_id, "status": "processing", "progress": 1, "message": "Iniciando transcripción..."}
        ))
    except Exception:
        pass

    logger.info(f"worker: nota_id={nota_id} claimed → processing")
    return {"ok": True, "nota_id": nota_id}


@router.post("/jobs/{nota_id}/progress", status_code=status.HTTP_200_OK)
async def update_progress(
    nota_id: int,
    body: ProgressUpdate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """
    Actualiza el progreso de un trabajo en procesamiento.
    El worker envía esto cada ~3 segundos durante transcripción e IA.
    """
    clamped = max(0, min(100, int(body.percent)))
    nota = db.query(Nota).filter(Nota.id == nota_id).first()
    if nota:
        nota.progreso = clamped
        nota.status_message = body.message
        db.commit()

    # Broadcast WS a clientes conectados
    try:
        asyncio.create_task(broadcast(
            nota_id,
            {"id": nota_id, "status": "processing", "progress": clamped, "message": body.message}
        ))
    except Exception:
        pass

    return {"ok": True}


@router.post("/jobs/{nota_id}/complete", status_code=status.HTTP_200_OK)
async def complete_job(
    nota_id: int,
    body: CompleteUpdate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """
    El worker entrega el trabajo completado:
    - HTML del resumen académico
    - Texto de transcripción (opcional, None si era reprocess)
    - Duración del audio e idioma detectado
    """
    nota = db.query(Nota).filter(Nota.id == nota_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    # Guardar transcript en storage (si viene uno nuevo)
    if body.transcript_text:
        try:
            materia_id = nota.materia_id
            # Determinar usuario_id vía materia
            materia = db.query(Materia).filter(Materia.id == materia_id).first()
            usuario_id = materia.usuario_id if materia else "unknown"

            import uuid as uuid_lib
            transcript_key = (
                f"{usuario_id}/{materia_id}/transcripts/"
                f"transcript_{nota_id}_{uuid_lib.uuid4().hex[:8]}.txt"
            )
            storage_service.upload_bytes(
                body.transcript_text.encode("utf-8"),
                transcript_key,
                "text/plain"
            )
            nota.transcripcion_path = transcript_key
            logger.info(f"worker: transcript guardado en storage key={transcript_key}")
        except Exception as e:
            logger.warning(f"worker: no se pudo guardar transcript: {e}")

    nota.contenido = body.html
    nota.progreso = 100
    nota.status = "done"
    nota.status_message = "Completado"
    if body.duration_seconds is not None:
        nota.duracion_audio = body.duration_seconds
    if body.language:
        nota.idioma_detectado = body.language
    db.commit()

    # Limpiar audio del storage (ya no es necesario)
    if nota.origen_audio:
        try:
            dropbox_path = dropbox_audio_service.from_ref(nota.origen_audio)
            if dropbox_path:
                dropbox_audio_service.delete_file(nota.origen_audio)
                logger.debug(f"worker: audio eliminado en Dropbox path={dropbox_path}")
            else:
                storage_service.delete_file(nota.origen_audio)
                logger.debug(f"worker: audio eliminado key={nota.origen_audio}")
        except Exception as e:
            logger.warning(f"worker: no se pudo eliminar audio: {e}")

    try:
        asyncio.create_task(broadcast(
            nota_id,
            {"id": nota_id, "status": "done", "progress": 100, "message": "Completado"}
        ))
    except Exception:
        pass

    logger.info(f"worker: nota_id={nota_id} completada ✅")
    return {"ok": True, "nota_id": nota_id}


@router.post("/jobs/{nota_id}/fail", status_code=status.HTTP_200_OK)
async def fail_job(
    nota_id: int,
    body: FailUpdate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """El worker reporta un fallo y la nota vuelve a cola para reintento."""
    nota = db.query(Nota).filter(Nota.id == nota_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    previous_message = (nota.status_message or "").strip()
    retry_count = 1
    if "reintento #" in previous_message.lower():
        try:
            retry_count = int(previous_message.lower().split("reintento #", 1)[1].split(":", 1)[0].strip()) + 1
        except Exception:
            retry_count = 1

    clean_error = (body.error or "Error desconocido").replace("\n", " ").strip()
    clean_error = clean_error[:180]

    nota.status = "queued"
    nota.progreso = 0
    nota.status_message = f"Pendiente de reintento #{retry_count}: {clean_error}"[:255]
    db.commit()

    try:
        asyncio.create_task(broadcast(
            nota_id,
            {"id": nota_id, "status": "queued", "progress": 0, "message": nota.status_message}
        ))
    except Exception:
        pass

    logger.warning(f"worker: nota_id={nota_id} reencolada por fallo (reintento #{retry_count}): {clean_error}")
    return {"ok": True, "requeued": True, "retry_count": retry_count}


@router.get("/status", status_code=status.HTTP_200_OK)
def worker_status(
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """
    Información de estado de la cola para el worker.
    Devuelve conteos de jobs en cada estado.
    """
    queued = db.query(Nota).filter(Nota.status == "queued").count()
    processing = db.query(Nota).filter(Nota.status == "processing").count()
    return {
        "queued": queued,
        "processing": processing,
        "worker_key_valid": True,
    }
