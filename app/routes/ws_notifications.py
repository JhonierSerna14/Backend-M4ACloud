from fastapi import APIRouter, WebSocket, Query, HTTPException
from loguru import logger
from app.core.database import SessionLocal
from app.core.auth import get_current_user
from app.models.nota import Nota
from app.models.materia import Materia
from app.core import ws as ws_hub

router = APIRouter(tags=["ws"])


@router.websocket("/notas/{nota_id}/progress")
async def nota_progress_ws(websocket: WebSocket, nota_id: int, token: str = Query(...)):
    """WebSocket que emite actualizaciones de progreso para una nota.
    Cliente debe enviar el token JWT como query param: ?token=xxxx
    """
    await websocket.accept()

    # Log intento de conexión (token masked)
    try:
        masked = token[:8] + '...' if token else '<no-token>'
    except Exception:
        masked = '<token-error>'
    logger.info(f"WS connect attempt: nota={nota_id} token={masked} client_connected={websocket.client}")

    current_state = None
    db = SessionLocal()

    try:
        # Validar usuario
        current_user = get_current_user(db, token)
        logger.info(f"WS auth success: nota={nota_id} user_id={current_user.id}")

        # Verificar que la nota pertenezca al usuario
        nota = db.query(Nota).join(Materia).filter(
            Nota.id == nota_id,
            Materia.usuario_id == current_user.id
        ).first()

        if not nota:
            await websocket.close(code=1008)
            return

        current_state = {
            "id": nota.id,
            "status": nota.status,
            "progress": nota.progreso,
            "progreso": nota.progreso,
            "message": nota.status_message,
            "updated_at": nota.fecha_actualizacion,
        }
    except HTTPException as ex:
        logger.warning(f"WS auth failed for nota={nota_id}: {ex.detail}")
        try:
            await websocket.close(code=1008)
        except Exception:
            pass
        return
    finally:
        db.close()

    # Registrar conexión
    await ws_hub.register(nota_id, websocket)

    # Enviar estado actual inmediatamente al conectar
    try:
        if current_state is not None:
            await websocket.send_json(current_state)
    except Exception:
        pass

    try:
        # Mantener la conexión viva; usar receive() para aceptar cualquier tipo de frame
        # (text/binary/ping/pong) y no bloquear el envío desde otras corutinas.
        while True:
            msg = await websocket.receive()
            mtype = msg.get("type")
            # Si el cliente cerró la conexión, salimos
            if mtype == "websocket.disconnect":
                break
            # Ignorar payloads de texto/ping/pong; son usados solo como keepalive
    except Exception:
        # Cualquier error al recibir (p. ej. cierre) termina la conexión limpiamente
        pass
    finally:
        await ws_hub.unregister(nota_id, websocket)
