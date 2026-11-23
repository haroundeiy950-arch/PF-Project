"""Realtime WebSocket endpoint.

Clients connect to ``/api/ws?token=<JWT>`` and immediately receive a snapshot of
the system.  Every incident, alert, camera-status and health change is then
pushed from the camera worker threads through the connection manager.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect # type: ignore
from sqlalchemy import func, select # type: ignore

from backend.ai.supervisor import supervisor
from backend.database import SessionLocal
from backend.deps import user_from_token
from backend.models import Incident
from backend.realtime import manager
from backend.utils.time_utils import iso, now

router = APIRouter(prefix="/api", tags=["Realtime"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str | None = Query(default=None)):
    if not token:
        await websocket.close(code=4401, reason="Authentication required")
        return

    db = SessionLocal()
    try:
        user = user_from_token(db, token)
        if user is None:
            await websocket.close(code=4401, reason="Invalid or expired session")
            return
        active = db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status.in_(("open", "acknowledged")))
        ) or 0
        user_payload = {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "role": user.role.name if user.role else None,
            "permissions": list(user.role.permissions or []) if user.role else [],
        }
    finally:
        db.close()

    await manager.connect(websocket)
    try:
        await manager.send_to(
            websocket,
            {
                "type": "connected",
                "data": {
                    "user": user_payload,
                    "active_incidents": int(active),
                    "server_time": iso(now()),
                    "health": supervisor.health_snapshot()
                    if supervisor.running
                    else {"status": "idle", "pipeline_running": False},
                    "clients": manager.client_count,
                    "topics": [
                        "incident.created",
                        "incident.updated",
                        "incident.acknowledged",
                        "incident.resolved",
                        "event.created",
                        "alert.updated",
                        "alert.playing",
                        "camera.status",
                        "health.updated",
                        "stats.refresh",
                    ],
                },
                "ts": iso(now()),
            },
        )
        while True:
            message = await websocket.receive_text()
            if message.strip().lower() in {"ping", "heartbeat"}:
                await manager.send_to(
                    websocket,
                    {
                        "type": "pong",
                        "data": {
                            "server_time": iso(now()),
                            "clients": manager.client_count,
                        },
                    },
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        await manager.disconnect(websocket)


__all__ = ["router"]
