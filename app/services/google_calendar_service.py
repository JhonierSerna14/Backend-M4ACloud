"""Google Calendar OAuth and one-way sync service."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger
from sqlalchemy.orm import Session, joinedload

from app.core.config import settings
from app.core.security import create_google_oauth_state, verify_google_oauth_state
from app.core.semestre import get_semestre_actual, is_editable_semestre
from app.core.token_crypto import decrypt_token, encrypt_token
from app.models.enums import TareaEstado
from app.models.materia import Materia
from app.models.tarea import Tarea
from app.models.usuario import Usuario

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
OAUTH_STATE_PURPOSE = "google_oauth_state"


def is_google_calendar_configured() -> bool:
    return bool(
        settings.GOOGLE_CLIENT_ID
        and settings.GOOGLE_CLIENT_SECRET
        and settings.GOOGLE_REDIRECT_URI
    )


def _client_config() -> dict[str, Any]:
    return {
        "web": {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.GOOGLE_REDIRECT_URI],
        }
    }


def get_auth_url(user_id: int) -> str:
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    flow.code_verifier = secrets.token_urlsafe(64)
    state = create_google_oauth_state(user_id, flow.code_verifier)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url


def exchange_code(code: str, state: str) -> str:
    _, code_verifier = verify_google_oauth_state(state)
    flow = Flow.from_client_config(_client_config(), scopes=SCOPES)
    flow.redirect_uri = settings.GOOGLE_REDIRECT_URI
    flow.fetch_token(code=code, code_verifier=code_verifier)
    credentials = flow.credentials
    if not credentials.refresh_token:
        raise ValueError("Google no devolvió refresh token. Revoca el acceso previo e intenta de nuevo.")
    return credentials.refresh_token


def _build_credentials(user: Usuario) -> Credentials | None:
    if not user.google_refresh_token:
        return None
    try:
        refresh_token = decrypt_token(user.google_refresh_token)
    except ValueError:
        logger.warning(f"Could not decrypt Google refresh token for user {user.id}")
        return None

    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=SCOPES,
    )
    credentials.refresh(Request())
    return credentials


def _get_calendar_service(user: Usuario):
    credentials = _build_credentials(user)
    if not credentials:
        return None
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _calendar_name(semestre_codigo: str) -> str:
    return f"M4A - {semestre_codigo}"


def ensure_calendar(user: Usuario, semestre_codigo: str) -> str:
    service = _get_calendar_service(user)
    if not service:
        raise ValueError("No hay credenciales de Google Calendar válidas")

    if user.google_calendar_id:
        try:
            service.calendars().get(calendarId=user.google_calendar_id).execute()
            return user.google_calendar_id
        except HttpError as exc:
            if exc.resp.status != 404:
                raise
            logger.info(f"Stored calendar {user.google_calendar_id} not found, creating new one")

    target_name = _calendar_name(semestre_codigo)
    calendar_list = service.calendarList().list().execute()
    for entry in calendar_list.get("items", []):
        if entry.get("summary") == target_name:
            return entry["id"]

    created = service.calendars().insert(
        body={
            "summary": target_name,
            "description": "Eventos académicos sincronizados desde M4A",
            "timeZone": settings.GOOGLE_CALENDAR_TIMEZONE,
        }
    ).execute()
    return created["id"]


def _hex_to_google_color_id(hex_color: str | None) -> str | None:
    if not hex_color:
        return None
    palette = {
        "#7986cb": "1",
        "#33b679": "2",
        "#8e24aa": "3",
        "#e67c73": "4",
        "#f6bf26": "5",
        "#f4511e": "6",
        "#039be5": "7",
        "#616161": "8",
        "#3f51b5": "9",
        "#0b8043": "10",
        "#d50000": "11",
    }
    normalized = hex_color.lower()
    if normalized in palette:
        return palette[normalized]
    return str((sum(ord(c) for c in normalized) % 11) + 1)


def _event_summary(tarea: Tarea) -> str:
    prefix = f"[{tarea.tipo.value}]"
    if tarea.estado == TareaEstado.COMPLETADA:
        prefix = "[Completada]"
    return f"{prefix} {tarea.titulo}"


def tarea_to_event(tarea: Tarea, materia: Materia | None) -> dict[str, Any]:
    materia_nombre = materia.nombre if materia else "Sin materia"
    estado_label = tarea.estado.value.replace("_", " ").title()
    description_parts = [
        f"Materia: {materia_nombre}",
        f"Estado: {estado_label}",
        f"Tipo: {tarea.tipo.value}",
    ]
    if tarea.descripcion:
        description_parts.append("")
        description_parts.append(tarea.descripcion)

    body: dict[str, Any] = {
        "summary": _event_summary(tarea),
        "description": "\n".join(description_parts),
    }

    color_id = _hex_to_google_color_id(materia.color if materia else None)
    if color_id:
        body["colorId"] = color_id

    if not tarea.fecha_limite:
        return body

    if tarea.hora_limite:
        start_dt = datetime.strptime(
            f"{tarea.fecha_limite.isoformat()} {tarea.hora_limite}",
            "%Y-%m-%d %H:%M",
        )
        end_dt = start_dt + timedelta(hours=1)
        body["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": settings.GOOGLE_CALENDAR_TIMEZONE,
        }
        body["end"] = {
            "dateTime": end_dt.isoformat(),
            "timeZone": settings.GOOGLE_CALENDAR_TIMEZONE,
        }
    else:
        next_day = tarea.fecha_limite + timedelta(days=1)
        body["start"] = {"date": tarea.fecha_limite.isoformat()}
        body["end"] = {"date": next_day.isoformat()}

    return body


def _disable_google_sync(db: Session, user: Usuario) -> None:
    user.google_calendar_sync_enabled = False
    user.google_refresh_token = None
    user.google_calendar_id = None
    user.google_calendar_connected_at = None
    db.commit()


def _handle_google_auth_error(db: Session, user: Usuario, exc: Exception) -> None:
    message = str(exc).lower()
    if "invalid_grant" in message or "token has been expired or revoked" in message:
        logger.warning(f"Google token revoked for user {user.id}: {exc}")
        _disable_google_sync(db, user)


def sync_tarea_create(db: Session, user: Usuario, tarea: Tarea) -> None:
    if not user.google_calendar_sync_enabled or not tarea.fecha_limite:
        return

    semestre = get_semestre_actual(db, user)
    if not is_editable_semestre(db, user, semestre):
        return

    service = _get_calendar_service(user)
    if not service:
        return

    calendar_id = ensure_calendar(user, semestre.codigo)
    if user.google_calendar_id != calendar_id:
        user.google_calendar_id = calendar_id
        db.commit()

    try:
        event = service.events().insert(
            calendarId=calendar_id,
            body=tarea_to_event(tarea, tarea.materia),
        ).execute()
        tarea.google_event_id = event.get("id")
        db.commit()
    except Exception as exc:
        logger.error(f"Google sync create failed for tarea {tarea.id}: {exc}")
        _handle_google_auth_error(db, user, exc)


def sync_tarea_update(db: Session, user: Usuario, tarea: Tarea) -> None:
    if not user.google_calendar_sync_enabled:
        return

    semestre = get_semestre_actual(db, user)
    if not is_editable_semestre(db, user, semestre):
        return

    if not tarea.fecha_limite:
        if tarea.google_event_id:
            sync_tarea_delete(db, user, tarea.google_event_id, calendar_id=user.google_calendar_id)
            tarea.google_event_id = None
            db.commit()
        return

    service = _get_calendar_service(user)
    if not service:
        return

    calendar_id = ensure_calendar(user, semestre.codigo)
    if user.google_calendar_id != calendar_id:
        user.google_calendar_id = calendar_id
        db.commit()

    body = tarea_to_event(tarea, tarea.materia)

    try:
        if tarea.google_event_id:
            service.events().patch(
                calendarId=calendar_id,
                eventId=tarea.google_event_id,
                body=body,
            ).execute()
        else:
            event = service.events().insert(calendarId=calendar_id, body=body).execute()
            tarea.google_event_id = event.get("id")
            db.commit()
    except HttpError as exc:
        if exc.resp.status == 404 and tarea.google_event_id:
            event = service.events().insert(calendarId=calendar_id, body=body).execute()
            tarea.google_event_id = event.get("id")
            db.commit()
            return
        logger.error(f"Google sync update failed for tarea {tarea.id}: {exc}")
        _handle_google_auth_error(db, user, exc)
    except Exception as exc:
        logger.error(f"Google sync update failed for tarea {tarea.id}: {exc}")
        _handle_google_auth_error(db, user, exc)


def sync_tarea_delete(
    db: Session,
    user: Usuario,
    google_event_id: str | None,
    calendar_id: str | None = None,
) -> None:
    if not user.google_calendar_sync_enabled or not google_event_id:
        return

    service = _get_calendar_service(user)
    if not service:
        return

    target_calendar = calendar_id or user.google_calendar_id
    if not target_calendar:
        return

    try:
        service.events().delete(calendarId=target_calendar, eventId=google_event_id).execute()
    except HttpError as exc:
        if exc.resp.status != 404:
            logger.error(f"Google sync delete failed for event {google_event_id}: {exc}")
            _handle_google_auth_error(db, user, exc)
    except Exception as exc:
        logger.error(f"Google sync delete failed for event {google_event_id}: {exc}")
        _handle_google_auth_error(db, user, exc)


def bulk_sync_semestre(db: Session, user: Usuario) -> dict[str, int]:
    if not user.google_calendar_sync_enabled:
        return {"synced": 0, "skipped": 0, "errors": 0}

    semestre = get_semestre_actual(db, user)
    calendar_id = ensure_calendar(user, semestre.codigo)
    user.google_calendar_id = calendar_id
    db.commit()

    tareas = (
        db.query(Tarea)
        .options(joinedload(Tarea.materia))
        .join(Materia)
        .filter(
            Materia.usuario_id == user.id,
            Materia.semestre_id == semestre.id,
            Tarea.fecha_limite.isnot(None),
        )
        .all()
    )

    synced = 0
    skipped = 0
    errors = 0

    for tarea in tareas:
        try:
            if tarea.google_event_id:
                sync_tarea_update(db, user, tarea)
            else:
                sync_tarea_create(db, user, tarea)
            synced += 1
        except Exception as exc:
            logger.error(f"Bulk sync failed for tarea {tarea.id}: {exc}")
            errors += 1

    return {"synced": synced, "skipped": skipped, "errors": errors}


def count_pending_sync(db: Session, user: Usuario) -> int:
    semestre = get_semestre_actual(db, user)
    return (
        db.query(Tarea)
        .join(Materia)
        .filter(
            Materia.usuario_id == user.id,
            Materia.semestre_id == semestre.id,
            Tarea.fecha_limite.isnot(None),
            Tarea.google_event_id.is_(None),
        )
        .count()
    )


def store_refresh_token(user: Usuario, refresh_token: str) -> str:
    return encrypt_token(refresh_token)


def revoke_refresh_token(refresh_token_cipher: str | None) -> None:
    if not refresh_token_cipher:
        return
    try:
        refresh_token = decrypt_token(refresh_token_cipher)
    except ValueError:
        return

    import httpx

    try:
        httpx.post(
            "https://oauth2.googleapis.com/revoke",
            params={"token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )
    except Exception as exc:
        logger.warning(f"Could not revoke Google token: {exc}")


def connect_user(db: Session, user: Usuario, refresh_token: str, semestre_codigo: str) -> None:
    user.google_refresh_token = store_refresh_token(user, refresh_token)
    user.google_calendar_sync_enabled = True
    user.google_calendar_connected_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)

    calendar_id = ensure_calendar(user, semestre_codigo)
    user.google_calendar_id = calendar_id
    db.commit()


def disconnect_user(db: Session, user: Usuario) -> None:
    revoke_refresh_token(user.google_refresh_token)
    user.google_refresh_token = None
    user.google_calendar_id = None
    user.google_calendar_connected_at = None
    user.google_calendar_sync_enabled = False
    db.commit()
