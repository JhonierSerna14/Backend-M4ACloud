"""
Schemas para Tarea/Evento académico.
Soporta diferentes tipos: tarea, parcial, entrega, etc.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, date
from enum import Enum
from app.schemas.materia import MateriaResponse


class TareaEstadoEnum(str, Enum):
    """Estado de la tarea."""
    PENDIENTE = "pendiente"
    EN_PROGRESO = "en_progreso"
    COMPLETADA = "completada"


class EventoTipoEnum(str, Enum):
    """Tipo de evento académico."""
    TAREA = "TAREA"
    PARCIAL = "PARCIAL"
    FINAL = "FINAL"
    QUIZ = "QUIZ"
    ENTREGA = "ENTREGA"
    EXPOSICION = "EXPOSICION"
    LECTURA = "LECTURA"
    OTRO = "OTRO"


class TareaBase(BaseModel):
    """Campos base de tarea."""
    titulo: str = Field(..., min_length=1, max_length=200)
    descripcion: Optional[str] = None
    tipo: EventoTipoEnum = EventoTipoEnum.TAREA
    fecha_limite: Optional[date] = None
    hora_limite: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$", description="Formato HH:MM")
    prioridad: int = Field(0, ge=0, le=2, description="0=normal, 1=importante, 2=urgente")
    materia_id: int
    nota_id: Optional[int] = Field(None, description="Vincular a una clase/nota")


class TareaCreate(TareaBase):
    """Crear tarea."""
    estado: TareaEstadoEnum = TareaEstadoEnum.PENDIENTE


class TareaUpdate(BaseModel):
    """Actualizar tarea - todos los campos opcionales."""
    titulo: Optional[str] = Field(None, min_length=1, max_length=200)
    descripcion: Optional[str] = None
    tipo: Optional[EventoTipoEnum] = None
    estado: Optional[TareaEstadoEnum] = None
    fecha_limite: Optional[date] = None
    hora_limite: Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    prioridad: Optional[int] = Field(None, ge=0, le=2)
    materia_id: Optional[int] = None
    nota_id: Optional[int] = None
    orden: Optional[int] = None


class TareaResponse(BaseModel):
    """Respuesta de tarea."""
    id: int
    titulo: str
    descripcion: Optional[str] = None
    tipo: EventoTipoEnum
    estado: TareaEstadoEnum
    prioridad: int
    fecha_limite: Optional[date] = None
    hora_limite: Optional[str] = None
    materia_id: int
    materia: Optional[MateriaResponse] = None
    nota_id: Optional[int] = None
    fecha_creacion: datetime
    fecha_actualizacion: Optional[datetime] = None
    orden: Optional[int] = 0

    model_config = {"from_attributes": True}


