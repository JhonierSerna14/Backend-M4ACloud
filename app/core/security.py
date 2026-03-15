"""
Utilidades de seguridad para manejo de contraseñas y tokens JWT.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Union

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Expiración por defecto según tipo de token
_DEFAULT_EXPIRY = {
    "access": lambda: timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    "refresh": lambda: timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS),
}


def _create_token(subject: Union[str, int], token_type: str, expires_delta: Optional[timedelta] = None) -> str:
    """Crea un token JWT firmado con el tipo y expiración indicados."""
    expire = datetime.now(timezone.utc) + (expires_delta or _DEFAULT_EXPIRY[token_type]())
    payload = {"exp": expire, "sub": str(subject), "type": token_type}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: Union[str, int], expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(subject, "access", expires_delta)


def create_refresh_token(subject: Union[str, int], expires_delta: Optional[timedelta] = None) -> str:
    return _create_token(subject, "refresh", expires_delta)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)
