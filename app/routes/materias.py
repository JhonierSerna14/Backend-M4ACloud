"""
Rutas para gestión de materias académicas.
CRUD completo + estadísticas por materia.
"""
import random

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List, Optional

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models.usuario import Usuario
from app.models.materia import Materia
from app.models.nota import Nota
from app.models.tarea import Tarea
from app.models.archivo import Archivo
from app.schemas.materia import MateriaCreate, MateriaUpdate, MateriaResponse, MateriaDetail

router = APIRouter(prefix="/materias", tags=["materias"])

# Paleta de colores por defecto para asignación automática a materias
DEFAULT_PALETTE = [
    "#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#8b5cf6",
    "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1",
]


@router.post("/", response_model=MateriaResponse, status_code=status.HTTP_201_CREATED)
def create_materia(
    materia_data: MateriaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Crea una nueva materia con color único por usuario."""
    # If color provided, validate uniqueness for this user
    if materia_data.color:
        exists = db.query(Materia).filter(
            Materia.usuario_id == current_user.id,
            Materia.color == materia_data.color
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="El color ya está asignado a otra materia")
        chosen_color = materia_data.color
    else:
        # Asignar primer color disponible de la paleta
        used = {m.color for m in db.query(Materia).filter(
            Materia.usuario_id == current_user.id, Materia.color.isnot(None)
        ).all()}
        chosen_color = next((c for c in DEFAULT_PALETTE if c not in used), None)
        if not chosen_color:
            # Paleta agotada: generar color aleatorio único
            for _ in range(10):
                c = "#%06x" % random.randint(0, 0xFFFFFF)
                if c not in used:
                    chosen_color = c
                    break
            if not chosen_color:
                raise HTTPException(status_code=400, detail="No hay colores disponibles. Elige uno manualmente.")

    new_materia = Materia(
        nombre=materia_data.nombre,
        descripcion=materia_data.descripcion,
        usuario_id=current_user.id,
        color=chosen_color
    )
    db.add(new_materia)
    db.commit()
    db.refresh(new_materia)
    return new_materia


@router.get("/", response_model=List[MateriaResponse])
def get_materias(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    search: Optional[str] = Query(None, description="Buscar por nombre"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista materias del usuario con búsqueda opcional y counters de notas/tareas."""
    # Subqueries para contar notas y tareas por materia sin duplicar rows
    sub_notas = db.query(func.count(Nota.id)).filter(Nota.materia_id == Materia.id).correlate(Materia).scalar_subquery()
    sub_tareas = db.query(func.count(Tarea.id)).filter(Tarea.materia_id == Materia.id).correlate(Materia).scalar_subquery()

    base_q = db.query(Materia, sub_notas.label('notas_count'), sub_tareas.label('tareas_count')).filter(Materia.usuario_id == current_user.id)

    if search:
        base_q = base_q.filter(Materia.nombre.ilike(f"%{search}%"))

    rows = base_q.order_by(Materia.nombre).offset(skip).limit(limit).all()

    resultados = []
    for materia, notas_count, tareas_count in rows:
        resultados.append({
            'id': materia.id,
            'nombre': materia.nombre,
            'descripcion': materia.descripcion,
            'contenido_html': materia.contenido_html,
            'usuario_id': materia.usuario_id,
            'fecha_creacion': materia.fecha_creacion,
            'color': materia.color,
            'total_notas': int(notas_count or 0),
            'total_tareas': int(tareas_count or 0)
        })

    return resultados

@router.get("/{materia_id}", response_model=MateriaDetail)
def get_materia(
    materia_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene materia con contadores de elementos relacionados."""
    materia = db.query(Materia).filter(
        Materia.id == materia_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not materia:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    
    # Contadores eficientes
    notas_count = db.query(func.count(Nota.id)).filter(Nota.materia_id == materia_id).scalar()
    tareas_count = db.query(func.count(Tarea.id)).filter(Tarea.materia_id == materia_id).scalar()
    archivos_count = db.query(func.count(Archivo.id)).filter(Archivo.materia_id == materia_id).scalar()
    
    return MateriaDetail(
        id=materia.id,
        nombre=materia.nombre,
        descripcion=materia.descripcion,
        contenido_html=materia.contenido_html,
        color=materia.color,
        usuario_id=materia.usuario_id,
        fecha_creacion=materia.fecha_creacion,
        total_notas=notas_count,
        total_tareas=tareas_count,
        total_archivos=archivos_count
    )

@router.put("/{materia_id}", response_model=MateriaResponse)
def update_materia(
    materia_id: int,
    materia_data: MateriaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza una materia. Valida unicidad de color si se modifica."""
    materia = db.query(Materia).filter(
        Materia.id == materia_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not materia:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    
    update_data = materia_data.model_dump(exclude_unset=True)

    if "color" in update_data and update_data["color"]:
        exists = db.query(Materia).filter(
            Materia.usuario_id == current_user.id,
            Materia.color == update_data["color"],
            Materia.id != materia_id
        ).first()
        if exists:
            raise HTTPException(status_code=400, detail="El color ya está asignado a otra materia")

    for key, value in update_data.items():
        setattr(materia, key, value)
    
    db.commit()
    db.refresh(materia)
    return materia


@router.delete("/{materia_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_materia(
    materia_id: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Elimina una materia y sus elementos asociados."""
    materia = db.query(Materia).filter(
        Materia.id == materia_id,
        Materia.usuario_id == current_user.id
    ).first()
    
    if not materia:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    
    db.delete(materia)
    db.commit()
    return None