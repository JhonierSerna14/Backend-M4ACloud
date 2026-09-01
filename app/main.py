"""
M4A Backend - API REST para gestión académica.
Transcripción de audio con IA y generación de resúmenes.
"""
import time
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import Response

warnings.filterwarnings("ignore", message="pkg_resources is deprecated as an API")

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.metrics import get_metrics_payload
from app.routes import (
    auth_router,
    semestres_router,
    materias_router,
    tareas_router,
    notas_router,
    archivos_router,
    audio_router,
    dashboard_router,
    ws_router,
    ws_sync_router,
)
from app.routes.uploads import router as uploads_router
from app.routes.worker import router as worker_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestión del ciclo de vida de la aplicación."""
    # Startup
    setup_logging()
    yield
    # Shutdown (cleanup si es necesario)


app = FastAPI(
    title="M4A API",
    description="Backend para Mis Materias, Mis Apuntes - Transcripción de audio con IA",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# CORS - En desarrollo se permite todo; en producción filtrar por dominio
# Orígenes permitidos: BACKEND_CORS_ORIGINS puede ser "*" o lista separada por coma
_raw_origins = settings.BACKEND_CORS_ORIGINS
if _raw_origins.strip() == "*":
    _cors_origins = ["*"]
else:
    _cors_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["*"],
)

# Compresión de respuestas para reducir latencia de red entre frontend y backend.
app.add_middleware(GZipMiddleware, minimum_size=1024)


# Middleware para tiempo de respuesta (útil para debugging)
@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(round(process_time, 3))
    return response


# Routers
app.include_router(auth_router, prefix=settings.API_V1_PREFIX)
app.include_router(semestres_router, prefix=settings.API_V1_PREFIX)
app.include_router(dashboard_router, prefix=settings.API_V1_PREFIX)
app.include_router(materias_router, prefix=settings.API_V1_PREFIX)
app.include_router(tareas_router, prefix=settings.API_V1_PREFIX)
app.include_router(notas_router, prefix=settings.API_V1_PREFIX)
app.include_router(archivos_router, prefix=settings.API_V1_PREFIX)
app.include_router(audio_router, prefix=settings.API_V1_PREFIX)
app.include_router(ws_router, prefix=settings.API_V1_PREFIX)
app.include_router(ws_sync_router, prefix=settings.API_V1_PREFIX)
app.include_router(uploads_router, prefix=settings.API_V1_PREFIX)
app.include_router(worker_router, prefix=settings.API_V1_PREFIX)


@app.get("/", tags=["root"])
async def root():
    """Endpoint raíz con información de la API."""
    return {
        "name": "M4A API",
        "version": "1.0.0",
        "docs": "/docs",
        "status": "running"
    }


@app.get("/health", tags=["health"])
async def health_check():
    """Health check para monitoreo."""
    return {"status": "healthy", "service": "m4a-backend"}


@app.get("/metrics", tags=["metrics"])
async def metrics(request: Request):
    """Prometheus metrics endpoint (requires valid API key or admin token)."""
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth.split(" ", 1)[1] != settings.METRICS_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")
    payload, content_type = get_metrics_payload()
    return Response(content=payload, media_type=content_type)