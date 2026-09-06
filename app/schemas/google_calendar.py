"""Schemas for Google Calendar integration."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class GoogleCalendarStatusResponse(BaseModel):
    connected: bool
    configured: bool
    calendar_name: Optional[str] = None
    connected_at: Optional[datetime] = None
    pending_count: int = 0
    message: Optional[str] = None


class GoogleCalendarAuthUrlResponse(BaseModel):
    authorization_url: str


class GoogleCalendarSyncResponse(BaseModel):
    synced: int
    skipped: int
    errors: int
