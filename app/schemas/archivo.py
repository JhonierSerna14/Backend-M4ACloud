"""
Esquemas Pydantic para validación de datos de Archivo.
Define los modelos de entrada y salida para operaciones con archivos.
"""
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
class ArchivoBase(BaseModel):
    nombre: str
    tipo: str
    materia_id: int

class ArchivoCreate(ArchivoBase):
    ruta: str
    tamaño: Optional[int] = None

class ArchivoUpdate(BaseModel):
    nombre: Optional[str] = None
    materia_id: Optional[int] = None

class ArchivoResponse(ArchivoBase):
    id: int
    ruta: str
    tamaño: Optional[int] = None
    fecha_creacion: datetime

    model_config = {"from_attributes": True}