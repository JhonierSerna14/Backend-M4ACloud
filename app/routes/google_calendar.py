"""Routes for Google Calendar OAuth and sync."""
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_google_oauth_state, verify_google_oauth_state
from app.core.semestre import get_semestre_actual
from app.models.usuario import Usuario
from app.schemas.google_calendar import (
    GoogleCalendarAuthUrlResponse,
    GoogleCalendarStatusResponse,
    GoogleCalendarSyncResponse,
)
from app.services.google_calendar_service import (
    bulk_sync_semestre,
    connect_user,
    count_pending_sync,
    disconnect_user,
    exchange_code,
    get_auth_url,
    is_google_calendar_configured,
)

router = APIRouter(prefix="/google-calendar", tags=["google-calendar"])


def _frontend_redirect(status_value: str, message: str | None = None) -> RedirectResponse:
    params = {"gcal": status_value}
    if message:
        params["gcal_message"] = message
    url = f"{settings.FRONTEND_URL.rstrip('/')}/?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=status.HTTP_302_FOUND)


@router.get("/status", response_model=GoogleCalendarStatusResponse)
def get_google_calendar_status(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    configured = is_google_calendar_configured()
    connected = bool(current_user.google_calendar_sync_enabled and current_user.google_refresh_token)

    calendar_name = None
    pending_count = 0
    message = None

    if not configured:
        message = "Google Calendar no está configurado en el servidor"
    elif connected:
        semestre = get_semestre_actual(db, current_user)
        calendar_name = f"M4A - {semestre.codigo}"
        pending_count = count_pending_sync(db, current_user)

    return GoogleCalendarStatusResponse(
        connected=connected,
        configured=configured,
        calendar_name=calendar_name,
        connected_at=current_user.google_calendar_connected_at,
        pending_count=pending_count,
        message=message,
    )


@router.get("/auth/url", response_model=GoogleCalendarAuthUrlResponse)
def get_google_auth_url(current_user: Usuario = Depends(get_current_user)):
    if not is_google_calendar_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google Calendar no está configurado en el servidor",
        )

    state = create_google_oauth_state(current_user.id)
    return GoogleCalendarAuthUrlResponse(authorization_url=get_auth_url(state))


@router.get("/auth/callback")
def google_auth_callback(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
):
    if error:
        return _frontend_redirect("error", error)

    if not code or not state:
        return _frontend_redirect("error", "Faltan parámetros de autorización")

    if not is_google_calendar_configured():
        return _frontend_redirect("error", "Google Calendar no configurado")

    try:
        user_id = verify_google_oauth_state(state)
    except ValueError as exc:
        return _frontend_redirect("error", str(exc))

    user = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not user:
        return _frontend_redirect("error", "Usuario no encontrado")

    try:
        refresh_token = exchange_code(code)
        semestre = get_semestre_actual(db, user)
        connect_user(db, user, refresh_token, semestre.codigo)
        bulk_sync_semestre(db, user)
    except Exception as exc:
        return _frontend_redirect("error", str(exc))

    return _frontend_redirect("connected")


@router.post("/disconnect", status_code=status.HTTP_200_OK)
def disconnect_google_calendar(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    disconnect_user(db, current_user)
    return {"ok": True}


@router.post("/sync", response_model=GoogleCalendarSyncResponse)
def manual_google_sync(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
):
    if not current_user.google_calendar_sync_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google Calendar no está conectado",
        )

    result = bulk_sync_semestre(db, current_user)
    return GoogleCalendarSyncResponse(**result)
