"""
Configuración de base de datos PostgreSQL con SQLAlchemy.
Pool de conexiones optimizado para producción.
"""
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings


# Configuración de encoding
os.environ["PGCLIENTENCODING"] = "UTF8"


def _use_null_pool(database_url: str) -> bool:
    """
    En Supabase pooler conviene no mantener conexiones vivas en SQLAlchemy.
    Esto evita saturar clientes cuando hay varias pestañas/dispositivos.
    """
    return "pooler.supabase.com" in (database_url or "")

# Configuración de engine.
engine_kwargs = {
    "echo": False,
    "pool_pre_ping": True,
    "connect_args": {"client_encoding": "utf8"} if settings.DATABASE_URL.startswith("postgresql") else {},
}

if _use_null_pool(settings.DATABASE_URL):
    # Crucial para no agotar MaxClients en Supabase Session/Pooler.
    engine_kwargs["poolclass"] = NullPool
else:
    engine_kwargs["pool_size"] = settings.DB_POOL_SIZE
    engine_kwargs["max_overflow"] = settings.DB_MAX_OVERFLOW
    engine_kwargs["pool_timeout"] = settings.DB_POOL_TIMEOUT
    engine_kwargs["pool_recycle"] = settings.DB_POOL_RECYCLE

engine = create_engine(settings.DATABASE_URL, **engine_kwargs)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """
    Dependency para obtener sesión de DB.
    Uso: db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    """
    Context manager para uso fuera de FastAPI.
    Uso: with get_db_context() as db: ...
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()