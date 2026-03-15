from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from pathlib import Path
import mimetypes

from app.core.config import settings
from app.services import storage_service

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.get("/{file_path:path}")
def get_upload(file_path: str):
    """Devuelve un archivo estático guardado en el directorio de uploads.

    Seguridad: se resuelve la ruta y se comprueba que esté dentro de UPLOAD_DIR
    para prevenir traversal.
    """
    # En modo Supabase: redirigir a la URL pública del bucket
    if settings.STORAGE_BACKEND == "supabase":
        normalized = file_path.replace("\\", "/")
        url = storage_service.get_signed_url(normalized)
        return RedirectResponse(url=url, status_code=302)

    upload_dir = Path(settings.UPLOAD_DIR).resolve()

    # Normalizar separadores (por si vienen con backslashes de Windows)
    normalized = file_path.replace("\\", "/")
    target = (upload_dir / normalized).resolve()

    # Verificar que el archivo existe y está dentro de uploads
    if not str(target).startswith(str(upload_dir)) or not target.exists():
        raise HTTPException(status_code=404, detail="Archivo no encontrado")

    mime_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(path=str(target), media_type=mime_type or "application/octet-stream")
