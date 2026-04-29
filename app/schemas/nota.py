"""
Schemas para Nota/Lienzo de clase.
Soporta creación manual o desde transcripción de audio.
"""
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import date, datetime


class AdjuntoResponse(BaseModel):
    """Archivo adjunto a una nota."""
    id: int
    nombre: str
    ruta: str
    tipo: str
    tamaño: Optional[int] = None
    fecha_creacion: datetime
    url: Optional[str] = None

    model_config = {"from_attributes": True}

    def model_dump(self, **kwargs):
        """Override para incluir URL normalizada en la serialización."""
        data = super().model_dump(**kwargs)
        ruta_normalizada = data.get('ruta', '').replace('\\', '/')
        from app.services import storage_service
        data['url'] = storage_service.get_public_url(ruta_normalizada)
        return data


class NotaBase(BaseModel):
    """Campos base de una nota."""
    titulo: str = Field(..., min_length=1, max_length=200)
    contenido: Optional[str] = None
    materia_id: int
    fecha_clase: Optional[date] = Field(None, description="Fecha de la clase")


class NotaCreate(NotaBase):
    """Crear nota manualmente (sin audio)."""
    pass


class NotaUpdate(BaseModel):
    """Actualizar nota - todos los campos opcionales."""
    titulo: Optional[str] = Field(None, min_length=1, max_length=200)
    contenido: Optional[str] = None
    materia_id: Optional[int] = None
    fecha_clase: Optional[date] = None


class NotaResponse(BaseModel):
    """Respuesta de nota."""
    id: int
    titulo: str
    contenido: Optional[str] = None
    materia_id: int
    fecha_clase: Optional[date] = None
    
    # Metadata de audio (si aplica)
    origen_audio: Optional[str] = None
    duracion_audio: Optional[int] = None
    idioma_detectado: Optional[str] = None

    # Estado y progreso
    status: Optional[str] = None
    status_message: Optional[str] = None
    progreso: Optional[int] = 0
    
    # Timestamps
    fecha_creacion: datetime
    fecha_actualizacion: Optional[datetime] = None
    materia_color: Optional[str] = None
    
    model_config = {"from_attributes": True}


class NotaListResponse(BaseModel):
    """Respuesta liviana para listados de notas (sin contenido completo)."""
    id: int
    titulo: str
    materia_id: int
    fecha_clase: Optional[date] = None

    origen_audio: Optional[str] = None
    duracion_audio: Optional[int] = None
    idioma_detectado: Optional[str] = None

    status: Optional[str] = None
    progreso: Optional[int] = 0

    fecha_creacion: datetime
    fecha_actualizacion: Optional[datetime] = None
    materia_nombre: Optional[str] = None
    materia_color: Optional[str] = None


class NotaDetail(NotaResponse):
    """Nota con sus adjuntos."""
    adjuntos: List[AdjuntoResponse] = []
    materia_nombre: Optional[str] = None