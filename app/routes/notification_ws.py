from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Dict, List, Optional
import asyncio
import logging
import jwt

from app.core.security import SECRET_KEY, ALGORITHM

logger = logging.getLogger(__name__)

router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, List[WebSocket]] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop

    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections.setdefault(user_id, []).append(websocket)
        logger.info(
            f"WS connected for user {user_id} ({len(self.active_connections[user_id])} sockets)"
        )

    def disconnect(self, websocket: WebSocket, user_id: int):
        conns = self.active_connections.get(user_id)
        if conns and websocket in conns:
            conns.remove(websocket)
            if not conns:
                del self.active_connections[user_id]

    async def send_notification(self, user_id: int, message: dict):
        conns = self.active_connections.get(user_id, [])
        disconnected = []
        for connection in conns:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)
        for conn in disconnected:
            self.disconnect(conn, user_id)

    def notify_user_sync(self, user_id: int, message: dict):
        if self.loop is None:
            logger.warning(
                "No event loop registered on ConnectionManager; skipping WS push"
            )
            return
        if user_id not in self.active_connections:
            return
        asyncio.run_coroutine_threadsafe(
            self.send_notification(user_id, message), self.loop
        )


manager = ConnectionManager()


def _get_user_id_from_token(token: str) -> Optional[int]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("user_id")
        return int(user_id) if user_id is not None else None
    except jwt.ExpiredSignatureError:
        logger.info("WS token expired")
        return None
    except jwt.InvalidTokenError as e:
        logger.warning(f"WS token invalid: {e}")
        return None


@router.websocket("/ws/notifications/")
async def websocket_endpoint(websocket: WebSocket, token: Optional[str] = Query(None)):
    if not token:
        await websocket.close(code=4401)
        return

    user_id = _get_user_id_from_token(token)
    if user_id is None:
        await websocket.close(code=4401)
        return

    await manager.connect(websocket, user_id)

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
            except Exception:
                break
    finally:
        manager.disconnect(websocket, user_id)
