"""Sentinel AI application entry point.

Run with::

    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request # type: ignore
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from fastapi.responses import FileResponse, JSONResponse # type: ignore
from fastapi.staticfiles import StaticFiles # type: ignore

from backend.ai.supervisor import supervisor
from backend.config import settings
from backend.database import Base, SessionLocal, engine, init_db
from backend.realtime import manager
from backend.routers import register_routers
from backend.seed import DEMO_USERS, seed_if_needed
from backend.utils.logging import get_logger
from backend.utils.time_utils import iso, now

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_directories()
    if settings.reset_database:
        log.warning("RESET_DATABASE is enabled: dropping all tables")
        Base.metadata.drop_all(bind=engine)
    init_db()

    db = SessionLocal()
    try:
        result = seed_if_needed(db)
        if result.get("seeded"):
            log.info(
                "Demo data ready · %s incidents · %s events · %s recordings",
                result.get("incidents"),
                result.get("events"),
                result.get("recordings"),
            )
        else:
            log.info("Database already initialised (%s)", result.get("reason", "ok"))
        credentials = ", ".join(f"{name}/{password}" for name, password, *_ in DEMO_USERS)
    finally:
        db.close()

    manager.bind_loop(asyncio.get_running_loop())
    app.state.started_at = now()
    if settings.pipeline_enabled:
        supervisor.start()

    log.info("=" * 72)
    log.info("%s v%s ready", settings.app_name, settings.app_version)
    log.info("API:      http://%s:%s/docs", settings.host, settings.port)
    log.info("Frontend: http://%s:%s/", settings.host, settings.port)
    log.info("Console logins: %s", credentials)
    log.info("=" * 72)

    try:
        yield
    finally:
        supervisor.stop()
        log.info("Sentinel AI shut down")


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.app_name} API",
        version=settings.app_version,
        description=(
            "AI Smart Security Camera System — live monitoring, verified threat "
            "detection, transparent risk scoring, bilingual alarms, evidence and reports."
        ),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_routers(app)

    # Evidence files are intentionally reachable by <img>/<video> tags.  Only
    # the media folders are mounted — never the database or logs directory.
    for name, directory in (
        ("snapshots", settings.snapshots_dir),
        ("clips", settings.clips_dir),
        ("faces", settings.faces_dir),
        ("exports", settings.exports_dir),
    ):
        app.mount(
            f"/media/{name}",
            StaticFiles(directory=str(directory), check_dir=False),
            name=f"media-{name}",
        )

    @app.get("/api", include_in_schema=False)
    def api_root():
        return {
            "name": f"{settings.app_name} API",
            "version": settings.app_version,
            "docs": "/docs",
            "status": "running",
            "time": iso(now()),
        }

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        icon = settings.frontend_dist / "favicon.svg"
        if icon.is_file():
            return FileResponse(icon)
        raise HTTPException(status_code=404)

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc: HTTPException):
        if request.url.path.startswith(("/api", "/media", "/docs", "/redoc", "/openapi.json")):
            return JSONResponse({"detail": exc.detail or "Not found"}, status_code=404)
        index = settings.frontend_dist / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            {
                "detail": "Not found",
                "hint": "Build the frontend with `npm run build` inside frontend/ to serve the UI.",
            },
            status_code=404,
        )

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        """Serve the compiled React app with client-side routing fallback."""
        if full_path.startswith(("api/", "media/", "docs", "redoc", "openapi.json")):
            raise HTTPException(status_code=404, detail="Not found")
        dist = settings.frontend_dist
        index = dist / "index.html"
        if not index.is_file():
            if full_path in {"", "index.html"}:
                return JSONResponse(
                    {
                        "name": f"{settings.app_name} API",
                        "version": settings.app_version,
                        "docs": "/docs",
                        "frontend": "not built yet — run `cd frontend; npm install; npm run build`",
                        "time": iso(now()),
                    }
                )
            raise HTTPException(status_code=404)

        candidate = (dist / full_path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            raise HTTPException(status_code=404) from None
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)

    return app


app = create_app()

__all__ = ["app", "create_app"]
