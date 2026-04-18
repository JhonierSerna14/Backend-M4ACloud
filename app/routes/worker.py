"""
Endpoints exclusivos para el worker local de transcripción.
Autenticados con X-Worker-Key header (secret key compartida).
El worker corre en la PC del usuario (con GPU) y hace polling a estos endpoints.
"""
from typing import Optional
from datetime import timedelta, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from loguru import logger

from app.core.config import settings
from app.core.database import get_db
from app.core.ws import broadcast
from app.core.user_ws import broadcast_user
from app.core.sync_events import build_sync_event
from app.models.nota import Nota
from app.models.materia import Materia
from app.services import storage_service
from app.services import dropbox_audio_service

import asyncio

router = APIRouter(prefix="/worker", tags=["worker"])


def build_progress_event(nota_id: int, status: str, progress: int, message: Optional[str] = None):
    return {
        "id": nota_id,
        "status": status,
        "progress": progress,
        "progreso": progress,
        "message": message,
        "occurred_at": datetime.utcnow().isoformat() + "Z",
    }

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
    transcript_text: Optional[str] = None  # None si el worker ya guardó la transcripción antes
    duration_seconds: Optional[int] = None
    language: Optional[str] = None


class TranscriptUpdate(BaseModel):
    transcript_text: str
    duration_seconds: Optional[int] = None
    language: Optional[str] = None


class RetryUpdate(BaseModel):
    error: str


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
    
    TAMBIÉN detecta tareas huérfanas (status=processing pero sin heartbeat reciente)
    y las recupera automáticamente si no han superado el máximo de reintentos.
    
    Devuelve null si no hay trabajos en cola.
    El worker debe llamar a /jobs/{id}/claim inmediatamente después.
    """
    # 1. Buscar tareas huérfanas (processing con timeout expirado)
    timeout_minutes = settings.WORKER_ORPHAN_TASK_TIMEOUT_MINUTES
    max_retries = settings.WORKER_MAX_RETRY_ATTEMPTS
    timeout_threshold = func.now() - timedelta(minutes=timeout_minutes)
    
    huerfana = (
        db.query(Nota)
        .join(Materia)
        .filter(
            Nota.status == "processing",
            Nota.processing_started_at <= timeout_threshold,
            Nota.processing_attempts < max_retries
        )
        .order_by(Nota.processing_started_at.asc())
        .first()
    )
    
    if huerfana:
        # Recuperar tarea huérfana: volver a queued e incrementar intentos
        huerfana.status = "queued"
        huerfana.processing_attempts += 1
        huerfana.progreso = 0
        huerfana.status_message = f"Tarea recuperada de error (reintento #{huerfana.processing_attempts})"
        huerfana.processing_started_at = None
        db.commit()
        
        logger.warning(
            f"🔄 Tarea huérfana recuperada: nota_id={huerfana.id} "
            f"(attempt {huerfana.processing_attempts}/{max_retries})"
        )
        
        # Notificar al cliente
        try:
            asyncio.create_task(broadcast(
                huerfana.id,
                {
                    "id": huerfana.id,
                    "status": "queued",
                    "progress": 0,
                    "message": huerfana.status_message
                }
            ))
            if huerfana.materia:
                asyncio.create_task(broadcast_user(
                    huerfana.materia.usuario_id,
                    build_sync_event(
                        action="update",
                        entity="notas",
                        entity_id=None,
                        affected_collections=["notas", "dashboard"],
                    )
                ))
        except Exception:
            pass
    
    # 2. Buscar siguiente tarea en cola (queued)
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
    
    También establece processing_started_at para poder detectar tareas huérfanas
    si el worker se cierra sin completar.
    """
    from sqlalchemy import func
    
    # Claim atómico para evitar doble toma del job por workers concurrentes.
    rows_updated = (
        db.query(Nota)
        .filter(Nota.id == nota_id, Nota.status == "queued")
        .update(
            {
                Nota.status: "processing",
                Nota.progreso: 1,
                Nota.status_message: "Worker reclamó el trabajo...",
                Nota.processing_started_at: func.now(),
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
            build_progress_event(
                nota_id,
                "processing",
                1,
                "Iniciando transcripción...",
            )
        ))
        
        # Sincronizar cache del listado y el dashboard en todo el cliente
        nota = db.query(Nota).join(Materia).filter(Nota.id == nota_id).first()
        if nota and nota.materia:
            asyncio.create_task(broadcast_user(
                nota.materia.usuario_id,
                build_sync_event(
                    action="update",
                    entity="notas",
                    entity_id=None,
                    affected_collections=["notas", "dashboard"],
                )
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
            build_progress_event(
                nota_id,
                "processing",
                clamped,
                body.message,
            )
        ))
    except Exception:
        pass

    return {"ok": True}


@router.post("/jobs/{nota_id}/transcript", status_code=status.HTTP_200_OK)
async def save_transcript(
    nota_id: int,
    body: TranscriptUpdate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """
    Persiste la transcripción apenas termina Whisper, antes de llamar a la IA.
    Si la IA falla después, la nota ya queda lista para reprocess manual.
    """
    nota = db.query(Nota).join(Materia).filter(Nota.id == nota_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    transcript_text = (body.transcript_text or "").strip()
    if not transcript_text:
        raise HTTPException(status_code=400, detail="La transcripción está vacía")

    if nota.transcripcion_path:
        return {
            "ok": True,
            "nota_id": nota_id,
            "transcript_path": nota.transcripcion_path,
            "already_saved": True,
        }

    try:
        materia = nota.materia or db.query(Materia).filter(Materia.id == nota.materia_id).first()
        usuario_id = materia.usuario_id if materia else "unknown"

        import uuid as uuid_lib

        transcript_key = (
            f"{usuario_id}/{nota.materia_id}/transcripts/"
            f"transcript_{nota_id}_{uuid_lib.uuid4().hex[:8]}.txt"
        )
        storage_service.upload_bytes(
            transcript_text.encode("utf-8"),
            transcript_key,
            "text/plain"
        )
        nota.transcripcion_path = transcript_key
        if body.duration_seconds is not None and nota.duracion_audio is None:
            nota.duracion_audio = body.duration_seconds
        if body.language and not nota.idioma_detectado:
            nota.idioma_detectado = body.language
        if nota.status == "processing":
            nota.progreso = max(nota.progreso or 0, 55)
            nota.status_message = "Transcripción guardada. Generando resumen..."
        db.commit()
    except Exception as e:
        logger.error(f"worker: no se pudo guardar transcript para nota_id={nota_id}: {e}")
        raise HTTPException(status_code=500, detail="No se pudo guardar la transcripción") from e

    logger.info(f"worker: transcript persistido para nota_id={nota_id} → {nota.transcripcion_path}")
    return {"ok": True, "nota_id": nota_id, "transcript_path": nota.transcripcion_path}


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
    - Duración del audio e idioma detectado
    """
    nota = db.query(Nota).filter(Nota.id == nota_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    if body.transcript_text and not nota.transcripcion_path:
        try:
            materia = nota.materia or db.query(Materia).filter(Materia.id == nota.materia_id).first()
            usuario_id = materia.usuario_id if materia else "unknown"

            import uuid as uuid_lib

            transcript_key = (
                f"{usuario_id}/{nota.materia_id}/transcripts/"
                f"transcript_{nota_id}_{uuid_lib.uuid4().hex[:8]}.txt"
            )
            storage_service.upload_bytes(
                body.transcript_text.encode("utf-8"),
                transcript_key,
                "text/plain"
            )
            nota.transcripcion_path = transcript_key
            logger.info(f"worker: transcript guardado tardíamente en storage key={transcript_key}")
        except Exception as e:
            logger.warning(f"worker: no se pudo guardar transcript tardíamente: {e}")

    nota.contenido = body.html
    nota.progreso = 100
    nota.status = "done"
    nota.status_message = "Completado"
    nota.processing_started_at = None  # Limpiar heartbeat
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
            build_progress_event(
                nota_id,
                "done",
                100,
                "Completado",
            )
        ))
        if nota.materia:
            asyncio.create_task(broadcast_user(
                nota.materia.usuario_id,
                build_sync_event(
                    action="update",
                    entity="notas",
                    entity_id=None,
                    affected_collections=["notas", "dashboard"],
                )
            ))
    except Exception:
        pass

    logger.info(f"worker: nota_id={nota_id} completada ✅")
    return {"ok": True, "nota_id": nota_id}


@router.post("/jobs/{nota_id}/retry", status_code=status.HTTP_200_OK)
async def retry_job(
    nota_id: int,
    body: RetryUpdate,
    db: Session = Depends(get_db),
    _key: str = Depends(verify_worker_key),
):
    """Marca la nota como retry cuando la IA falló pero la transcripción ya quedó guardada."""
    nota = db.query(Nota).filter(Nota.id == nota_id).first()
    if not nota:
        raise HTTPException(status_code=404, detail="Nota no encontrada")

    clean_error = (body.error or "Error desconocido").replace("\n", " ").strip()[:220]
    nota.status = "retry"
    nota.progreso = 100 if nota.transcripcion_path else 0
    nota.status_message = f"Requiere reintento manual: {clean_error}"
    nota.processing_started_at = None
    db.commit()

    try:
        asyncio.create_task(broadcast(
            nota_id,
            build_progress_event(
                nota_id,
                "retry",
                nota.progreso or 100,
                nota.status_message,
            )
        ))
        if nota.materia:
            asyncio.create_task(broadcast_user(
                nota.materia.usuario_id,
                build_sync_event(
                    action="update",
                    entity="notas",
                    entity_id=None,
                    affected_collections=["notas", "dashboard"],
                )
            ))
    except Exception:
        pass

    logger.warning(f"worker: nota_id={nota_id} marcada como retry: {clean_error}")
    return {"ok": True, "retry": True}


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
    nota.processing_started_at = None  # Limpiar heartbeat
    db.commit()

    try:
        asyncio.create_task(broadcast(
            nota_id,
            build_progress_event(
                nota_id,
                "queued",
                0,
                nota.status_message,
            )
        ))
        if nota.materia:
            asyncio.create_task(broadcast_user(
                nota.materia.usuario_id,
                build_sync_event(
                    action="update",
                    entity="notas",
                    entity_id=None,
                    affected_collections=["notas", "dashboard"],
                )
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
