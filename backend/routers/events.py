"""Detection event browser.

Events are the raw, high-volume layer of the system (every verified detection
and every logged normal motion).  Incidents are the curated alarms built on top
of them; the Events screen uses these endpoints for searching and evidence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query # type: ignore
from sqlalchemy import func, or_, select # type: ignore
from sqlalchemy.orm import Session, joinedload # type: ignore

from backend.database import get_db
from backend.deps import get_current_user
from backend.models import Camera, Event, Incident, User
from backend.services.alarm import event_payload
from backend.utils.time_utils import now, parse_datetime

router = APIRouter(prefix="/api", tags=["Events"])


@router.get("/events")
def list_events(
    camera_id: Optional[int] = None,
    zone_id: Optional[int] = None,
    incident_id: Optional[int] = None,
    event_type: Optional[str] = None,
    target_type: Optional[str] = None,
    is_threat: Optional[bool] = None,
    q: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Event).options(
        joinedload(Event.camera), joinedload(Event.zone)
    )
    count_query = select(func.count()).select_from(Event)

    filters = []
    if camera_id is not None:
        filters.append(Event.camera_id == camera_id)
    if zone_id is not None:
        filters.append(Event.zone_id == zone_id)
    if incident_id is not None:
        filters.append(Event.incident_id == incident_id)
    if event_type:
        filters.append(Event.event_type == event_type)
    if target_type:
        filters.append(Event.target_type == target_type)
    if is_threat is not None:
        filters.append(Event.is_threat.is_(is_threat))
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Event.event_type.ilike(pattern),
                Event.target_type.ilike(pattern),
                Event.track_id.ilike(pattern),
            )
        )
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end)
    if start_dt:
        filters.append(Event.occurred_at >= start_dt)
    if end_dt:
        filters.append(Event.occurred_at <= end_dt)

    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(Event.occurred_at.desc()).offset(offset).limit(limit)
    ).all()

    threats = db.scalar(
        select(func.count()).select_from(Event).where(*filters, Event.is_threat.is_(True))
    ) if filters else db.scalar(
        select(func.count()).select_from(Event).where(Event.is_threat.is_(True))
    )

    return {
        "items": [event_payload(event) for event in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "threats": threats or 0,
    }


@router.get("/events/stats")
def event_stats(
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    since = now() - timedelta(hours=hours)
    by_type = db.execute(
        select(Event.event_type, func.count())
        .where(Event.occurred_at >= since)
        .group_by(Event.event_type)
        .order_by(func.count().desc())
    ).all()
    by_target = db.execute(
        select(Event.target_type, func.count())
        .where(Event.occurred_at >= since)
        .group_by(Event.target_type)
    ).all()
    by_camera = db.execute(
        select(Camera.name, Event.camera_id, func.count())
        .join(Event, Event.camera_id == Camera.id)
        .where(Event.occurred_at >= since)
        .group_by(Camera.id)
    ).all()
    return {
        "window_hours": hours,
        "by_type": [{"event_type": name, "count": count} for name, count in by_type],
        "by_target": [{"target_type": name, "count": count} for name, count in by_target],
        "by_camera": [
            {"camera_id": camera_id, "camera_name": name, "count": count}
            for name, camera_id, count in by_camera
        ],
    }


@router.get("/events/{event_id}")
def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    payload = event_payload(event, event.camera)
    if event.incident_id:
        incident = db.get(Incident, event.incident_id)
        if incident is not None:
            payload["incident_code"] = incident.code
            payload["incident_level"] = incident.level
    return payload


__all__ = ["router"]
