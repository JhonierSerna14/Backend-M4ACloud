"""
Sistema de logging configurable para M4A.

Modos:
- DEBUG: Logs detallados en consola y archivo (desarrollo)
- INFO: Logs normales en consola y archivo
- ERROR: Solo errores en consola (producción)

Configuración vía .env: LOG_LEVEL=DEBUG|INFO|WARNING|ERROR
"""
import logging
import os
import sys

from loguru import logger

from app.core.config import settings

DEBUG_FORMAT = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
SIMPLE_FORMAT = "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>"
LOG_FILE_PATH = "logs/m4a.log"


class InterceptHandler(logging.Handler):
    """Interceptor para unificar logs de bibliotecas externas con Loguru."""
    
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


def setup_logging() -> None:
    """
    Configura logging según LOG_LEVEL en .env.

    - DEBUG: Todo en consola con detalles (función, línea)
    - INFO: Logs normales en consola
    - ERROR: Solo errores (producción)
    """
    logger.remove()

    level = settings.LOG_LEVEL
    is_debug = level == "DEBUG"

    # Consola
    console_format = DEBUG_FORMAT if is_debug else SIMPLE_FORMAT
    logger.add(
        sys.stderr,
        level=level,
        format=console_format,
        colorize=True,
    )

    # Archivo: nivel configurable vía LOG_FILE_LEVEL (por defecto igual a nivel de consola)
    if LOG_FILE_PATH:
        os.makedirs(os.path.dirname(LOG_FILE_PATH), exist_ok=True)
        file_level = os.getenv("LOG_FILE_LEVEL", level)
        logger.add(
            LOG_FILE_PATH,
            level=file_level,
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
            rotation="10 MB",
            retention="7 days",
            compression="zip",
            enqueue=True,
        )

    # Configurar logging estándar
    std_level = logging.DEBUG if is_debug else logging.WARNING
    logging.basicConfig(handlers=[InterceptHandler()], level=std_level, force=True)

    # Controlar bibliotecas externas según nivel
    external_level = logging.DEBUG if is_debug else logging.WARNING
    for name in ["uvicorn", "uvicorn.access", "uvicorn.error", "fastapi",
                 "sqlalchemy.engine", "httpx", "httpcore", "websockets"]:
        lib_logger = logging.getLogger(name)
        lib_logger.setLevel(external_level)
        lib_logger.handlers = [InterceptHandler()]
        lib_logger.propagate = False  # Evita duplicación al no propagar al root logger

    # faster_whisper siempre en WARNING (muy verbose)
    whisper_logger = logging.getLogger("faster_whisper")
    whisper_logger.setLevel(logging.WARNING)
    whisper_logger.propagate = False

    logger.info(f"📋 Logging configurado: {level}")
