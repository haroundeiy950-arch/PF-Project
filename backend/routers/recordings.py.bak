
"""Recordings, snapshots and evidence management (Section 8)."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request  # type: ignore
from sqlalchemy import func, select  # type: ignore
from sqlalchemy.orm import Session, joinedload  # type: ignore

from backend.ai.supervisor import supervisor
from backend.database import get_db
from backend.deps import (
    client_ip,
    get_current_user,
    require_permissions,
)
from backend.models import Camera, Incident, Recording, User
from backend.schemas import MessageResponse
from backend.services import alarm, evidence_audit, imaging, storage
from backend.services.audit import record_audit
from backend.utils.time_utils import now

router = APIRouter(prefix="/api/recordings", tags=["Recordings"])


def _payload(recording: Recording) -> dict:
    payload = alarm.recording_payload(recording)

    payload["camera_name"] = (
        recording.camera.name if recording.camera else None
    )
    payload["camera_code"] = (
        recording.camera.code if recording.camera else None
    )

    if recording.incident:
        payload["incident_code"] = recording.incident.code
        payload["incident_level"] = recording.incident.level

    return payload


@router.get("")
def list_recordings(
    camera_id: Optional[int] = None,
    incident_id: Optional[int] = None,
    kind: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_recordings")),
):
    query = select(Recording).options(
        joinedload(Recording.camera),
        joinedload(Recording.incident),
    )

    count_query = select(func.count()).select_from(Recording)

    filters = []

    if camera_id is not None:
        filters.append(Recording.camera_id == camera_id)

    if incident_id is not None:
        filters.append(Recording.incident_id == incident_id)

    if kind:
        filters.append(Recording.kind == kind)

    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0

    rows = db.scalars(
        query.order_by(Recording.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "items": [_payload(recording) for recording in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/stats")
def recording_stats(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_recordings")),
):
    by_kind = db.execute(
        select(
            Recording.kind,
            func.count(),
            func.coalesce(func.sum(Recording.size_bytes), 0),
        ).group_by(Recording.kind)
    ).all()

    total_size = (
        db.scalar(
            select(
                func.coalesce(func.sum(Recording.size_bytes), 0)
            )
        )
        or 0
    )

    total_count = (
        db.scalar(select(func.count()).select_from(Recording))
        or 0
    )

    disk = storage.disk_status()

    return {
        "total_count": int(total_count),
        "total_size_bytes": int(total_size),
        "total_size_gb": round(int(total_size) / (1024**3), 3),
        "by_kind": [
            {
                "kind": kind,
                "count": int(count),
                "size_bytes": int(size),
            }
            for kind, count, size in by_kind
        ],
        "disk": disk,
    }


@router.post("/audit")
def audit_recordings(
    request: Request,
    repair: bool = False,
    db: Session = Depends(get_db),
    actor: User = Depends(get_current_user),
):
    """
    Verify evidence files.

    Read-only audit requires view_recordings.
    Repair audit requires delete_recordings.
    """

    required_permission = (
        "delete_recordings" if repair else "view_recordings"
    )

    permissions = (
        actor.role.permissions if actor.role else []
    )

    from backend.security import has_permission

    if not has_permission(permissions, required_permission):
        raise HTTPException(
            status_code=403,
            detail=f"Missing permission: {required_permission}",
        )

    result = evidence_audit.audit_evidence(
        db,
        repair=repair,
    )

    record_audit(
        db,
        actor,
        "recording.audit",
        target="evidence_archive",
        detail=(
            f"Evidence audit "
            f"{'with repair' if repair else 'read-only'}"
        ),
        ip_address=client_ip(request),
        commit=False,
    )

    db.commit()

    return result


@router.post("/snapshot/{camera_id}", status_code=201)
def capture_snapshot(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("view_live")),
):
    """Save the current frame of a live camera as evidence."""

    camera = db.get(Camera, camera_id)

    if camera is None:
        raise HTTPException(
            status_code=404,
            detail="Camera not found",
        )

    runtime = supervisor.get(camera_id)
    jpeg = runtime.get_jpeg() if runtime else None

    if jpeg is None:
        raise HTTPException(
            status_code=409,
            detail="Camera has no frame available yet",
        )

    import cv2  # type: ignore
    import numpy as np

    frame = cv2.imdecode(
        np.frombuffer(jpeg, dtype=np.uint8),
        cv2.IMREAD_COLOR,
    )

    if frame is None:
        raise HTTPException(
            status_code=500,
            detail="Could not decode camera frame",
        )

    code = (
        f"MANUAL-{camera.code}-"
        f"{now().strftime('%Y%m%d%H%M%S')}"
    )

    path = imaging.save_snapshot(frame, code)

    recording = Recording(
        camera_id=camera.id,
        kind="snapshot",
        path=path,
        started_at=now(),
        ended_at=now(),
        duration_seconds=0.0,
        size_bytes=storage.file_size(path),
    )

    db.add(recording)

    record_audit(
        db,
        actor,
        "recording.snapshot",
        target=code,
        detail="Manual snapshot captured",
        ip_address=client_ip(request),
        commit=False,
    )

    db.commit()
    db.refresh(recording)

    return _payload(recording)


@router.get("/{recording_id}")
def get_recording(
    recording_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_recordings")),
):
    recording = db.get(Recording, recording_id)

    if recording is None:
        raise HTTPException(
            status_code=404,
            detail="Recording not found",
        )

    payload = _payload(recording)
    payload["exists"] = storage.absolute_path(
        recording.path
    ).is_file()

    return payload


@router.delete("/{recording_id}")
def delete_recording(
    recording_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("delete_recordings")),
):
    recording = db.get(Recording, recording_id)

    if recording is None:
        raise HTTPException(
            status_code=404,
            detail="Recording not found",
        )

    incident = recording.incident

    if incident:
        if incident.clip_path == recording.path:
            incident.clip_path = ""

        if incident.snapshot_path == recording.path:
            incident.snapshot_path = ""

    storage.delete_file(recording.path)
    db.delete(recording)

    record_audit(
        db,
        actor,
        "recording.delete",
        target=recording.path,
        detail=f"Evidence removed ({recording.kind})",
        ip_address=client_ip(request),
        commit=False,
    )

    db.commit()

    return MessageResponse(message="Recording deleted")


@router.get("/incident/{incident_id}")
def incident_recordings(
    incident_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_recordings")),
):
    incident = db.get(Incident, incident_id)

    if incident is None:
        raise HTTPException(
            status_code=404,
            detail="Incident not found",
        )

    return {
        "incident_id": incident_id,
        "code": incident.code,
        "snapshot_url": storage.media_url(
            incident.snapshot_path
        ),
        "clip_url": storage.media_url(
            incident.clip_path
        ),
        "items": [
            _payload(recording)
            for recording in incident.recordings
        ],
    }


__all__ = ["router"]
