"""
Almacenamiento temporal de audio recibido vía Web Share Target (Vercel → backend).
"""
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import BaseModel

from app.core.auth import get_current_user
from app.core.config import settings
from app.models.usuario import Usuario

router = APIRouter(prefix="/audio", tags=["audio-share"])

SHARE_INTAKE_DIR = Path(settings.UPLOAD_DIR) / "share_intake"
MIN_FILE_SIZE = 1024
SHARE_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.I,
)
ALLOWED_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".flac", ".webm", ".mp4", ".amr", ".3gp", ".opus"
}


class ShareIntakeCreated(BaseModel):
    id: str
    filename: str


def _intake_secret() -> str:
    return (settings.SHARE_INTAKE_SECRET or settings.WORKER_SECRET_KEY).strip()


def _verify_intake_key(header_value: str | None) -> None:
    expected = _intake_secret()
    if not expected or header_value != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid share intake key")


def _meta_path(share_id: str) -> Path:
    return SHARE_INTAKE_DIR / f"{share_id}.json"


def _find_audio_path(share_id: str) -> Path | None:
    for path in SHARE_INTAKE_DIR.glob(f"{share_id}.*"):
        if path.suffix.lower() == ".json":
            continue
        return path
    return None


@router.post("/share-intake", response_model=ShareIntakeCreated)
async def create_share_intake(
    file: UploadFile = File(...),
    x_share_intake_key: str | None = Header(default=None, alias="X-Share-Intake-Key"),
):
    _verify_intake_key(x_share_intake_key)

    raw_name = (file.filename or "audio-compartido.m4a").strip() or "audio-compartido.m4a"
    ext = Path(raw_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".m4a"

    share_id = str(uuid.uuid4())
    SHARE_INTAKE_DIR.mkdir(parents=True, exist_ok=True)
    dest = SHARE_INTAKE_DIR / f"{share_id}{ext}"

    total = 0
    max_bytes = settings.MAX_UPLOAD_SIZE
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="File too large",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as exc:
        dest.unlink(missing_ok=True)
        logger.exception("share-intake write failed: {}", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not store file")

    if total < MIN_FILE_SIZE:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Empty or invalid audio file")

    meta = {
        "filename": raw_name,
        "content_type": file.content_type or "application/octet-stream",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "size": total,
    }
    _meta_path(share_id).write_text(json.dumps(meta), encoding="utf-8")

    return ShareIntakeCreated(id=share_id, filename=raw_name)


@router.get("/share-intake/{share_id}")
async def get_share_intake(
    share_id: str,
    current_user: Usuario = Depends(get_current_user),
):
    if not SHARE_ID_RE.match(share_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    audio_path = _find_audio_path(share_id)
    meta_path = _meta_path(share_id)
    if not audio_path or not audio_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    filename = audio_path.name
    media_type = "application/octet-stream"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            filename = meta.get("filename") or filename
            media_type = meta.get("content_type") or media_type
        except (json.JSONDecodeError, OSError):
            pass

    response = FileResponse(
        path=audio_path,
        media_type=media_type,
        filename=filename,
    )

    try:
        audio_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("share-intake cleanup failed for {}: {}", share_id, exc)

    return response
