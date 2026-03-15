"""
Configuración centralizada de la aplicación.
Todas las variables se cargan automáticamente desde .env por pydantic_settings.
"""
import os

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Configuración de M4A Backend. Valores por defecto para desarrollo local."""

    # Base de datos
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/m4a_db"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800

    # JWT
    JWT_SECRET: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Archivos
    UPLOAD_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
    MAX_UPLOAD_SIZE_MB: int = 300

    # Storage backend: local | supabase
    STORAGE_BACKEND: str = "local"
    SUPABASE_URL: str = ""
    SUPABASE_SERVICE_ROLE_KEY: str = ""
    SUPABASE_STORAGE_BUCKET: str = "m4a-files"

    # Audio storage backend: storage | dropbox
    AUDIO_STORAGE_BACKEND: str = "storage"
    DROPBOX_ACCESS_TOKEN: str = ""
    DROPBOX_APP_KEY: str = ""
    DROPBOX_APP_SECRET: str = ""
    DROPBOX_REFRESH_TOKEN: str = ""
    DROPBOX_AUDIO_ROOT_PATH: str = "/M4A-Audio-Temp"

    # Worker: clave secreta compartida con el worker local
    WORKER_SECRET_KEY: str = "change-me-worker-secret"

    # CORS orígenes permitidos (separados por coma)
    BACKEND_CORS_ORIGINS: str = "*"

    # Proveedor de resumen IA: groq | gemini | disabled
    SUMMARY_PROVIDER: str = "gemini"

    # Groq
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"

    # Google Gemini (fallback)
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # Chunking de transcripciones para IA
    MAX_TRANSCRIPT_SIZE_SINGLE: int = 15000
    GROQ_REQUEST_DELAY: float = 2.5
    AI_TEMPERATURE: float = 0.1
    AI_REQUEST_TIMEOUT: int = 120

    # Whisper - Transcripción de audio
    WHISPER_MODEL_SIZE: str = "medium"
    WHISPER_COMPUTE_TYPE: str = "int8_float16"
    WHISPER_DEVICE: str = "cuda"
    CHUNK_DURATION_MINUTES: int = 5
    CHUNK_OVERLAP_SECONDS: int = 30
    MAX_PARALLEL_CHUNKS: int = 2
    MAX_CONCURRENT_TRANSCRIPTIONS: int = 1

    # Whisper - Procesamiento GPU
    WHISPER_BATCH_SIZE: int = 16
    VAD_FILTER_ENABLED: bool = True
    VAD_MIN_SPEECH_DURATION_MS: int = 250
    VAD_SPEECH_PAD_MS: int = 400

    # Whisper - Parámetros de precisión
    WHISPER_BEAM_SIZE: int = 5
    WHISPER_BEST_OF: int = 5
    WHISPER_TEMPERATURE: float = 0.0
    WHISPER_LANGUAGE: str = "es"
    WHISPER_COMPRESSION_RATIO: float = 2.0
    WHISPER_NO_SPEECH_THRESHOLD: float = 0.7
    WHISPER_REPETITION_PENALTY: float = 1.1

    # Metrics
    METRICS_API_KEY: str = "change-me-metrics-key"

    # Aplicación
    APP_NAME: str = "M4A Backend"
    API_V1_PREFIX: str = "/api/v1"
    LOG_LEVEL: str = "INFO"

    # Directorio para transcripciones en modo debug
    DEBUG_TRANSCRIPTS_DIR: str = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "transcripts"
    )

    # Timeouts
    TRANSCRIPTION_TIMEOUT: int = 1800

    @property
    def MAX_UPLOAD_SIZE(self) -> int:
        """Tamaño máximo de subida en bytes."""
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()