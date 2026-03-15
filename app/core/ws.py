"""
Gestor de conexiones WebSocket para notificaciones en tiempo real.
Mapea nota_id a un conjunto de WebSocket activos y permite broadcast.
"""
from typing import Dict, Set, Any
from fastapi import WebSocket
import asyncio
from loguru import logger

# Map nota_id -> set of WebSocket
_connections: Dict[int, Set[WebSocket]] = {}
_lock = asyncio.Lock()

async def register(nota_id: int, websocket: WebSocket):
    async with _lock:
        conns = _connections.setdefault(nota_id, set())
        conns.add(websocket)
        logger.info(f"WS register: nota={nota_id} connections={len(conns)}")

async def unregister(nota_id: int, websocket: WebSocket):
    async with _lock:
        conns = _connections.get(nota_id)
        if not conns:
            return
        conns.discard(websocket)
        logger.info(f"WS unregister: nota={nota_id} remaining={len(conns)}")
        if not conns:
            _connections.pop(nota_id, None)

async def _safe_send(nota_id: int, ws: WebSocket, message: Any):
    try:
        await ws.send_json(message)
        logger.debug(f"WS send to nota {nota_id} success")
    except Exception as e:
        logger.warning(f"WS send failed for nota {nota_id}: {e}")
        # Remove dead connection
        try:
            await unregister(nota_id, ws)
        except Exception:
            pass


async def broadcast(nota_id: int, message: Any):
    # Fire-and-forget sends so slow clients don't block processing
    conns = list((_connections.get(nota_id) or set()))
    logger.debug(f"Broadcasting to nota {nota_id}, {len(conns)} connections: {message}")
    for ws in conns:
        # schedule _safe_send and don't await
        try:
            asyncio.create_task(_safe_send(nota_id, ws, message))
        except Exception as e:
            logger.warning(f"Failed to schedule WS send for nota {nota_id}: {e}")
            # fallback: try to unregister
            try:
                await unregister(nota_id, ws)
            except Exception:
                pass


async def get_connections_count(nota_id: int) -> int:
    async with _lock:
        return len(_connections.get(nota_id, set()))
