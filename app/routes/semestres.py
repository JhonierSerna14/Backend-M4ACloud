"""
Rutas para gestión de semestres académicos.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from app.core.database import get_db
from app.core.auth import get_current_user
from app.core.semestre import get_semestre_actual, get_latest_semestre, is_editable_semestre
from app.core.sync_events import build_sync_event
from app.core.user_ws import broadcast_user
from app.models.usuario import Usuario
from app.models.semestre import Semestre
from app.models.materia import Materia
from app.schemas.semestre import SemestreCreate, SemestreResponse, SemestreActualUpdate

router = APIRouter(prefix="/semestres", tags=["semestres"])


def _serialize_semestre(
    semestre: Semestre,
    total_materias: int,
    semestre_actual_id: int | None,
    latest_id: int | None,
) -> dict:
    return {
        "id": semestre.id,
        "codigo": semestre.codigo,
        "nombre": semestre.nombre,
        "total_materias": total_materias,
        "es_actual": semestre.id == semestre_actual_id,
        "es_editable": semestre.id == latest_id,
        "fecha_creacion": semestre.fecha_creacion,
    }


@router.get("/", response_model=List[SemestreResponse])
def get_semestres(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Lista semestres del usuario ordenados por código descendente."""
    sub_materias = (
        db.query(func.count(Materia.id))
        .filter(Materia.semestre_id == Semestre.id)
        .correlate(Semestre)
        .scalar_subquery()
    )

    rows = (
        db.query(Semestre, sub_materias.label("materias_count"))
        .filter(Semestre.usuario_id == current_user.id)
        .order_by(Semestre.codigo.desc())
        .all()
    )

    latest = get_latest_semestre(db, current_user)
    latest_id = latest.id if latest else None

    return [
        _serialize_semestre(
            semestre,
            int(materias_count or 0),
            current_user.semestre_actual_id,
            latest_id,
        )
        for semestre, materias_count in rows
    ]


@router.get("/actual", response_model=SemestreResponse)
def get_semestre_actual_endpoint(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Devuelve el semestre activo del usuario."""
    semestre = get_semestre_actual(db, current_user)
    total_materias = db.query(func.count(Materia.id)).filter(
        Materia.semestre_id == semestre.id
    ).scalar()
    latest = get_latest_semestre(db, current_user)

    return _serialize_semestre(
        semestre,
        int(total_materias or 0),
        current_user.semestre_actual_id,
        latest.id if latest else None,
    )


@router.post("/", response_model=SemestreResponse, status_code=status.HTTP_201_CREATED)
def create_semestre(
    semestre_data: SemestreCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Crea un semestre vacío y lo establece como actual."""
    exists = db.query(Semestre).filter(
        Semestre.usuario_id == current_user.id,
        Semestre.codigo == semestre_data.codigo,
    ).first()
    if exists:
        raise HTTPException(status_code=400, detail="Ya existe un semestre con ese código")

    nombre = semestre_data.nombre or f"Semestre {semestre_data.codigo}"
    new_semestre = Semestre(
        codigo=semestre_data.codigo,
        nombre=nombre,
        usuario_id=current_user.id,
    )
    db.add(new_semestre)
    db.flush()

    current_user.semestre_actual_id = new_semestre.id
    db.commit()
    db.refresh(new_semestre)
    db.refresh(current_user)

    payload = _serialize_semestre(new_semestre, 0, new_semestre.id, new_semestre.id)
    background_tasks.add_task(
        broadcast_user,
        current_user.id,
        build_sync_event(
            action="created",
            entity="semestre",
            entity_id=new_semestre.id,
            payload=payload,
            affected_collections=["semestres", "semestre-actual", "materias", "dashboard", "notas", "tareas"],
        ),
    )
    return payload


@router.put("/actual", response_model=SemestreResponse)
def set_semestre_actual(
    data: SemestreActualUpdate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    """Cambia el semestre activo del usuario."""
    semestre = db.query(Semestre).filter(
        Semestre.id == data.semestre_id,
        Semestre.usuario_id == current_user.id,
    ).first()
    if not semestre:
        raise HTTPException(status_code=404, detail="Semestre no encontrado")

    current_user.semestre_actual_id = semestre.id
    db.commit()
    db.refresh(current_user)

    total_materias = db.query(func.count(Materia.id)).filter(
        Materia.semestre_id == semestre.id
    ).scalar()
    latest = get_latest_semestre(db, current_user)
    payload = _serialize_semestre(
        semestre,
        int(total_materias or 0),
        semestre.id,
        latest.id if latest else None,
    )

    background_tasks.add_task(
        broadcast_user,
        current_user.id,
        build_sync_event(
            action="updated",
            entity="semestre",
            entity_id=semestre.id,
            payload=payload,
            affected_collections=["semestres", "semestre-actual", "materias", "dashboard", "notas", "tareas", "calendario"],
        ),
    )
    return payload
