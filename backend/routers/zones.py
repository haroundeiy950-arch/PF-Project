"""Detection zone CRUD.

Zones are polygons in normalized 0..1 image coordinates, so the same polygon
works at every stream resolution.  Every write invalidates the pipeline's zone
cache so the change is picked up by running cameras within one frame.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request # type: ignore
from sqlalchemy import select, update # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.database import get_db
from backend.deps import client_ip, get_current_user, require_permissions
from backend.models import Camera, Event, Incident, User, Zone
from backend.schemas import MessageResponse, ZoneCreate, ZoneUpdate
from backend.services import zones
from backend.services.audit import record_audit

router = APIRouter(prefix="/api", tags=["Zones"])


def zone_payload(zone: Zone) -> dict:
    return {
        "id": zone.id,
        "camera_id": zone.camera_id,
        "name": zone.name,
        "zone_type": zone.zone_type,
        "points": zone.points or [],
        "schedule_start": zone.schedule_start,
        "schedule_end": zone.schedule_end,
        "days": zone.days or [],
        "schedule_label": zones.describe_schedule(
            zone.schedule_start, zone.schedule_end, zone.days or []
        ),
        "min_dwell_seconds": zone.min_dwell_seconds,
        "min_frames": zone.min_frames,
        "cooldown_seconds": zone.cooldown_seconds,
        "is_enabled": zone.is_enabled,
        "color": zone.color,
        "camera_name": zone.camera.name if zone.camera else None,
    }


@router.get("/zones/meta")
def zone_meta(_: User = Depends(get_current_user)):
    return {
        "zone_types": [
            {
                "value": "restricted",
                "label": "Restricted area",
                "description": "Any verified intrusion is a high-risk alarm.",
                "color": "#ef4444",
            },
            {
                "value": "limited",
                "label": "Limited access",
                "description": "Staff-only area: alerts on unusual behaviour.",
                "color": "#f59e0b",
            },
            {
                "value": "public",
                "label": "Public area",
                "description": "Open area: only abnormal activity raises risk.",
                "color": "#22d3ee",
            },
        ],
        "weekdays": [
            {"value": index, "label": label}
            for index, label in enumerate(zones.WEEKDAY_LABELS)
        ],
        "defaults": {
            "min_dwell_seconds": 2.0,
            "min_frames": 6,
            "cooldown_seconds": 90,
        },
    }


@router.get("/zones")
def list_zones(
    camera_id: Optional[int] = None,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Zone).order_by(Zone.camera_id, Zone.id)
    if camera_id is not None:
        query = query.where(Zone.camera_id == camera_id)
    rows = db.scalars(query).all()
    return {"items": [zone_payload(zone) for zone in rows], "total": len(rows)}


@router.get("/zones/{zone_id}")
def get_zone(
    zone_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone_payload(zone)


@router.post("/zones", status_code=201)
def create_zone(
    payload: ZoneCreate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_zones")),
):
    camera = db.get(Camera, payload.camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="Camera not found")

    zone = Zone(
        camera_id=camera.id,
        name=payload.name.strip(),
        zone_type=payload.zone_type,
        points=payload.points,
        schedule_start=payload.schedule_start,
        schedule_end=payload.schedule_end,
        days=payload.days,
        min_dwell_seconds=payload.min_dwell_seconds,
        min_frames=payload.min_frames,
        cooldown_seconds=payload.cooldown_seconds,
        is_enabled=payload.is_enabled,
        color=payload.color,
    )
    db.add(zone)
    record_audit(
        db,
        actor,
        "zone.create",
        target=f"{camera.code}/{payload.name}",
        detail=f"{payload.zone_type} polygon with {len(payload.points)} points",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(zone)
    zones.zone_cache.invalidate()
    return zone_payload(zone)


@router.patch("/zones/{zone_id}")
def update_zone(
    zone_id: int,
    payload: ZoneUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_zones")),
):
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(zone, field, value)
    record_audit(
        db,
        actor,
        "zone.update",
        target=f"{zone.camera.code if zone.camera else zone.camera_id}/{zone.name}",
        detail=", ".join(sorted(data.keys())) or "No field changed",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(zone)
    zones.zone_cache.invalidate()
    return zone_payload(zone)


@router.delete("/zones/{zone_id}")
def delete_zone(
    zone_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_zones")),
):
    zone = db.get(Zone, zone_id)
    if zone is None:
        raise HTTPException(status_code=404, detail="Zone not found")
    camera_code = zone.camera.code if zone.camera else str(zone.camera_id)
    name = zone.name

    # Historical evidence must survive zone deletion: detach references first.
    db.execute(update(Event).where(Event.zone_id == zone_id).values(zone_id=None))
    db.execute(update(Incident).where(Incident.zone_id == zone_id).values(zone_id=None))
    db.delete(zone)
    record_audit(
        db,
        actor,
        "zone.delete",
        target=f"{camera_code}/{name}",
        detail="Zone removed; historical events kept without a zone link",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    zones.zone_cache.invalidate()
    return MessageResponse(message=f"Zone {name} removed")


__all__ = ["router", "zone_payload"]
