"""API routers.

Every module exposes a single ``router`` object which ``backend.main`` mounts
under ``/api``.  The order here is the order shown in the OpenAPI docs.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter # type: ignore

from backend.routers import (
    alerts,
    auth,
    cameras,
    dashboard,
    events,
    incidents,
    persons,
    recordings,
    reports,
    settings,
    system,
    users,
    ws,
    zones,
)

ROUTERS: List[APIRouter] = [
    auth.router,
    users.router,
    cameras.router,
    zones.router,
    events.router,
    incidents.router,
    alerts.router,
    dashboard.router,
    persons.router,
    recordings.router,
    reports.router,
    settings.router,
    system.router,
    ws.router,
]


def register_routers(app) -> None:
    """Attach every router to a FastAPI application."""
    for router in ROUTERS:
        app.include_router(router)


__all__ = ["ROUTERS", "register_routers"]
