"""User-scoped WebSocket connection registry for realtime CRUD sync."""
from typing import Any, Dict, Set
import asyncio

from fastapi import WebSocket
from loguru import logger

_user_connections: Dict[int, Set[WebSocket]] = {}
_user_lock = asyncio.Lock()


async def register_user(user_id: int, websocket: WebSocket):
    async with _user_lock:
        conns = _user_connections.setdefault(user_id, set())
        conns.add(websocket)
        logger.info(f"WS register user: user_id={user_id} connections={len(conns)}")


async def unregister_user(user_id: int, websocket: WebSocket):
    async with _user_lock:
        conns = _user_connections.get(user_id)
        if not conns:
            return
        conns.discard(websocket)
        logger.info(f"WS unregister user: user_id={user_id} remaining={len(conns)}")
        if not conns:
            _user_connections.pop(user_id, None)


async def _safe_send_user(user_id: int, websocket: WebSocket, message: Any):
    try:
        await websocket.send_json(message)
    except Exception as ex:
        logger.warning(f"WS send user failed user_id={user_id}: {ex}")
        try:
            await unregister_user(user_id, websocket)
        except Exception:
            pass


async def broadcast_user(user_id: int, message: Any):
    conns = list((_user_connections.get(user_id) or set()))
    if conns:
        await asyncio.gather(*[_safe_send_user(user_id, ws, message) for ws in conns])


async def get_user_connections_count(user_id: int) -> int:
    async with _user_lock:
        return len(_user_connections.get(user_id, set()))
