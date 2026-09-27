"""WebSocket 连接管理：向前端广播日志与运行状态。"""
import asyncio
import json
from typing import Any, Callable


class ConnectionManager:
    def __init__(self) -> None:
        self.connections: set = set()
        # 广播钩子：引擎用它把「推给前端的日志」同时写进运行日志文件。
        # 必须在「没有连接就直接返回」之前调用——页面被关掉之后，正是最需要留痕的时候。
        self.on_broadcast: Callable[[dict], None] | None = None

    async def connect(self, ws) -> None:
        await ws.accept()
        self.connections.add(ws)

    def disconnect(self, ws) -> None:
        self.connections.discard(ws)

    async def broadcast(self, message: dict[str, Any]) -> None:
        cb = self.on_broadcast
        if cb is not None:
            try:
                cb(message)
            except Exception:
                pass
        if not self.connections:
            return
        text = json.dumps(message, ensure_ascii=False)

        async def _send(ws) -> bool:
            try:
                await ws.send_text(text)
                return True
            except Exception:
                return False

        # 并发发送：某个客户端接收慢不会拖慢整体日志推送
        results = await asyncio.gather(*(_send(ws) for ws in list(self.connections)))
        for ws, ok in zip(list(self.connections), results):
            if not ok:
                self.disconnect(ws)


manager = ConnectionManager()
