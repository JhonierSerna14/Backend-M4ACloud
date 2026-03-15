"""
Esquemas Pydantic para validación de datos de Materia.
Define los modelos de entrada y salida para operaciones con materias académicas.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
class MateriaBase(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=100)
    descripcion: Optional[str] = None
    contenido_html: Optional[str] = None
    color: Optional[str] = None

class MateriaCreate(MateriaBase):
    pass

class MateriaUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=100)
    descripcion: Optional[str] = None
    contenido_html: Optional[str] = None
    color: Optional[str] = None

class MateriaResponse(MateriaBase):
    id: int
    usuario_id: int
    fecha_creacion: datetime
    total_notas: int = 0
    total_tareas: int = 0

    model_config = {"from_attributes": True}

class MateriaDetail(MateriaResponse):
    total_archivos: int = 0