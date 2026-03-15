"""
Esquemas Pydantic para validación de datos de Usuario.
Define los modelos de entrada y salida para operaciones con usuarios.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime
class UsuarioBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=100)
    email: EmailStr = Field(...)

class UsuarioCreate(UsuarioBase):
    password: str = Field(..., min_length=6)

class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=6)

class UsuarioResponse(UsuarioBase):
    id: int
    is_active: bool
    fecha_creacion: datetime

    model_config = {"from_attributes": True}