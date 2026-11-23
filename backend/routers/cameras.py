"""Camera management and live streaming endpoints.

The live feed is served as an MJPEG multipart response so it can be embedded
directly in an ``<img>`` tag.  Because browser image tags cannot send an
``Authorization`` header, the stream and snapshot endpoints also accept a JWT
through the ``?token=`` query parameter.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response # type: ignore
from fastapi.responses import StreamingResponse # type: ignore
from sqlalchemy import func, select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.ai.discovery import preferred_camera_index, probe_webcams
from backend.ai.supervisor import supervisor
from backend.config import settings
from backend.database import get_db
from backend.deps import client_ip, get_current_user, get_stream_user, require_permissions
from backend.models import Camera, Event, Incident, Recording, User, Zone
from backend.schemas import CameraCreate, CameraUpdate, LiveDeviceSelect, MessageResponse
from backend.serializers import camera_payload
from backend.services import imaging, storage, zones
from backend.services.audit import record_audit
from backend.utils.logging import get_logger

log = get_logger("routers.cameras")

router = APIRouter(prefix="/api", tags=["Cameras"])

STREAM_BOUNDARY = "frame"


def _counts(db: Session) -> tuple[Dict[int, int], Dict[int, int]]:
    zone_counts = dict(
        db.execute(select(Zone.camera_id, func.count()).group_by(Zone.camera_id)).all()
    )
    threat_counts = dict(
        db.execute(
            select(Incident.camera_id, func.count())
            .where(Incident.status.in_(("open", "acknowledged")))
            .group_by(Incident.camera_id)
        ).all()
    )
    return zone_counts, threat_counts


def _serialize(db: Session, camera: Camera) -> Dict:
    zone_counts, threat_counts = _counts(db)
    runtime = supervisor.get(camera.id)
    return camera_payload(
        camera,
        runtime=runtime.get_meta() if runtime else None,
        zones_count=zone_counts.get(camera.id, 0),
        active_threats=threat_counts.get(camera.id, 0),
    )


def _unique_code(db: Session, requested: Optional[str]) -> str:
    base = (requested or "").strip().upper()
    if base:
        if db.scalar(select(Camera).where(Camera.code == base)):
            raise HTTPException(status_code=409, detail=f"Camera code {base} already exists")
        return base
    number = 1
    while db.scalar(select(Camera).where(Camera.code == f"CAM-{number:02d}")):
        number += 1
    return f"CAM-{number:02d}"


@router.get("/cameras")
def list_cameras(
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_live")),
):
    cameras = db.scalars(select(Camera).order_by(Camera.code)).all()
    return {
        "items": [_serialize(db, camera) for camera in cameras],
        "total": len(cameras),
        "supervisor_running": supervisor.running,
    }


@router.get("/cameras/meta")
def camera_meta(_: User = Depends(require_permissions("view_live"))):
    return {
        "source_types": [
            {"value": "demo", "label": "Synthetic demo feed"},
            {"value": "rtsp", "label": "RTSP / IP camera"},
            {"value": "file", "label": "Video file"},
            {"value": "webcam", "label": "Local webcam"},
        ],
        "resolutions": ["640x360", "960x540", "1280x720", "1920x1080"],
        "detector_modes": ["auto", "yolo", "demo"],
        "demo_mode": settings.demo_mode,
        "live_only": settings.live_only,
        "evidence_enabled": settings.evidence_enabled,
        "evidence_saved": settings.evidence_enabled and settings.recording_enabled,
        "live_camera_index": settings.live_camera_index,
        "webcam_backend": settings.webcam_backend,
        "continuous_recording_enabled": settings.continuous_recording_enabled,
        "continuous_segment_seconds": settings.continuous_segment_seconds,
        "save_motion_snapshots": settings.save_motion_snapshots,
        "max_fps": 30,
    }


@router.get("/cameras/discover")
def discover_cameras(_: User = Depends(require_permissions("view_live"))):
    """List physically attached cameras and whether they show a live image."""
    devices = probe_webcams()
    live = [device for device in devices if device.has_signal]
    visible = live if settings.live_only else devices
    return {
        "items": [device.as_dict() for device in visible],
        "live_only": settings.live_only,
        "active_index": settings.live_camera_index,
        "recommended_index": preferred_camera_index(devices),
        "live_devices": len(live),
        "total_devices": len(devices),
        "hidden_inactive": 0 if not settings.live_only else len(devices) - len(live),
        "backend": settings.webcam_backend,
    }


@router.post("/cameras", status_code=201)
def create_camera(
    payload: CameraCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_cameras")),
):
    camera = Camera(
        name=payload.name.strip(),
        code=_unique_code(db, payload.code),
        location=payload.location,
        rtsp_url=payload.rtsp_url,
        source_type=payload.source_type,
        status="starting",
        is_enabled=payload.is_enabled,
        fps=payload.fps,
        resolution=payload.resolution,
        notes=payload.notes,
    )
    db.add(camera)
    db.flush()
    record_audit(
        db,
        actor,
        "camera.create",
        target=camera.code,
        detail=f"{camera.name} · {camera.source_type}",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(camera)
    zones.zone_cache.invalidate()
    if camera.is_enabled:
        supervisor.sync()
    return _serialize(db, camera)


@router.get("/cameras/{camera_id}")
def get_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_live")),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    payload = _serialize(db, camera)
    payload["zones"] = [
        {
            "id": zone.id,
            "name": zone.name,
            "zone_type": zone.zone_type,
            "points": zone.points,
            "is_enabled": zone.is_enabled,
            "color": zone.color,
            "schedule": zones.describe_schedule(zone.schedule_start, zone.schedule_end, zone.days),
        }
        for zone in sorted(camera.zones, key=lambda item: item.id)
    ]
    recent = db.scalars(
        select(Incident)
        .where(Incident.camera_id == camera_id)
        .order_by(Incident.detected_at.desc())
        .limit(8)
    ).all()
    payload["recent_incidents"] = [
        {
            "id": item.id,
            "code": item.code,
            "title": item.title,
            "level": item.level,
            "risk_score": item.risk_score,
            "status": item.status,
            "detected_at": item.detected_at.isoformat(),
            "snapshot_url": storage.media_url(item.snapshot_path),
        }
        for item in recent
    ]
    runtime = supervisor.get(camera_id)
    payload["runtime"] = runtime.as_dict() if runtime else None
    return payload


@router.patch("/cameras/{camera_id}")
def update_camera(
    camera_id: int,
    payload: CameraUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_cameras")),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    data = payload.model_dump(exclude_unset=True)
    if "code" in data and data["code"]:
        code = str(data["code"]).strip().upper()
        duplicate = db.scalar(select(Camera).where(Camera.code == code, Camera.id != camera_id))
        if duplicate:
            raise HTTPException(status_code=409, detail=f"Camera code {code} already exists")
        data["code"] = code
    for field, value in data.items():
        setattr(camera, field, value)

    record_audit(
        db,
        actor,
        "camera.update",
        target=camera.code,
        detail=", ".join(sorted(data.keys())) or "No field changed",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(camera)

    if camera.is_enabled:
        supervisor.restart_camera(camera.id)
    else:
        supervisor.stop_camera(camera.id)
    return _serialize(db, camera)


@router.delete("/cameras/{camera_id}")
def delete_camera(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_cameras")),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    incidents = db.scalar(
        select(func.count()).select_from(Incident).where(Incident.camera_id == camera_id)
    )
    events = db.scalar(
        select(func.count()).select_from(Event).where(Event.camera_id == camera_id)
    )
    if incidents or events:
        raise HTTPException(
            status_code=409,
            detail=(
                "This camera has evidence history. Disable it instead so the audit "
                "trail and recordings remain intact."
            ),
        )

    supervisor.stop_camera(camera_id)
    recordings = db.scalars(select(Recording).where(Recording.camera_id == camera_id)).all()
    for recording in recordings:
        storage.delete_file(recording.path)
        db.delete(recording)
    code = camera.code
    db.delete(camera)
    record_audit(
        db,
        actor,
        "camera.delete",
        target=code,
        detail="Camera removed (no evidence history)",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    zones.zone_cache.invalidate()
    return MessageResponse(message=f"Camera {code} removed")


@router.post("/cameras/{camera_id}/restart")
def restart_camera(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_cameras")),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.is_enabled:
        raise HTTPException(status_code=400, detail="Enable the camera before restarting it")
    supervisor.restart_camera(camera_id)
    record_audit(
        db,
        actor,
        "camera.restart",
        target=camera.code,
        detail="Worker restarted by operator",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    return {"message": f"Camera {camera.code} restarting", "status": "starting"}


@router.post("/cameras/{camera_id}/live-device")
def select_live_device(
    camera_id: int,
    payload: LiveDeviceSelect,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_cameras")),
):
    """Point a camera at a different physical webcam index."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    camera.source_type = "webcam"
    camera.rtsp_url = str(payload.index)
    record_audit(
        db,
        actor,
        "camera.live_device",
        target=camera.code,
        detail=f"Live camera device set to index {payload.index}",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    supervisor.restart_camera(camera_id)
    return {"message": f"Camera {camera.code} now uses device {payload.index}", "index": payload.index}


@router.post("/cameras/{camera_id}/auto-device")
def auto_select_live_device(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_cameras")),
):
    """Scan physical cameras and switch to the first one with a live image."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    devices = probe_webcams()
    selectable = [device for device in devices if device.has_signal] if settings.live_only else devices
    index = preferred_camera_index(selectable)
    if index is None:
        raise HTTPException(
            status_code=409,
            detail=(
                "No camera with a live image was found. Check that the device is enabled "
                "in Windows Device Manager and that camera access is allowed for desktop apps."
            ),
        )
    camera.source_type = "webcam"
    camera.rtsp_url = str(index)
    record_audit(
        db,
        actor,
        "camera.live_device",
        target=camera.code,
        detail=f"Auto-detected live camera device {index}",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    supervisor.restart_camera(camera_id)
    return {
        "message": f"Camera {camera.code} now uses device {index}",
        "index": index,
        "devices": [device.as_dict() for device in selectable],
    }


@router.get("/cameras/{camera_id}/snapshot")
def camera_snapshot(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_stream_user),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    runtime = supervisor.get(camera_id)
    jpeg = runtime.get_jpeg() if runtime else None
    if jpeg is None:
        frame = imaging.placeholder_image(
            settings.frame_width, settings.frame_height, "WAITING FOR SIGNAL"
        )
        imaging.draw_header(
            frame,
            camera.name,
            camera.code,
            camera.location,
            "normal",
        )
        jpeg = imaging.encode_jpeg(frame, quality=78)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


async def _mjpeg_stream(camera_id: int, fps: int) -> AsyncGenerator[bytes, None]:
    interval = 1.0 / max(1, min(fps, 15))
    last: Optional[bytes] = None
    idle_since = time.monotonic()
    while True:
        runtime = supervisor.get(camera_id)
        jpeg = runtime.get_jpeg() if runtime else None
        if jpeg is None:
            if last is None or time.monotonic() - idle_since > 2.0:
                message = "NO CAMERA SIGNAL" if settings.live_only else "CONNECTING TO CAMERA"
                frame = imaging.placeholder_image(
                    settings.frame_width, settings.frame_height, message
                )
                jpeg = imaging.encode_jpeg(frame, quality=60)
                idle_since = time.monotonic()
            else:
                jpeg = last
        last = jpeg
        yield (
            f"--{STREAM_BOUNDARY}\r\n"
            "Content-Type: image/jpeg\r\n"
            f"Content-Length: {len(jpeg)}\r\n\r\n"
        ).encode("ascii") + jpeg + b"\r\n"
        await asyncio.sleep(interval)


@router.get("/cameras/{camera_id}/stream")
def camera_stream(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_stream_user),
):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.is_enabled:
        raise HTTPException(status_code=409, detail="Camera is disabled")
    return StreamingResponse(
        _mjpeg_stream(camera_id, camera.fps),
        media_type=f"multipart/x-mixed-replace; boundary={STREAM_BOUNDARY}",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Connection": "close",
        },
    )


@router.get("/cameras/{camera_id}/detections")
def latest_detections(
    camera_id: int,
    _: User = Depends(require_permissions("view_live")),
):
    runtime = supervisor.get(camera_id)
    if runtime is None:
        return {"camera_id": camera_id, "status": "offline", "detections": []}
    return {
        "camera_id": camera_id,
        "status": runtime.status,
        "fps": round(runtime.fps, 1),
        "detections": runtime.detections,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


__all__ = ["router"]
