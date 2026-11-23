"""System status, health and small operational actions."""

from __future__ import annotations

import platform
import sys
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request # type: ignore
from sqlalchemy import func, select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.ai.face import get_face_engine
from backend.ai.supervisor import supervisor
from backend.config import settings
from backend.constants import LEVEL_LABELS, ROLE_DEFINITIONS
from backend.database import get_db
from backend.deps import client_ip, get_current_user, require_permissions
from backend.models import Camera, Event, Incident, Recording, User
from backend.schemas import MessageResponse
from backend.services import storage
from backend.services.audit import record_audit
from backend.utils.time_utils import iso, now

router = APIRouter(prefix="/api/system", tags=["System"])


@router.get("/ping")
def ping():
    """Unauthenticated liveness probe for monitoring tools."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "time": iso(now()),
    }


@router.get("/info")
def system_info(_: User = Depends(get_current_user)):
    disk = storage.disk_status()
    return {
        "app_name": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "pipeline_enabled": settings.pipeline_enabled,
        "supervisor_running": supervisor.running,
        "demo_mode": settings.demo_mode,
        "live_only": settings.live_only,
        "evidence_enabled": settings.evidence_enabled,
        "evidence_saved": settings.evidence_enabled and settings.recording_enabled,
        "live_camera_index": settings.live_camera_index,
        "detector_mode": settings.detector_mode,
        "face_recognition_enabled": settings.face_recognition_enabled,
        "face_engine": get_face_engine().status,
        "recording_enabled": settings.recording_enabled,
        "continuous_recording_enabled": settings.continuous_recording_enabled,
        "continuous_segment_seconds": settings.continuous_segment_seconds,
        "save_motion_snapshots": settings.save_motion_snapshots,
        "webcam_backend": settings.webcam_backend,
        "retention_days": settings.retention_days,
        "voice_enabled": settings.voice_enabled,
        "siren_enabled": settings.siren_enabled,
        "storage": disk,
        "storage_estimate": {
            "per_camera_gb_per_day_2mbps": storage.storage_estimate_per_camera_gb_per_day(2.0),
            "per_camera_gb_per_day_4mbps": storage.storage_estimate_per_camera_gb_per_day(4.0),
        },
        "timezone": "server-local",
        "server_time": iso(now()),
    }


@router.get("/health")
def system_health(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    snapshot = supervisor.health_snapshot()
    snapshot["pipeline_running"] = supervisor.running
    counts = {
        "cameras": db.scalar(select(func.count()).select_from(Camera)) or 0,
        "events": db.scalar(select(func.count()).select_from(Event)) or 0,
        "incidents": db.scalar(select(func.count()).select_from(Incident)) or 0,
        "recordings": db.scalar(select(func.count()).select_from(Recording)) or 0,
        "open_incidents": db.scalar(
            select(func.count())
            .select_from(Incident)
            .where(Incident.status.in_(("open", "acknowledged")))
        )
        or 0,
    }
    db_path = settings.database_url.replace("sqlite:///", "")
    db_size = 0
    try:
        from pathlib import Path

        db_size = Path(db_path).stat().st_size
    except OSError:
        pass
    return {
        **snapshot,
        "counts": counts,
        "database": {
            "engine": "sqlite" if settings.database_url.startswith("sqlite") else "postgresql",
            "size_bytes": db_size,
            "size_mb": round(db_size / (1024**2), 2),
        },
        "face_engine": get_face_engine().status,
        "version": settings.app_version,
    }


@router.get("/levels")
def level_metadata(_: User = Depends(get_current_user)):
    return {
        "levels": [
            {"value": key, "label": label} for key, label in LEVEL_LABELS.items()
        ],
        "roles": [
            {"name": key, **value} for key, value in ROLE_DEFINITIONS.items()
        ],
    }


@router.post("/pipeline/restart")
def restart_pipeline(
    request: Request,
    actor: User = Depends(require_permissions("manage_settings")),
    db: Session = Depends(get_db),
):
    supervisor.stop()
    supervisor.start()
    record_audit(
        db,
        actor,
        "system.pipeline_restart",
        target="camera-supervisor",
        detail="All camera workers restarted",
        ip_address=client_ip(request),
        commit=True,
    )
    return MessageResponse(message="AI pipeline restarted")


@router.post("/retention")
def retention(
    request: Request,
    actor: User = Depends(require_permissions("manage_settings")),
    db: Session = Depends(get_db),
):
    result = storage.purge_expired_recordings(db)
    record_audit(
        db,
        actor,
        "storage.retention",
        target="recordings",
        detail=str(result),
        ip_address=client_ip(request),
        commit=True,
    )
    return result


__all__ = ["router"]
