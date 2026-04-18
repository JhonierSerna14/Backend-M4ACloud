"""Helpers to build user-scoped sync event envelopes."""
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

SYNC_PROTOCOL_VERSION = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_sync_connected_event() -> dict[str, Any]:
    return {
        "event_type": "sync.connected",
        "protocol_version": SYNC_PROTOCOL_VERSION,
        "scope": "user",
        "occurred_at": _now_iso(),
    }


def build_sync_event(
    *,
    action: str,
    entity: str,
    entity_id: Optional[int],
    payload: Optional[dict[str, Any]] = None,
    affected_collections: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    return {
        "event_type": "sync.event",
        "action": action,
        "entity": entity,
        "id": entity_id,
        "payload": payload,
        "affected_collections": list(affected_collections or []),
        "occurred_at": _now_iso(),
    }
