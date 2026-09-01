from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.semestre import Semestre
from app.models.materia import Materia
from app.models.usuario import Usuario


def get_semestre_actual(db: Session, user: Usuario) -> Semestre:
    """Returns the user's currently active semester or raises 404."""
    if not user.semestre_actual_id:
        raise HTTPException(
            status_code=404,
            detail="No hay semestre activo configurado",
        )

    semestre = db.query(Semestre).filter(
        Semestre.id == user.semestre_actual_id,
        Semestre.usuario_id == user.id,
    ).first()

    if not semestre:
        raise HTTPException(
            status_code=404,
            detail="Semestre activo no encontrado",
        )

    return semestre


def get_latest_semestre(db: Session, user: Usuario) -> Semestre | None:
    """Returns the most recent semester for the user (by codigo desc)."""
    return db.query(Semestre).filter(
        Semestre.usuario_id == user.id,
    ).order_by(Semestre.codigo.desc()).first()


def is_editable_semestre(db: Session, user: Usuario, semestre: Semestre) -> bool:
    """Only the latest semester allows write operations."""
    latest = get_latest_semestre(db, user)
    return latest is not None and latest.id == semestre.id


def require_editable_semestre(db: Session, user: Usuario, semestre: Semestre) -> None:
    """Raises 403 if the semester is archived (not the latest)."""
    if not is_editable_semestre(db, user, semestre):
        raise HTTPException(
            status_code=403,
            detail="Este semestre es de solo lectura (archivo). Cambia al semestre actual para editar.",
        )


def get_materia_en_semestre_actual(db: Session, user: Usuario, materia_id: int) -> Materia:
    """Returns a materia that belongs to the user's active semester."""
    semestre = get_semestre_actual(db, user)
    materia = db.query(Materia).filter(
        Materia.id == materia_id,
        Materia.usuario_id == user.id,
        Materia.semestre_id == semestre.id,
    ).first()
    if not materia:
        raise HTTPException(status_code=404, detail="Materia no encontrada")
    return materia


def get_materia_editable(db: Session, user: Usuario, materia_id: int) -> Materia:
    """Returns a materia in the active editable semester for write operations."""
    semestre = get_semestre_actual(db, user)
    require_editable_semestre(db, user, semestre)
    return get_materia_en_semestre_actual(db, user, materia_id)
