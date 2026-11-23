"""Incident lifecycle: browse, acknowledge, resolve and false-alarm.

Every state change is audited and broadcast over the WebSocket channel so all
open operator screens update immediately (the alarm chain in Section 3).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request # type: ignore
from sqlalchemy import func, or_, select # type: ignore
from sqlalchemy.orm import Session, joinedload, selectinload # type: ignore

from backend.constants import LEVEL_LABELS, LEVEL_ORDER, THREAT_TYPE_LABELS
from backend.database import get_db
from backend.deps import client_ip, get_current_user, require_permissions
from backend.models import Camera, Event, Incident, User, Zone
from backend.realtime import manager
from backend.schemas import IncidentAction, IncidentStatusUpdate, MessageResponse
from backend.services import alarm
from backend.services.audit import record_audit
from backend.utils.time_utils import now, parse_datetime

router = APIRouter(prefix="/api", tags=["Incidents"])

ACTIVE_STATUSES = ("open", "acknowledged")


def _load(db: Session, incident_id: int) -> Incident:
    incident = db.scalar(
        select(Incident)
        .options(
            joinedload(Incident.camera),
            joinedload(Incident.zone),
            selectinload(Incident.alerts),
            selectinload(Incident.recordings),
            selectinload(Incident.acknowledgements),
        )
        .where(Incident.id == incident_id)
    )
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    return incident


def _serialize(incident: Incident, event_count: Optional[int] = None) -> dict:
    payload = alarm.incident_payload(
        incident,
        incident.camera,
        incident.zone if incident.zone_id else None,
        include_relations=True,
        event_count=event_count,
    )
    payload["level_label"] = LEVEL_LABELS.get(incident.level, incident.level)
    payload["type_label"] = THREAT_TYPE_LABELS.get(
        incident.incident_type, incident.incident_type
    )
    payload["minutes_open"] = round(
        max(0.0, (now() - incident.detected_at).total_seconds() / 60.0), 1
    )
    if incident.acknowledged_by_id:
        actor = getattr(incident, "acknowledged_by", None)
        payload["acknowledged_by"] = actor.full_name if actor else str(incident.acknowledged_by_id)
    else:
        payload["acknowledged_by"] = None
    return payload


@router.get("/incidents/active")
def active_incidents(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """The live threat panel.  Open alarms first, then highest risk."""
    rows = db.scalars(
        select(Incident)
        .options(
            joinedload(Incident.camera),
            joinedload(Incident.zone),
            selectinload(Incident.alerts),
            selectinload(Incident.recordings),
            selectinload(Incident.acknowledgements),
        )
        .where(Incident.status.in_(ACTIVE_STATUSES))
        .order_by(Incident.detected_at.desc())
        .limit(20)
    ).all()
    rows = sorted(
        rows,
        key=lambda item: (
            0 if item.status == "open" else 1,
            -LEVEL_ORDER.get(item.level, 0),
            -item.risk_score,
            -item.detected_at.timestamp(),
        ),
    )
    items = [_serialize(item) for item in rows]
    return {
        "items": items,
        "total": len(items),
        "primary": items[0] if items else None,
        "critical_count": sum(1 for item in rows if item.level == "critical"),
        "high_count": sum(1 for item in rows if item.level == "high"),
    }


@router.get("/incidents/summary")
def incident_summary(
    days: int = Query(default=1, ge=1, le=90),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    since = now() - timedelta(days=days)
    by_level = db.execute(
        select(Incident.level, func.count())
        .where(Incident.detected_at >= since)
        .group_by(Incident.level)
    ).all()
    by_status = db.execute(
        select(Incident.status, func.count())
        .where(Incident.detected_at >= since)
        .group_by(Incident.status)
    ).all()
    by_type = db.execute(
        select(Incident.incident_type, func.count())
        .where(Incident.detected_at >= since)
        .group_by(Incident.incident_type)
        .order_by(func.count().desc())
    ).all()
    by_camera = db.execute(
        select(Camera.name, Camera.code, func.count())
        .join(Incident, Incident.camera_id == Camera.id)
        .where(Incident.detected_at >= since)
        .group_by(Camera.id)
    ).all()
    total = sum(count for _, count in by_level)
    return {
        "window_days": days,
        "total": total,
        "by_level": [
            {"level": level, "label": LEVEL_LABELS.get(level, level), "count": count}
            for level, count in by_level
        ],
        "by_status": [{"status": status, "count": count} for status, count in by_status],
        "by_type": [
            {
                "incident_type": name,
                "label": THREAT_TYPE_LABELS.get(name, name),
                "count": count,
            }
            for name, count in by_type
        ],
        "by_camera": [
            {"camera_name": name, "camera_code": code, "count": count}
            for name, code, count in by_camera
        ],
    }


@router.get("/incidents")
def list_incidents(
    level: Optional[str] = None,
    status: Optional[str] = None,
    camera_id: Optional[int] = None,
    zone_id: Optional[int] = None,
    incident_type: Optional[str] = None,
    q: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Incident).options(
        joinedload(Incident.camera), joinedload(Incident.zone)
    )
    count_query = select(func.count()).select_from(Incident)
    filters = []

    if level:
        filters.append(Incident.level == level)
    if status:
        filters.append(Incident.status == status)
    if camera_id is not None:
        filters.append(Incident.camera_id == camera_id)
    if zone_id is not None:
        filters.append(Incident.zone_id == zone_id)
    if incident_type:
        filters.append(Incident.incident_type == incident_type)
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Incident.code.ilike(pattern),
                Incident.title.ilike(pattern),
                Incident.incident_type.ilike(pattern),
                Incident.track_id.ilike(pattern),
            )
        )
    start_dt = parse_datetime(start)
    end_dt = parse_datetime(end)
    if start_dt:
        filters.append(Incident.detected_at >= start_dt)
    if end_dt:
        filters.append(Incident.detected_at <= end_dt)

    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(Incident.detected_at.desc()).offset(offset).limit(limit)
    ).all()

    event_counts = dict(
        db.execute(
            select(Incident.id, func.count())
            .select_from(Incident)
            .outerjoin(Incident.events)
            .where(Incident.id.in_([row.id for row in rows] or [-1]))
            .group_by(Incident.id)
        ).all()
    ) if rows else {}

    items = []
    for incident in rows:
        payload = alarm.incident_payload(
            incident,
            incident.camera,
            incident.zone if incident.zone_id else None,
            include_relations=False,
            event_count=event_counts.get(incident.id, 0),
        )
        payload["level_label"] = LEVEL_LABELS.get(incident.level, incident.level)
        payload["type_label"] = THREAT_TYPE_LABELS.get(
            incident.incident_type, incident.incident_type
        )
        items.append(payload)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/incidents/{incident_id}")
def get_incident(
    incident_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    incident = _load(db, incident_id)
    count = db.scalar(
        select(func.count()).select_from(Incident).join(Incident.events).where(Incident.id == incident_id)
    ) or 0
    return _serialize(incident, event_count=count)


@router.get("/incidents/{incident_id}/events")
def incident_events(
    incident_id: int,
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    rows = db.scalars(
        select(Event)
        .where(Event.incident_id == incident_id)
        .order_by(Event.occurred_at)
        .limit(limit)
    ).all()
    return {"items": [alarm.event_payload(event) for event in rows], "total": len(rows)}


@router.post("/incidents/{incident_id}/acknowledge")
def acknowledge(
    incident_id: int,
    payload: IncidentAction,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("acknowledge_alarms")),
):
    incident = _load(db, incident_id)
    if incident.status in {"resolved", "false_alarm"}:
        raise HTTPException(status_code=409, detail="This incident is already closed")
    if incident.status == "acknowledged":
        return _serialize(incident)
    alarm.acknowledge_incident(db, incident, actor, payload.note)
    record_audit(
        db,
        actor,
        "incident.acknowledge",
        target=incident.code,
        detail=payload.note or "Alarm acknowledged",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(incident)
    result = _serialize(incident)
    manager.broadcast_threadsafe("incident.acknowledged", result)
    manager.broadcast_threadsafe("stats.refresh", {"reason": "acknowledged"})
    return result


@router.post("/incidents/{incident_id}/resolve")
def resolve(
    incident_id: int,
    payload: IncidentAction,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("acknowledge_alarms")),
):
    incident = _load(db, incident_id)
    if incident.status == "resolved":
        return _serialize(incident)
    alarm.resolve_incident(db, incident, actor, status="resolved", note=payload.note)
    record_audit(
        db,
        actor,
        "incident.resolve",
        target=incident.code,
        detail=payload.note or "Incident resolved",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(incident)
    result = _serialize(incident)
    manager.broadcast_threadsafe("incident.resolved", result)
    manager.broadcast_threadsafe("stats.refresh", {"reason": "resolved"})
    return result


@router.post("/incidents/{incident_id}/false-alarm")
def false_alarm(
    incident_id: int,
    payload: IncidentAction,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("acknowledge_alarms")),
):
    incident = _load(db, incident_id)
    alarm.resolve_incident(db, incident, actor, status="false_alarm", note=payload.note)
    record_audit(
        db,
        actor,
        "incident.false_alarm",
        target=incident.code,
        detail=payload.note or "Marked as false alarm",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(incident)
    result = _serialize(incident)
    manager.broadcast_threadsafe("incident.false_alarm", result)
    manager.broadcast_threadsafe("stats.refresh", {"reason": "false_alarm"})
    return result


@router.patch("/incidents/{incident_id}/status")
def update_status(
    incident_id: int,
    payload: IncidentStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("acknowledge_alarms")),
):
    incident = _load(db, incident_id)
    if payload.status == "acknowledged":
        if incident.status != "acknowledged":
            alarm.acknowledge_incident(db, incident, actor, payload.note)
    elif payload.status in {"resolved", "false_alarm"}:
        alarm.resolve_incident(db, incident, actor, payload.status, payload.note)
    elif payload.status == "open":
        incident.status = "open"
        incident.resolved_at = None
    else:  # pragma: no cover - schema validates the list
        raise HTTPException(status_code=400, detail="Unsupported status")

    record_audit(
        db,
        actor,
        f"incident.{payload.status}",
        target=incident.code,
        detail=payload.note or "Status changed from the incident screen",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(incident)
    result = _serialize(incident)
    manager.broadcast_threadsafe("incident.updated", result)
    manager.broadcast_threadsafe("stats.refresh", {"reason": "status"})
    return result


@router.delete("/incidents/{incident_id}")
def delete_incident(
    incident_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_settings")),
):
    """Administrators can purge a false incident and its evidence."""
    incident = _load(db, incident_id)
    code = incident.code
    for recording in list(incident.recordings):
        from backend.services import storage

        storage.delete_file(recording.path)
    for event in list(incident.events):
        event.incident_id = None
    db.delete(incident)
    record_audit(
        db,
        actor,
        "incident.delete",
        target=code,
        detail="Incident and evidence deleted by administrator",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    manager.broadcast_threadsafe("stats.refresh", {"reason": "deleted"})
    return MessageResponse(message=f"Incident {code} deleted")


__all__ = ["router"]
