"""
Servicio de almacenamiento de archivos.
Soporta backend local (disco) y Supabase Storage.
Seleccionado mediante STORAGE_BACKEND en .env: "local" | "supabase"
"""
import os
import mimetypes
from pathlib import Path
from typing import Optional

from loguru import logger

from app.core.config import settings


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _get_supabase_client():
    """Devuelve un cliente Supabase inicializado (lazy import)."""
    from supabase import create_client  # type: ignore
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_ROLE_KEY)


def normalize_storage_key(storage_key: str) -> str:
    """Normaliza una clave de storage a separadores POSIX (/) para compatibilidad cloud."""
    return str(storage_key).replace("\\", "/").lstrip("/")


# ---------------------------------------------------------------------------
# API pública
# ---------------------------------------------------------------------------


def upload_file(local_path: str, storage_key: str) -> str:
    """
    Sube un archivo al backend de storage configurado.

    Args:
        local_path: Ruta absoluta al archivo local a subir.
        storage_key: Clave de destino relativa (ej: "2/3/audio/uuid.m4a").

    Returns:
        La misma storage_key, que se puede pasar a get_public_url / get_signed_url.
    """
    normalized_key = normalize_storage_key(storage_key)

    if settings.STORAGE_BACKEND == "supabase":
        client = _get_supabase_client()
        mime_type, _ = mimetypes.guess_type(local_path)
        with open(local_path, "rb") as f:
            data = f.read()
        # upsert=True para que sobreescriba si ya existe
        client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).upload(
            normalized_key, data,
            file_options={"content-type": mime_type or "application/octet-stream", "upsert": "true"}
        )
        logger.debug(f"storage: uploaded to supabase key={normalized_key}")
    else:
        # Local: ya está guardado en disco; no hacemos nada adicional
        logger.debug(f"storage: local mode, file already at {local_path}")
    return normalized_key


def upload_bytes(data: bytes, storage_key: str, content_type: str = "application/octet-stream") -> str:
    """
    Sube bytes directamente al storage (sin archivo local).

    Args:
        data: Bytes a subir.
        storage_key: Clave de destino.
        content_type: MIME type del contenido.

    Returns:
        La storage_key.
    """
    normalized_key = normalize_storage_key(storage_key)

    if settings.STORAGE_BACKEND == "supabase":
        client = _get_supabase_client()
        client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).upload(
            normalized_key, data,
            file_options={"content-type": content_type, "upsert": "true"}
        )
        logger.debug(f"storage: uploaded bytes to supabase key={normalized_key}")
    else:
        # Guardar en disco local bajo UPLOAD_DIR
        local_path = Path(settings.UPLOAD_DIR) / normalized_key
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        logger.debug(f"storage: saved bytes locally to {local_path}")
    return normalized_key


def download_bytes(storage_key: str) -> bytes:
    """
    Descarga un archivo del storage y devuelve sus bytes.

    Args:
        storage_key: Clave relativa del archivo.

    Returns:
        Bytes del archivo.
    """
    normalized_key = normalize_storage_key(storage_key)

    if settings.STORAGE_BACKEND == "supabase":
        client = _get_supabase_client()
        return client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).download(normalized_key)
    else:
        local_path = Path(settings.UPLOAD_DIR) / normalized_key
        return local_path.read_bytes()


def get_signed_url(storage_key: str, expires_in: int = 3600) -> str:
    """
    Devuelve una URL firmada de descarga temporal.

    Args:
        storage_key: Clave relativa del archivo.
        expires_in: Segundos hasta que expira la URL (default 1 hora).

    Returns:
        URL de descarga.
    """
    normalized_key = normalize_storage_key(storage_key)

    if settings.STORAGE_BACKEND == "supabase":
        client = _get_supabase_client()
        result = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).create_signed_url(
            normalized_key, expires_in
        )
        return result["signedURL"]
    else:
        # En modo local devolvemos la URL relativa del endpoint de uploads
        return f"/api/uploads/{normalized_key}"


def get_public_url(storage_key: str) -> str:
    """
    Devuelve la URL pública permanente de un archivo.
    En modo supabase requiere que el bucket sea público o que se use signed URL.
    En modo local devuelve la URL relativa /api/uploads/...

    Args:
        storage_key: Clave relativa del archivo.

    Returns:
        URL de acceso.
    """
    normalized_key = normalize_storage_key(storage_key)

    if settings.STORAGE_BACKEND == "supabase":
        client = _get_supabase_client()
        return client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).get_public_url(normalized_key)
    else:
        return f"/api/uploads/{normalized_key}"


def delete_file(storage_key: str) -> None:
    """
    Elimina un archivo del storage.

    Args:
        storage_key: Clave relativa del archivo.
    """
    normalized_key = normalize_storage_key(storage_key)

    if settings.STORAGE_BACKEND == "supabase":
        client = _get_supabase_client()
        client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).remove([normalized_key])
        logger.debug(f"storage: deleted from supabase key={normalized_key}")
    else:
        local_path = Path(settings.UPLOAD_DIR) / normalized_key
        try:
            local_path.unlink(missing_ok=True)
            logger.debug(f"storage: deleted local file {local_path}")
        except Exception as e:
            logger.warning(f"storage: could not delete {local_path}: {e}")


def exists(storage_key: str) -> bool:
    """Comprueba si un archivo existe en el storage."""
    normalized_key = normalize_storage_key(storage_key)

    if settings.STORAGE_BACKEND == "supabase":
        try:
            client = _get_supabase_client()
            # list() con prefix para verificar existencia
            items = client.storage.from_(settings.SUPABASE_STORAGE_BUCKET).list(
                path=str(Path(normalized_key).parent).replace("\\", "/"),
            )
            name = Path(normalized_key).name
            return any(item.get("name") == name for item in (items or []))
        except Exception:
            return False
    else:
        return (Path(settings.UPLOAD_DIR) / normalized_key).exists()


def get_local_path(storage_key: str) -> Optional[str]:
    """
    Devuelve la ruta local absoluta de un archivo (solo en modo local).
    En modo supabase devuelve None (el archivo no existe localmente).
    """
    normalized_key = normalize_storage_key(storage_key)
    if settings.STORAGE_BACKEND == "local":
        return str(Path(settings.UPLOAD_DIR) / normalized_key)
    return None
