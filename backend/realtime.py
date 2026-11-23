"""WebSocket connection manager for live events.

The camera pipeline runs in worker threads, so ``broadcast_threadsafe`` bridges
threads and the asyncio event loop safely.  Clients receive JSON envelopes:

    {"type": "incident.created", "data": {...}, "ts": "2026-11-16T14:22:31"}
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Set

from fastapi import WebSocket # type: ignore

from backend.utils.logging import get_logger
from backend.utils.time_utils import iso, now

log = get_logger("realtime")


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        log.info("WebSocket connected (%d clients)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        log.info("WebSocket disconnected (%d clients)", len(self._connections))

    @property
    def client_count(self) -> int:
        return len(self._connections)

    async def send_to(self, websocket: WebSocket, payload: Dict[str, Any]) -> None:
        try:
            await websocket.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:  # pragma: no cover - client vanished
            await self.disconnect(websocket)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        envelope = {
            "type": payload.get("type", "message"),
            "data": payload.get("data", {}),
            "ts": payload.get("ts") or iso(now()),
        }
        text = json.dumps(envelope, ensure_ascii=False, default=str)
        async with self._lock:
            connections: List[WebSocket] = list(self._connections)
        stale: List[WebSocket] = []
        for connection in connections:
            try:
                await connection.send_text(text)
            except Exception:
                stale.append(connection)
        if stale:
            async with self._lock:
                for connection in stale:
                    self._connections.discard(connection)

    def broadcast_threadsafe(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish from a worker thread without blocking the camera loop."""
        payload = {"type": event_type, "data": data}
        if self._loop is None or self._loop.is_closed():
            return
        try:
            asyncio.run_coroutine_threadsafe(self.broadcast(payload), self._loop)
        except RuntimeError:  # pragma: no cover - shutdown race
            pass

    async def ping_all(self) -> None:
        await self.broadcast({"type": "heartbeat", "data": {"clients": self.client_count}})


manager = ConnectionManager()

__all__ = ["ConnectionManager", "manager"]
