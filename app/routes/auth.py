"""
Rutas de autenticación para login, registro y gestión de tokens JWT.
Maneja el proceso completo de autenticación de usuarios.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, verify_password, get_password_hash
from app.core.config import settings
from app.core.auth import get_current_user, get_refresh_token_user
from app.models.usuario import Usuario
from app.schemas.usuario import UsuarioCreate, UsuarioResponse
from app.schemas.token import Token

router = APIRouter(prefix="/auth", tags=["autenticación"])


def _create_token_pair(user_id: int) -> dict:
    """Genera un par de tokens (access + refresh) para el usuario."""
    access_token = create_access_token(
        user_id, expires_delta=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    refresh = create_refresh_token(
        user_id, expires_delta=timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    )
    return {"access_token": access_token, "refresh_token": refresh, "token_type": "bearer"}

@router.post("/register", response_model=UsuarioResponse, status_code=status.HTTP_201_CREATED)
def register_user(user_data: UsuarioCreate, db: Session = Depends(get_db)):
    """
    Registra un nuevo usuario en el sistema
    """
    # Verificar si el email ya existe
    db_user = db.query(Usuario).filter(Usuario.email == user_data.email).first()
    if db_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El email ya está registrado"
        )
    
    # Crear nuevo usuario
    hashed_password = get_password_hash(user_data.password)
    new_user = Usuario(
        nombre=user_data.nombre,
        email=user_data.email,
        password_hash=hashed_password
    )
    
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    return new_user

@router.post("/login", response_model=Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Inicia sesión y obtiene token JWT
    """
    # Buscar usuario por username (email)
    user = db.query(Usuario).filter(Usuario.email == form_data.username).first()
    
    # Verificar credenciales
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verificar que el usuario esté activo
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )
    
    # Crear tokens
    return _create_token_pair(user.id)

@router.post("/refresh", response_model=Token)
def refresh_token(
    user: Usuario = Depends(get_refresh_token_user)
):
    """
    Renueva el token de acceso usando un token de refresco
    """
    return _create_token_pair(user.id)

@router.get("/me", response_model=UsuarioResponse)
def get_current_user_info(current_user: Usuario = Depends(get_current_user)):
    """
    Obtiene información del usuario actual
    """
    return current_user