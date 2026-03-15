"""
Servicio de audio temporal en Dropbox.
Se usa para subir audios pesados y eliminarlos al completar el procesamiento.
"""
from pathlib import Path

import dropbox
from dropbox.files import CommitInfo, UploadSessionCursor, WriteMode

from app.core.config import settings


CHUNK_SIZE = 8 * 1024 * 1024  # 8MB por chunk


def _client() -> dropbox.Dropbox:
    if not settings.DROPBOX_ACCESS_TOKEN:
        raise RuntimeError("Falta DROPBOX_ACCESS_TOKEN en configuración")
    return dropbox.Dropbox(settings.DROPBOX_ACCESS_TOKEN, timeout=300)


def _normalize(path: str) -> str:
    p = path.replace("\\", "/")
    if not p.startswith("/"):
        p = "/" + p
    return p


def build_audio_path(user_id: int, materia_id: int, filename: str) -> str:
    ext = Path(filename).suffix or ".m4a"
    unique = Path(filename).stem
    return _normalize(f"{settings.DROPBOX_AUDIO_ROOT_PATH}/{user_id}/{materia_id}/audio/{unique}{ext}")


def to_ref(dropbox_path: str) -> str:
    return f"dropbox:{_normalize(dropbox_path)}"


def from_ref(value: str | None) -> str | None:
    if not value:
        return None
    if value.startswith("dropbox:"):
        return _normalize(value.split(":", 1)[1])
    return None


def upload_file(local_path: str, dropbox_path: str) -> str:
    dbx = _client()
    dbx_path = _normalize(dropbox_path)
    total_size = Path(local_path).stat().st_size

    with open(local_path, "rb") as f:
        if total_size <= CHUNK_SIZE:
            dbx.files_upload(f.read(), dbx_path, mode=WriteMode("overwrite"))
        else:
            start = dbx.files_upload_session_start(f.read(CHUNK_SIZE))
            cursor = UploadSessionCursor(session_id=start.session_id, offset=f.tell())

            while f.tell() < total_size:
                remaining = total_size - f.tell()
                if remaining <= CHUNK_SIZE:
                    commit = CommitInfo(path=dbx_path, mode=WriteMode("overwrite"))
                    dbx.files_upload_session_finish(f.read(CHUNK_SIZE), cursor, commit)
                else:
                    dbx.files_upload_session_append_v2(f.read(CHUNK_SIZE), cursor)
                    cursor.offset = f.tell()

    return to_ref(dbx_path)


def create_temp_download_link(ref_or_path: str) -> str:
    dbx = _client()
    path = from_ref(ref_or_path) or _normalize(ref_or_path)
    return dbx.files_get_temporary_link(path).link


def delete_file(ref_or_path: str) -> None:
    dbx = _client()
    path = from_ref(ref_or_path) or _normalize(ref_or_path)
    try:
        dbx.files_delete_v2(path)
    except Exception:
        # Si ya no existe, no frenamos el flujo
        pass
