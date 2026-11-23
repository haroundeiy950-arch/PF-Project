"""Analytics and report exports (Section 15)."""

from __future__ import annotations

import csv
import io
from collections import Counter
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query # type: ignore
from fastapi.responses import StreamingResponse # type: ignore
from sqlalchemy import func, select # type: ignore
from sqlalchemy.orm import Session, joinedload # type: ignore

from backend.constants import LEVEL_LABELS, THREAT_TYPE_LABELS
from backend.database import get_db
from backend.deps import get_current_user, require_permissions
from backend.models import Camera, Event, Incident, User, Zone
from backend.utils.time_utils import iso, now, parse_datetime

router = APIRouter(prefix="/api/reports", tags=["Reports"])

WEEKDAY_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _range(start: Optional[str], end: Optional[str]) -> tuple:
    end_dt = parse_datetime(end) or now()
    start_dt = parse_datetime(start) or (end_dt - timedelta(days=7))
    if start_dt > end_dt:
        start_dt, end_dt = end_dt, start_dt
    return start_dt, end_dt


def _csv_response(filename: str, headers: List[str], rows: List[List[Any]]) -> StreamingResponse:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(["" if value is None else value for value in row])
    content = "\ufeff" + buffer.getvalue()  # BOM keeps Arabic readable in Excel
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/overview")
def report_overview(
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("view_reports")),
):
    start_dt, end_dt = _range(start, end)
    incidents = db.scalars(
        select(Incident)
        .options(joinedload(Incident.camera), joinedload(Incident.zone))
        .where(Incident.detected_at >= start_dt, Incident.detected_at <= end_dt)
        .order_by(Incident.detected_at)
    ).all()
    event_count = db.scalar(
        select(func.count())
        .select_from(Event)
        .where(Event.occurred_at >= start_dt, Event.occurred_at <= end_dt)
    ) or 0

    level_counts = Counter(incident.level for incident in incidents)
    type_counts = Counter(incident.incident_type for incident in incidents)
    status_counts = Counter(incident.status for incident in incidents)
    camera_counts = Counter(incident.camera.name if incident.camera else "Unknown" for incident in incidents)
    zone_counts = Counter(incident.zone.name if incident.zone else "Unassigned" for incident in incidents)

    response_times = [
        (incident.acknowledged_at - incident.detected_at).total_seconds() / 60.0
        for incident in incidents
        if incident.acknowledged_at
    ]
    resolution_times = [
        (incident.resolved_at - incident.detected_at).total_seconds() / 60.0
        for incident in incidents
        if incident.resolved_at
    ]

    daily: Dict[str, Dict[str, int]] = {}
    day = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    while day.date() <= end_dt.date():
        daily[day.date().isoformat()] = {"incidents": 0, "critical": 0, "high": 0}
        day += timedelta(days=1)
    for incident in incidents:
        key = incident.detected_at.date().isoformat()
        if key in daily:
            daily[key]["incidents"] += 1
            if incident.level in {"critical", "high"}:
                daily[key][incident.level] += 1

    total = len(incidents)
    false_alarms = status_counts.get("false_alarm", 0)
    return {
        "range": {
            "start": iso(start_dt),
            "end": iso(end_dt),
            "days": max(1, (end_dt.date() - start_dt.date()).days + 1),
        },
        "totals": {
            "incidents": total,
            "events": int(event_count),
            "critical": level_counts.get("critical", 0),
            "high": level_counts.get("high", 0),
            "medium": level_counts.get("medium", 0),
            "normal": level_counts.get("normal", 0),
            "false_alarms": false_alarms,
            "open": status_counts.get("open", 0),
            "acknowledged": status_counts.get("acknowledged", 0),
            "resolved": status_counts.get("resolved", 0),
            "false_alarm_rate": round((false_alarms / total) * 100, 1) if total else 0.0,
            "avg_response_minutes": round(sum(response_times) / len(response_times), 1)
            if response_times
            else 0.0,
            "avg_resolution_minutes": round(sum(resolution_times) / len(resolution_times), 1)
            if resolution_times
            else 0.0,
            "verification_reduction": round(max(0.0, (1 - total / event_count) * 100), 1)
            if event_count
            else 0.0,
        },
        "by_level": [
            {
                "level": level,
                "label": LEVEL_LABELS.get(level, level),
                "count": level_counts.get(level, 0),
            }
            for level in ("critical", "high", "medium", "normal")
        ],
        "by_type": [
            {
                "incident_type": key,
                "label": THREAT_TYPE_LABELS.get(key, key),
                "count": count,
            }
            for key, count in type_counts.most_common()
        ],
        "by_status": [{"status": key, "count": count} for key, count in status_counts.items()],
        "by_camera": [
            {"camera_name": key, "count": count} for key, count in camera_counts.most_common()
        ],
        "by_zone": [{"zone_name": key, "count": count} for key, count in zone_counts.most_common()],
        "daily": [
            {
                "date": key,
                "label": WEEKDAY_SHORT[date.fromisoformat(key).weekday()],
                **values,
            }
            for key, values in daily.items()
        ],
        "generated_at": iso(now()),
    }


@router.get("/incidents.csv")
def export_incidents(
    start: Optional[str] = None,
    end: Optional[str] = None,
    level: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("export_data")),
):
    start_dt, end_dt = _range(start, end)
    query = (
        select(Incident)
        .options(joinedload(Incident.camera), joinedload(Incident.zone))
        .where(Incident.detected_at >= start_dt, Incident.detected_at <= end_dt)
        .order_by(Incident.detected_at.desc())
    )
    if level:
        query = query.where(Incident.level == level)
    incidents = db.scalars(query).all()
    rows = [
        [
            incident.code,
            incident.detected_at.strftime("%Y-%m-%d %H:%M:%S"),
            incident.level,
            incident.risk_score,
            incident.status,
            incident.incident_type,
            incident.title,
            incident.camera.name if incident.camera else "",
            incident.camera.code if incident.camera else "",
            incident.zone.name if incident.zone else "",
            incident.target_type,
            incident.face_status,
            incident.explanation,
            incident.detected_at.strftime("%Y-%m-%d"),
        ]
        for incident in incidents
    ]
    filename = f"sentinel-incidents-{start_dt.strftime('%Y%m%d')}-{end_dt.strftime('%Y%m%d')}.csv"
    return _csv_response(
        filename,
        [
            "Code",
            "Detected",
            "Level",
            "Risk score",
            "Status",
            "Type",
            "Title",
            "Camera",
            "Camera code",
            "Zone",
            "Target",
            "Face status",
            "Explanation",
            "Date",
        ],
        rows,
    )


@router.get("/events.csv")
def export_events(
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("export_data")),
):
    start_dt, end_dt = _range(start, end)
    events = db.scalars(
        select(Event)
        .options(joinedload(Event.camera), joinedload(Event.zone))
        .where(Event.occurred_at >= start_dt, Event.occurred_at <= end_dt)
        .order_by(Event.occurred_at.desc())
        .limit(20000)
    ).all()
    rows = [
        [
            event.id,
            event.occurred_at.strftime("%Y-%m-%d %H:%M:%S"),
            event.event_type,
            event.target_type,
            round(event.confidence, 3),
            "yes" if event.is_threat else "no",
            event.track_id,
            event.camera.name if event.camera else "",
            event.zone.name if event.zone else "",
            event.incident_id or "",
        ]
        for event in events
    ]
    filename = f"sentinel-events-{start_dt.strftime('%Y%m%d')}-{end_dt.strftime('%Y%m%d')}.csv"
    return _csv_response(
        filename,
        [
            "ID",
            "Occurred",
            "Event type",
            "Target",
            "Confidence",
            "Threat",
            "Track",
            "Camera",
            "Zone",
            "Incident",
        ],
        rows,
    )


@router.get("/export")
def export_json(
    start: Optional[str] = None,
    end: Optional[str] = None,
    db: Session = Depends(get_db),
    _: User = Depends(require_permissions("export_data")),
):
    """Full JSON evidence package for auditors."""
    start_dt, end_dt = _range(start, end)
    incidents = db.scalars(
        select(Incident)
        .options(
            joinedload(Incident.camera),
            joinedload(Incident.zone),
            joinedload(Incident.alerts),
            joinedload(Incident.recordings),
        )
        .where(Incident.detected_at >= start_dt, Incident.detected_at <= end_dt)
        .order_by(Incident.detected_at.desc())
    ).unique().all()
    cameras = db.scalars(select(Camera)).all()
    zones = db.scalars(select(Zone)).all()
    return {
        "generated_at": iso(now()),
        "range": {"start": iso(start_dt), "end": iso(end_dt)},
        "counts": {"incidents": len(incidents), "cameras": len(cameras), "zones": len(zones)},
        "incidents": [
            {
                "code": incident.code,
                "detected_at": iso(incident.detected_at),
                "level": incident.level,
                "risk_score": incident.risk_score,
                "status": incident.status,
                "type": incident.incident_type,
                "title": incident.title,
                "camera": incident.camera.name if incident.camera else None,
                "zone": incident.zone.name if incident.zone else None,
                "explanation": incident.explanation,
                "factors": incident.factors,
                "acknowledged_at": iso(incident.acknowledged_at),
                "resolved_at": iso(incident.resolved_at),
                "alerts": [
                    {
                        "channel": alert.channel,
                        "language": alert.language,
                        "message": alert.message,
                        "status": alert.status,
                    }
                    for alert in incident.alerts
                ],
                "recordings": [
                    {"kind": recording.kind, "path": recording.path}
                    for recording in incident.recordings
                ],
            }
            for incident in incidents
        ],
    }


__all__ = ["router"]
