"""
Script para iniciar la aplicación M4A.
Uso: python run_app.py
"""
import os
import sys
import subprocess
import warnings

from dotenv import load_dotenv

load_dotenv()

warnings.filterwarnings("ignore", message="pkg_resources is deprecated")
warnings.filterwarnings("ignore", category=DeprecationWarning)

# Asegurar directorio de trabajo correcto
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Evitar warnings de symlinks en huggingface_hub (Windows)
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_ENABLE_SYMLINKS", "0")

if __name__ == "__main__":
    # Verificar que exista soporte WS en el entorno (websockets o wsproto)
    ws_ok = False
    try:
        import websockets  # type: ignore
        ws_ok = True
    except Exception:
        try:
            import wsproto  # type: ignore
            ws_ok = True
        except Exception:
            ws_ok = False

    if not ws_ok:
        print('\nERROR: No WebSocket backend instalado. Instala "websockets" o ejecuta: pip install "uvicorn[standard]"\n', file=sys.stderr)

    subprocess.run(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
    )
