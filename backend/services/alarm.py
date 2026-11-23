"""Alarm & emergency response chain (Section 3).

The chain is always the same:

1. the camera detects an event
2. the risk engine classifies it
3. the siren sounds (optional)
4. a remote notification is sent
5. before/after evidence is saved
6. the incident is logged

This module owns incident creation, alert dispatch, acknowledgement and the
JSON payloads used by the REST API and the WebSocket channel.
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.config import settings
from backend.constants import LEVEL_LABELS, THREAT_TYPE_LABELS
from backend.models import (
    Acknowledgement,
    Alert,
    Camera,
    Event,
    Incident,
    Recording,
    User,
    Zone,
)
from backend.realtime import manager
from backend.services import notifications, siren
from backend.services import storage
from backend.services.risk import RiskResult
from backend.services.voice import build_voice_messages, incident_title
from backend.utils.time_utils import iso, now


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def _camera_dict(camera: Optional[Camera]) -> Dict[str, Any]:
    if not camera:
        return {"camera_name": None, "camera_code": None, "camera_location": None}
    return {
        "camera_name": camera.name,
        "camera_code": camera.code,
        "camera_location": camera.location,
    }


def alert_payload(alert: Alert) -> Dict[str, Any]:
    return {
        "id": alert.id,
        "incident_id": alert.incident_id,
        "channel": alert.channel,
        "language": alert.language,
        "message": alert.message,
        "status": alert.status,
        "sent_to": alert.sent_to,
        "played_at": iso(alert.played_at),
        "acknowledged_at": iso(alert.acknowledged_at),
        "detail": alert.detail,
        "created_at": iso(alert.created_at),
    }


def recording_payload(recording: Recording) -> Dict[str, Any]:
    return {
        "id": recording.id,
        "incident_id": recording.incident_id,
        "camera_id": recording.camera_id,
        "kind": recording.kind,
        "url": storage.media_url(recording.path),
        "path": recording.path,
        "started_at": iso(recording.started_at),
        "ended_at": iso(recording.ended_at),
        "duration_seconds": recording.duration_seconds,
        "size_bytes": recording.size_bytes,
        "created_at": iso(recording.created_at),
    }


def acknowledgement_payload(ack: Acknowledgement) -> Dict[str, Any]:
    return {
        "id": ack.id,
        "incident_id": ack.incident_id,
        "user_id": ack.user_id,
        "user_name": ack.user.full_name if ack.user else None,
        "note": ack.note,
        "acknowledged_at": iso(ack.acknowledged_at),
    }


def event_payload(event: Event, camera: Optional[Camera] = None) -> Dict[str, Any]:
    camera = camera or event.camera
    return {
        "id": event.id,
        "camera_id": event.camera_id,
        "zone_id": event.zone_id,
        "incident_id": event.incident_id,
        "event_type": event.event_type,
        "target_type": event.target_type,
        "confidence": round(event.confidence, 3),
        "bbox": event.bbox or [],
        "track_id": event.track_id,
        "is_threat": event.is_threat,
        "snapshot_url": storage.media_url(event.snapshot_path),
        "meta": event.meta or {},
        "occurred_at": iso(event.occurred_at),
        "camera_name": camera.name if camera else None,
        "zone_name": event.zone.name if event.zone else None,
    }


def incident_payload(
    incident: Incident,
    camera: Optional[Camera] = None,
    zone: Optional[Zone] = None,
    include_relations: bool = True,
    event_count: Optional[int] = None,
) -> Dict[str, Any]:
    camera = camera or incident.camera
    zone = zone or (incident.zone if incident.zone_id else None)
    data: Dict[str, Any] = {
        "id": incident.id,
        "code": incident.code,
        "camera_id": incident.camera_id,
        "zone_id": incident.zone_id,
        "incident_type": incident.incident_type,
        "title": incident.title,
        "risk_score": incident.risk_score,
        "level": incident.level,
        "level_label": LEVEL_LABELS.get(incident.level, incident.level),
        "status": incident.status,
        "explanation": incident.explanation,
        "factors": incident.factors or {},
        "target_type": incident.target_type,
        "track_id": incident.track_id,
        "face_status": incident.face_status,
        "detected_at": iso(incident.detected_at),
        "acknowledged_at": iso(incident.acknowledged_at),
        "acknowledged_by_id": incident.acknowledged_by_id,
        "resolved_at": iso(incident.resolved_at),
        "snapshot_url": storage.media_url(incident.snapshot_path),
        "clip_url": storage.media_url(incident.clip_path),
        "camera_name": camera.name if camera else None,
        "camera_code": camera.code if camera else None,
        "camera_location": camera.location if camera else None,
        "zone_name": zone.name if zone else None,
        "zone_type": zone.zone_type if zone else None,
        "type_label": THREAT_TYPE_LABELS.get(incident.incident_type, incident.incident_type),
        "meta": incident.meta or {},
    }
    if include_relations:
        data["alerts"] = [alert_payload(alert) for alert in incident.alerts]
        data["recordings"] = [recording_payload(rec) for rec in incident.recordings]
        data["acknowledgements"] = [
            acknowledgement_payload(ack) for ack in incident.acknowledgements
        ]
        data["event_count"] = (
            event_count
            if event_count is not None
            else sum(1 for _ in (incident.events or []))
        )
    return data


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------
_code_lock = threading.Lock()
_code_state: Dict[str, int] = {}


def next_incident_code(db: Session, at: Optional[datetime] = None) -> str:
    """Return the next human-readable incident code.

    Camera workers run concurrently, so the database counter alone is not
    enough: two workers can read the same ``COUNT(*)`` before either
    transaction commits, which used to raise ``UNIQUE constraint failed``.
    The per-day in-process counter guarantees uniqueness even while the
    insert of the previous worker is still uncommitted.
    """
    at = at or now()
    day = at.strftime("%Y%m%d")
    prefix = f"INC-{day}-"
    with _code_lock:
        latest = db.scalar(
            select(func.max(Incident.code)).where(Incident.code.like(f"{prefix}%"))
        )
        db_max = 0
        if latest:
            try:
                db_max = int(str(latest).rsplit("-", 1)[1])
            except (IndexError, ValueError):
                db_max = 0
        sequence = max(db_max, _code_state.get(day, 0)) + 1
        _code_state[day] = sequence
        return f"{prefix}{sequence:04d}"


def create_event(
    db: Session,
    camera: Camera,
    *,
    event_type: str,
    target_type: str = "unknown",
    confidence: float = 0.0,
    bbox: Sequence[float] = (),
    track_id: str = "",
    zone: Optional[Zone] = None,
    is_threat: bool = False,
    snapshot_path: str = "",
    incident_id: Optional[int] = None,
    meta: Optional[Dict[str, Any]] = None,
    occurred_at: Optional[datetime] = None,
) -> Event:
    event = Event(
        camera_id=camera.id,
        zone_id=zone.id if zone else None,
        incident_id=incident_id,
        event_type=event_type,
        target_type=target_type,
        confidence=float(confidence),
        bbox=list(bbox),
        track_id=track_id,
        is_threat=is_threat,
        snapshot_path=snapshot_path,
        meta=meta or {},
        occurred_at=occurred_at or now(),
    )
    db.add(event)
    db.flush()
    return event


def create_incident(
    db: Session,
    camera: Camera,
    *,
    threat_type: str,
    risk: RiskResult,
    target_type: str = "person",
    track_id: str = "",
    face_status: str = "unknown",
    zone: Optional[Zone] = None,
    snapshot_path: str = "",
    factors: Optional[Dict[str, Any]] = None,
    detected_at: Optional[datetime] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Incident:
    """Create the incident and run the full alarm response chain."""
    incident = Incident(
        code=next_incident_code(db, detected_at),
        camera_id=camera.id,
        zone_id=zone.id if zone else None,
        incident_type=threat_type,
        title=incident_title(threat_type, camera.name),
        risk_score=risk.score,
        level=risk.level,
        status="open",
        explanation=risk.explanation,
        factors={
            "contributions": risk.contributions,
            "breakdown": risk.breakdown,
            **(factors or {}),
        },
        target_type=target_type,
        track_id=track_id,
        face_status=face_status,
        detected_at=detected_at or now(),
        snapshot_path=snapshot_path,
        meta=meta or {},
    )
    db.add(incident)
    db.flush()

    _dispatch_alerts(db, incident, camera, risk)

    # The notification is fire-and-forget; it must never block the pipeline.
    notifications.send_notification(
        title=incident.title,
        message=risk.explanation,
        level=risk.level,
        incident_id=incident.id,
        extra={
            "camera": camera.name,
            "camera_code": camera.code,
            "zone": zone.name if zone else None,
            "risk_score": risk.score,
        },
    )
    db.flush()
    return incident


def _dispatch_alerts(
    db: Session, incident: Incident, camera: Camera, risk: RiskResult
) -> List[Alert]:
    alerts: List[Alert] = []

    for message in build_voice_messages(
        incident.incident_type, camera.name, camera.code
    ):
        alert = Alert(
            incident_id=incident.id,
            channel="voice",
            language=message["language"],
            message=message["text"],
            status="not_started" if settings.voice_enabled else "stopped",
            detail="Waiting for operator screen to play the warning"
            if settings.voice_enabled
            else "Voice alerts disabled",
        )
        db.add(alert)
        alerts.append(alert)

    notification_alert = Alert(
        incident_id=incident.id,
        channel="notification",
        language="en",
        message=f"{incident.title}. {risk.explanation}",
        status="sent",
        sent_to=notifications.notification_target(),
        detail="Sent to administrator / remote monitoring center",
    )
    db.add(notification_alert)
    alerts.append(notification_alert)

    if settings.siren_enabled and risk.level in {"high", "critical"}:
        siren_state = siren.trigger_siren(3.0)
        siren_alert = Alert(
            incident_id=incident.id,
            channel="siren",
            language="en",
            message="Local siren triggered",
            status="playing" if siren_state == "playing" else siren_state,
            sent_to="local-siren",
        )
        db.add(siren_alert)
        alerts.append(siren_alert)

    db.flush()
    return alerts


def add_event_to_incident(
    db: Session,
    incident: Incident,
    event: Optional[Event],
    risk: Optional[RiskResult] = None,
    escalate: bool = False,
) -> None:
    """Merge a repeated detection into an existing incident."""
    if event is not None:
        event.incident_id = incident.id
        event.is_threat = True
        event.snapshot_path = event.snapshot_path or incident.snapshot_path

    if risk is not None:
        if risk.score > incident.risk_score:
            incident.risk_score = risk.score
            incident.level = risk.level
            incident.explanation = risk.explanation
            incident.factors = {
                "contributions": risk.contributions,
                "breakdown": risk.breakdown,
                **(incident.factors or {}),
            }
        if escalate:
            incident.status = "open"
            incident.meta = {**(incident.meta or {}), "last_escalated_at": iso(now())}
    db.flush()


# ---------------------------------------------------------------------------
# Operator actions
# ---------------------------------------------------------------------------
def acknowledge_incident(
    db: Session,
    incident: Incident,
    user: User,
    note: str = "",
) -> Acknowledgement:
    stamp = now()
    incident.status = "acknowledged"
    incident.acknowledged_at = stamp
    incident.acknowledged_by_id = user.id

    for alert in incident.alerts:
        if alert.channel == "voice" and alert.status != "acknowledged":
            alert.status = "acknowledged"
            alert.acknowledged_at = stamp
        elif alert.channel == "siren" and alert.status == "playing":
            alert.status = "stopped"

    ack = Acknowledgement(
        incident_id=incident.id,
        user_id=user.id,
        note=note,
        acknowledged_at=stamp,
    )
    db.add(ack)
    db.flush()
    return ack


def resolve_incident(
    db: Session,
    incident: Incident,
    user: User,
    status: str = "resolved",
    note: str = "",
) -> None:
    stamp = now()
    incident.status = status
    incident.resolved_at = stamp
    if status == "false_alarm":
        incident.meta = {**(incident.meta or {}), "false_alarm_by": user.username, "note": note}
    for alert in incident.alerts:
        if alert.channel == "voice" and alert.status in {"not_started", "playing"}:
            alert.status = "stopped"
    db.flush()


def mark_alert_playing(db: Session, alert: Alert, status: str = "playing") -> Alert:
    alert.status = status
    if status == "playing" and alert.played_at is None:
        alert.played_at = now()
    db.flush()
    return alert


# ---------------------------------------------------------------------------
# Realtime helpers
# ---------------------------------------------------------------------------
def broadcast_incident(
    db: Session, incident: Incident, event_type: str = "incident.created"
) -> None:
    camera = db.get(Camera, incident.camera_id)
    zone = db.get(Zone, incident.zone_id) if incident.zone_id else None
    payload = incident_payload(incident, camera, zone, include_relations=True)
    manager.broadcast_threadsafe(event_type, payload)


def broadcast_alert(alert: Alert, event_type: str = "alert.updated") -> None:
    manager.broadcast_threadsafe(event_type, alert_payload(alert))


def broadcast_event(event: Event, event_type: str = "event.created") -> None:
    manager.broadcast_threadsafe(event_type, event_payload(event))


def broadcast_stats_refresh() -> None:
    manager.broadcast_threadsafe("stats.refresh", {"reason": "pipeline"})
