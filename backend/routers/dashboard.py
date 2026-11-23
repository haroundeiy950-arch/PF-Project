"""Dashboard aggregation API.

One call returns everything the Control Center needs: KPI cards, the active
threat panel, 24-hour timeline, level distribution, camera tiles, system health
and recent activity.  Keeping it in a single request keeps the live dashboard
snappy while the WebSocket channel pushes incremental updates.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, Query # type: ignore # type: ignore
from sqlalchemy import func, select # type: ignore
from sqlalchemy.orm import Session, joinedload, selectinload # type: ignore

from backend.ai.supervisor import supervisor
from backend.constants import LEVEL_LABELS, LEVEL_ORDER, THREAT_TYPE_LABELS
from backend.database import get_db
from backend.deps import get_current_user
from backend.models import AuditLog, Camera, Event, Incident, User, Zone
from backend.services import alarm, app_settings, storage
from backend.utils.time_utils import iso, now

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

ACTIVE_STATUSES = ("open", "acknowledged")
WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _kpis(db: Session, today_start) -> Dict[str, Any]:
    active = db.scalar(
        select(func.count()).select_from(Incident).where(Incident.status.in_(ACTIVE_STATUSES))
    ) or 0
    incidents_today = db.scalar(
        select(func.count()).select_from(Incident).where(Incident.detected_at >= today_start)
    ) or 0
    events_today = db.scalar(
        select(func.count()).select_from(Event).where(Event.occurred_at >= today_start)
    ) or 0
    critical_today = db.scalar(
        select(func.count())
        .select_from(Incident)
        .where(Incident.detected_at >= today_start, Incident.level == "critical")
    ) or 0
    false_alarms = db.scalar(
        select(func.count())
        .select_from(Incident)
        .where(Incident.detected_at >= today_start, Incident.status == "false_alarm")
    ) or 0

    response_rows = db.execute(
        select(Incident.detected_at, Incident.acknowledged_at)
        .where(
            Incident.acknowledged_at.isnot(None),
            Incident.detected_at >= now() - timedelta(days=7),
        )
        .limit(500)
    ).all()
    response_times = [
        max(0.0, (acked - detected).total_seconds() / 60.0)
        for detected, acked in response_rows
        if detected and acked
    ]
    avg_response = round(sum(response_times) / len(response_times), 1) if response_times else 0.0
    false_rate = round((false_alarms / incidents_today) * 100, 1) if incidents_today else 0.0

    cameras_total = db.scalar(select(func.count()).select_from(Camera)) or 0
    cameras_online = sum(1 for runtime in supervisor.all() if runtime.status == "online")
    if not supervisor.running:
        cameras_online = db.scalar(
            select(func.count()).select_from(Camera).where(Camera.status == "online")
        ) or 0

    disk = storage.disk_status()
    health = supervisor.health_snapshot() if supervisor.running else {}

    return {
        "active_threats": int(active),
        "incidents_today": int(incidents_today),
        "events_today": int(events_today),
        "critical_today": int(critical_today),
        "false_alarms_today": int(false_alarms),
        "false_alarm_rate": false_rate,
        "avg_response_minutes": avg_response,
        "verified_reduction": round(
            max(0.0, (1 - (incidents_today / events_today)) * 100), 1
        )
        if events_today
        else 0.0,
        "cameras_online": int(cameras_online),
        "cameras_total": int(cameras_total),
        "storage_gb": disk["storage_gb"],
        "storage_percent": disk["percent"],
        "uptime_seconds": health.get("uptime_seconds", 0),
    }


def _active_incidents(db: Session) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(Incident)
        .options(joinedload(Incident.camera), joinedload(Incident.zone))
        .where(Incident.status.in_(ACTIVE_STATUSES))
        .order_by(Incident.detected_at.desc())
        .limit(12)
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
    return [
        alarm.incident_payload(
            incident,
            incident.camera,
            incident.zone if incident.zone_id else None,
            include_relations=False,
        )
        for incident in rows
    ]


def _timeline_24h(db: Session, today_start) -> List[Dict[str, Any]]:
    current_hour = now().replace(minute=0, second=0, microsecond=0)
    start = current_hour - timedelta(hours=23)
    incidents = db.execute(
        select(Incident.detected_at).where(Incident.detected_at >= start)
    ).all()
    events = db.execute(select(Event.occurred_at).where(Event.occurred_at >= start)).all()

    incident_buckets: Counter = Counter()
    for (stamp,) in incidents:
        incident_buckets[stamp.replace(minute=0, second=0, microsecond=0)] += 1
    event_buckets: Counter = Counter()
    for (stamp,) in events:
        event_buckets[stamp.replace(minute=0, second=0, microsecond=0)] += 1

    timeline = []
    for offset in range(24):
        bucket = start + timedelta(hours=offset)
        timeline.append(
            {
                "hour": bucket.strftime("%H:00"),
                "timestamp": iso(bucket),
                "incidents": incident_buckets.get(bucket, 0),
                "events": event_buckets.get(bucket, 0),
            }
        )
    return timeline


def _level_distribution(db: Session, since) -> List[Dict[str, Any]]:
    rows = dict(
        db.execute(
            select(Incident.level, func.count())
            .where(Incident.detected_at >= since)
            .group_by(Incident.level)
        ).all()
    )
    return [
        {
            "level": level,
            "label": LEVEL_LABELS.get(level, level),
            "count": int(rows.get(level, 0)),
        }
        for level in ("critical", "high", "medium", "normal")
    ]


def _type_distribution(db: Session, since) -> List[Dict[str, Any]]:
    rows = db.execute(
        select(Incident.incident_type, func.count())
        .where(Incident.detected_at >= since)
        .group_by(Incident.incident_type)
        .order_by(func.count().desc())
    ).all()
    return [
        {
            "incident_type": name,
            "label": THREAT_TYPE_LABELS.get(name, name),
            "count": int(count),
        }
        for name, count in rows
    ]


def _weekly(db: Session) -> List[Dict[str, Any]]:
    today = now().date()
    start = today - timedelta(days=6)
    rows = db.execute(
        select(Incident.detected_at, Incident.level).where(
            Incident.detected_at >= now() - timedelta(days=7)
        )
    ).all()
    buckets: Dict[str, Dict[str, int]] = defaultdict(lambda: {"incidents": 0, "critical": 0})
    for stamp, level in rows:
        key = stamp.date().isoformat()
        buckets[key]["incidents"] += 1
        if level == "critical":
            buckets[key]["critical"] += 1
    result = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        data = buckets.get(day.isoformat(), {"incidents": 0, "critical": 0})
        result.append(
            {
                "date": day.isoformat(),
                "label": WEEKDAY_SHORT[day.weekday()],
                "incidents": data["incidents"],
                "critical": data["critical"],
            }
        )
    return result


def _cameras(db: Session) -> List[Dict[str, Any]]:
    counts = dict(
        db.execute(
            select(Incident.camera_id, func.count())
            .where(Incident.status.in_(ACTIVE_STATUSES))
            .group_by(Incident.camera_id)
        ).all()
    )
    cameras = db.scalars(select(Camera).order_by(Camera.code)).all()
    items = []
    for camera in cameras:
        runtime = supervisor.get(camera.id)
        meta = runtime.get_meta() if runtime else {}
        items.append(
            {
                "id": camera.id,
                "name": camera.name,
                "code": camera.code,
                "location": camera.location,
                "source_type": camera.source_type,
                "is_enabled": camera.is_enabled,
                "status": runtime.status if runtime else camera.status,
                "fps": round(meta.get("fps", 0.0), 1),
                "threat_level": meta.get("threat_level", "normal"),
                "risk_score": meta.get("risk_score", 0),
                "active_threats": int(counts.get(camera.id, 0)),
                "last_seen_at": iso(camera.last_seen_at),
                "stream_url": f"/api/cameras/{camera.id}/stream",
                "snapshot_url": f"/api/cameras/{camera.id}/snapshot",
            }
        )
    return items


def _recent_incidents(db: Session) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(Incident)
        .options(joinedload(Incident.camera), joinedload(Incident.zone))
        .order_by(Incident.detected_at.desc())
        .limit(8)
    ).all()
    return [
        alarm.incident_payload(
            incident,
            incident.camera,
            incident.zone if incident.zone_id else None,
            include_relations=False,
        )
        for incident in rows
    ]


def _recent_events(db: Session) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(Event)
        .options(joinedload(Event.camera), joinedload(Event.zone))
        .order_by(Event.occurred_at.desc())
        .limit(12)
    ).all()
    return [alarm.event_payload(event, event.camera) for event in rows]


def _top_zones(db: Session, since) -> List[Dict[str, Any]]:
    rows = db.execute(
        select(Zone.name, Zone.zone_type, Camera.code, func.count())
        .join(Incident, Incident.zone_id == Zone.id)
        .join(Camera, Zone.camera_id == Camera.id)
        .where(Incident.detected_at >= since)
        .group_by(Zone.id)
        .order_by(func.count().desc())
        .limit(5)
    ).all()
    return [
        {
            "zone_name": name,
            "zone_type": zone_type,
            "camera_code": code,
            "incidents": int(count),
        }
        for name, zone_type, code, count in rows
    ]


def _recent_activity(db: Session) -> List[Dict[str, Any]]:
    rows = db.scalars(
        select(AuditLog)
        .options(joinedload(AuditLog.user))
        .order_by(AuditLog.created_at.desc())
        .limit(8)
    ).all()
    return [
        {
            "id": entry.id,
            "username": entry.user.username if entry.user else "system",
            "action": entry.action,
            "target": entry.target,
            "detail": entry.detail,
            "created_at": iso(entry.created_at),
        }
        for entry in rows
    ]


@router.get("")
def dashboard(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    current = now()
    today_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    since_24h = current - timedelta(hours=24)
    active = _active_incidents(db)
    health = supervisor.health_snapshot() if supervisor.running else {
        "status": "healthy",
        "cpu_percent": 0,
        "memory_percent": 0,
        "disk_percent": storage.disk_status()["percent"],
        "storage_gb": storage.disk_status()["storage_gb"],
        "cameras_online": 0,
        "cameras_total": db.scalar(select(func.count()).select_from(Camera)) or 0,
        "uptime_seconds": 0,
        "fps_total": 0.0,
        "pipeline_running": False,
        "checked_at": iso(current),
    }
    health.setdefault("pipeline_running", supervisor.running)
    settings_payload = app_settings.get_settings(db)

    return {
        "generated_at": iso(current),
        "kpis": _kpis(db, today_start),
        "active": {
            "items": active,
            "total": len(active),
            "primary": active[0] if active else None,
            "critical_count": sum(1 for item in active if item["level"] == "critical"),
            "high_count": sum(1 for item in active if item["level"] == "high"),
        },
        "recent_incidents": _recent_incidents(db),
        "recent_events": _recent_events(db),
        "timeline": _timeline_24h(db, today_start),
        "level_distribution": _level_distribution(db, since_24h),
        "type_distribution": _type_distribution(db, since_24h),
        "weekly": _weekly(db),
        "cameras": _cameras(db),
        "health": health,
        "top_zones": _top_zones(db, since_24h),
        "activity": _recent_activity(db),
        "alerting": {
            "voice_enabled": bool(settings_payload["voice"].get("enabled", True)),
            "siren_enabled": bool(settings_payload["alarm"].get("siren_enabled", False)),
            "languages": settings_payload["voice"].get("languages", ["en", "ar"]),
            "repeat_seconds": settings_payload["voice"].get("repeat_seconds", 20),
        },
    }


@router.get("/timeline")
def timeline(
    hours: int = Query(default=24, ge=6, le=168),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    current_hour = now().replace(minute=0, second=0, microsecond=0)
    start = current_hour - timedelta(hours=hours - 1)
    incidents = db.execute(
        select(Incident.detected_at).where(Incident.detected_at >= start)
    ).all()
    events = db.execute(select(Event.occurred_at).where(Event.occurred_at >= start)).all()
    incident_buckets: Counter = Counter(stamp.replace(minute=0, second=0, microsecond=0) for (stamp,) in incidents)
    event_buckets: Counter = Counter(stamp.replace(minute=0, second=0, microsecond=0) for (stamp,) in events)
    items = []
    for offset in range(hours):
        bucket = start + timedelta(hours=offset)
        items.append(
            {
                "hour": bucket.strftime("%H:00"),
                "timestamp": iso(bucket),
                "incidents": incident_buckets.get(bucket, 0),
                "events": event_buckets.get(bucket, 0),
            }
        )
    return {"items": items, "hours": hours}


@router.get("/health")
def dashboard_health(_: User = Depends(get_current_user)):
    snapshot = supervisor.health_snapshot()
    snapshot["pipeline_running"] = supervisor.running
    return snapshot


__all__ = ["router"]
