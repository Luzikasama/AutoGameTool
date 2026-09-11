"""WebSocket 连接管理：向前端广播日志与运行状态。"""
import json
from typing import Any


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set = set()

    async def connect(self, ws) -> None:
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws) -> None:
        self.connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if not self.connections:
            return
        text = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
