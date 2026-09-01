from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator
import re


CODIGO_SEMESTRE_PATTERN = re.compile(r"^\d{4}-\d{2}$")


class SemestreCreate(BaseModel):
    codigo: str = Field(..., min_length=7, max_length=7, description="Formato YYYY-NN, ej. 2026-02")
    nombre: Optional[str] = Field(None, max_length=100)

    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, value: str) -> str:
        if not CODIGO_SEMESTRE_PATTERN.match(value):
            raise ValueError("El código debe tener formato YYYY-NN (ej. 2026-01)")
        return value


class SemestreResponse(BaseModel):
    id: int
    codigo: str
    nombre: Optional[str] = None
    total_materias: int = 0
    es_actual: bool = False
    es_editable: bool = False
    fecha_creacion: datetime

    model_config = {"from_attributes": True}


class SemestreActualUpdate(BaseModel):
    semestre_id: int
