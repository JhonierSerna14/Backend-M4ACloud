"""
Dependencias de autenticación para protección de rutas.
Maneja validación de tokens JWT y obtención de usuarios autenticados.
"""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from pydantic import ValidationError

from app.core.config import settings
from app.core.database import get_db
from app.models.usuario import Usuario
from app.schemas.token import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


def _validate_token(token: str, expected_type: str, db: Session) -> Usuario:
    """
    Valida un token JWT, verifica su tipo y expiración, y retorna el usuario asociado.
    
    Args:
        token: Token JWT a validar.
        expected_type: Tipo esperado ("access" o "refresh").
        db: Sesión de base de datos.
    
    Returns:
        Usuario autenticado.
    
    Raises:
        HTTPException: Si el token es inválido, expirado, o el usuario no existe.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="No se pudo validar las credenciales",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        token_data = TokenPayload(**payload)
        
        if token_data.type != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Token de {expected_type} inválido",
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        if datetime.now(timezone.utc) > token_data.exp:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expirado",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except (JWTError, ValidationError):
        raise credentials_exception
    
    user = db.query(Usuario).filter(Usuario.id == token_data.sub).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    return user


def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Usuario:
    """Obtiene el usuario actual a partir del token JWT de acceso."""
    return _validate_token(token, "access", db)


def get_refresh_token_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme)
) -> Usuario:
    """Obtiene el usuario actual a partir del token JWT de refresco."""
    return _validate_token(token, "refresh", db)