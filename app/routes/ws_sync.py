from fastapi import APIRouter, HTTPException, Query, WebSocket
from loguru import logger

from app.core.auth import get_current_user
from app.core.database import SessionLocal
from app.core.sync_events import build_sync_connected_event
from app.core.user_ws import register_user, unregister_user

router = APIRouter(tags=["ws"])


@router.websocket("/sync/events")
async def user_sync_ws(websocket: WebSocket, token: str = Query(...)):
    await websocket.accept()

    db = SessionLocal()
    current_user = None
    try:
        current_user = get_current_user(db, token)
    except HTTPException as ex:
        logger.warning(f"WS sync auth failed: {ex.detail}")
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        return
    finally:
        db.close()

    await register_user(current_user.id, websocket)

    try:
        await websocket.send_json(build_sync_connected_event())
    except Exception:
        pass

    try:
        while True:
            msg = await websocket.receive()
            if msg.get("type") == "websocket.disconnect":
                break
    except Exception:
        pass
    finally:
        await unregister_user(current_user.id, websocket)
