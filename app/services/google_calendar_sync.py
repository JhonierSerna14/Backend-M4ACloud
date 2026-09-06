"""Background task helpers for Google Calendar sync."""
from loguru import logger

from sqlalchemy.orm import joinedload

from app.core.database import get_db_context
from app.models.tarea import Tarea
from app.models.usuario import Usuario
from app.services.google_calendar_service import (
    bulk_sync_semestre,
    sync_tarea_create,
    sync_tarea_delete,
    sync_tarea_update,
)


def sync_tarea_to_google(
    user_id: int,
    action: str,
    tarea_id: int | None = None,
    google_event_id: str | None = None,
) -> None:
    try:
        with get_db_context() as db:
            user = db.query(Usuario).filter(Usuario.id == user_id).first()
            if not user or not user.google_calendar_sync_enabled:
                return

            if action == "delete":
                sync_tarea_delete(
                    db,
                    user,
                    google_event_id,
                    calendar_id=user.google_calendar_id,
                )
                return

            if not tarea_id:
                return

            tarea = (
                db.query(Tarea)
                .options(joinedload(Tarea.materia))
                .filter(Tarea.id == tarea_id)
                .first()
            )
            if not tarea:
                return

            if action == "create":
                sync_tarea_create(db, user, tarea)
            elif action == "update":
                sync_tarea_update(db, user, tarea)
    except Exception as exc:
        logger.error(f"Background Google sync failed (user={user_id}, action={action}): {exc}")


def bulk_sync_user_semestre(user_id: int) -> None:
    try:
        with get_db_context() as db:
            user = db.query(Usuario).filter(Usuario.id == user_id).first()
            if not user or not user.google_calendar_sync_enabled:
                return
            bulk_sync_semestre(db, user)
    except Exception as exc:
        logger.error(f"Background bulk Google sync failed (user={user_id}): {exc}")
