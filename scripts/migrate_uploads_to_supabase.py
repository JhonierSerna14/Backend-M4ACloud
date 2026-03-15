"""
Script de migración: sube los archivos locales (uploads/) a Supabase Storage.

Uso (una sola vez, antes del deploy):
    cd Backend
    pip install supabase
    SUPABASE_URL=https://xxx.supabase.co \
    SUPABASE_SERVICE_ROLE_KEY=eyJ... \
    python scripts/migrate_uploads_to_supabase.py

El script es idempotente: si el archivo ya existe en Supabase, lo salta.
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Aseguramos que el directorio Backend/ esté en el path cuando se corre el script
BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

load_dotenv(BASE_DIR / ".env")

SUPABASE_URL    = os.environ["SUPABASE_URL"]
SUPABASE_KEY    = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
BUCKET          = os.getenv("SUPABASE_STORAGE_BUCKET", "m4a-files")
upload_dir_env = os.getenv("UPLOAD_DIR", "")
if upload_dir_env:
    candidate = Path(upload_dir_env)
    UPLOAD_DIR = candidate if candidate.is_absolute() else (BASE_DIR / candidate)
else:
    primary = BASE_DIR / "uploads"
    legacy = BASE_DIR / "app" / "uploads"
    UPLOAD_DIR = primary if primary.exists() else legacy

from supabase import create_client, Client  # noqa: E402

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def file_exists_in_supabase(storage_key: str) -> bool:
    try:
        # list() devuelve los objetos en el "directorio" del key
        parent = str(Path(storage_key).parent)
        name   = Path(storage_key).name
        files  = supabase.storage.from_(BUCKET).list(parent)
        return any(f["name"] == name for f in files)
    except Exception:
        return False


def migrate():
    if not UPLOAD_DIR.exists():
        print(f"❌ Directorio de uploads no encontrado: {UPLOAD_DIR.absolute()}")
        sys.exit(1)

    all_files = [p for p in UPLOAD_DIR.rglob("*") if p.is_file()]
    total = len(all_files)
    print(f"📦 {total} archivo(s) encontrados en {UPLOAD_DIR.absolute()}")

    uploaded = 0
    skipped  = 0
    errors   = 0

    for idx, local_path in enumerate(all_files, 1):
        # storage_key = ruta relativa dentro de uploads/
        storage_key = str(local_path.relative_to(UPLOAD_DIR)).replace("\\", "/")

        prefix = f"[{idx}/{total}]"

        if file_exists_in_supabase(storage_key):
            print(f"{prefix} SKIP  {storage_key}")
            skipped += 1
            continue

        try:
            with open(local_path, "rb") as f:
                data = f.read()

            # Intentar inferir content-type básico
            ext = local_path.suffix.lower()
            content_type_map = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png",  ".gif": "image/gif",
                ".webp": "image/webp", ".pdf": "application/pdf",
                ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
                ".wav": "audio/wav",  ".ogg": "audio/ogg",
                ".webm": "audio/webm", ".txt": "text/plain",
            }
            content_type = content_type_map.get(ext, "application/octet-stream")

            supabase.storage.from_(BUCKET).upload(
                storage_key,
                data,
                {"content-type": content_type, "upsert": "false"},
            )
            size_kb = len(data) / 1024
            print(f"{prefix} ✅ {storage_key} ({size_kb:.1f} KB)")
            uploaded += 1

        except Exception as e:
            print(f"{prefix} ❌ ERROR {storage_key}: {e}")
            errors += 1

    print(f"\n🏁 Migración completada:")
    print(f"   ✅ Subidos:  {uploaded}")
    print(f"   ⏭️ Saltados: {skipped} (ya existían)")
    print(f"   ❌ Errores:  {errors}")

    if errors:
        sys.exit(1)


if __name__ == "__main__":
    migrate()
