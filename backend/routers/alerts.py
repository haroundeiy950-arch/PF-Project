"""Alert channel endpoints (voice, notification, siren).

Voice warnings are stored in both English and Arabic with every incident.  The
browser picks up pending warnings from ``/api/alerts/pending`` and synthesises
them with the Web Speech API; marking an alert as playing/stopped is persisted
here so every operator screen stays in sync.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request # type: ignore
from sqlalchemy import func, select # type: ignore
from sqlalchemy.orm import Session, joinedload # type: ignore

from backend.constants import THREAT_TYPE_LABELS, VOICE_TEMPLATES
from backend.database import get_db
from backend.deps import client_ip, get_current_user, require_permissions
from backend.models import Alert, Incident, User
from backend.realtime import manager
from backend.schemas import MessageResponse
from backend.services import alarm, storage
from backend.services.audit import record_audit
from backend.utils.time_utils import iso, now

router = APIRouter(prefix="/api", tags=["Alerts"])

FINAL_STATUSES = {"resolved", "false_alarm"}


def _alert_context(alert: Alert) -> dict:
    payload = alarm.alert_payload(alert)
    incident = alert.incident
    if incident is not None:
        payload.update(
            {
                "incident_code": incident.code,
                "incident_title": incident.title,
                "incident_level": incident.level,
                "incident_status": incident.status,
                "camera_id": incident.camera_id,
                "snapshot_url": storage.media_url(incident.snapshot_path),
                "detected_at": iso(incident.detected_at),
            }
        )
    return payload


@router.get("/alerts/templates")
def alert_templates(_: User = Depends(get_current_user)):
    return {
        "languages": [
            {"code": "en", "label": "English", "voice": "en-US"},
            {"code": "ar", "label": "العربية", "voice": "ar-SA"},
        ],
        "channels": [
            {"value": "voice", "label": "Bilingual voice warning"},
            {"value": "notification", "label": "Operator / control room notification"},
            {"value": "siren", "label": "Local siren"},
        ],
        "threats": [
            {"value": key, "label": THREAT_TYPE_LABELS.get(key, key)}
            for key in VOICE_TEMPLATES
        ],
        "templates": [
            {
                "threat_type": threat,
                "label": THREAT_TYPE_LABELS.get(threat, threat),
                "en": messages.get("en", ""),
                "ar": messages.get("ar", ""),
            }
            for threat, messages in VOICE_TEMPLATES.items()
        ],
    }


@router.get("/alerts/pending")
def pending_alerts(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Warnings which the operator browser still has to speak."""
    rows = db.scalars(
        select(Alert)
        .options(joinedload(Alert.incident))
        .join(Incident, Alert.incident_id == Incident.id)
        .where(
            Alert.channel == "voice",
            Alert.status == "not_started",
            Incident.status.in_(("open", "acknowledged")),
        )
        .order_by(Alert.created_at.desc())
        .limit(20)
    ).all()
    return {"items": [_alert_context(alert) for alert in rows], "total": len(rows)}


@router.get("/alerts")
def list_alerts(
    incident_id: Optional[int] = None,
    channel: Optional[str] = None,
    language: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = select(Alert).options(joinedload(Alert.incident))
    count_query = select(func.count()).select_from(Alert)
    filters = []
    if incident_id is not None:
        filters.append(Alert.incident_id == incident_id)
    if channel:
        filters.append(Alert.channel == channel)
    if language:
        filters.append(Alert.language == language)
    if status:
        filters.append(Alert.status == status)
    for condition in filters:
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = db.scalar(count_query) or 0
    rows = db.scalars(
        query.order_by(Alert.created_at.desc()).offset(offset).limit(limit)
    ).all()
    return {
        "items": [_alert_context(alert) for alert in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/alerts/{alert_id}")
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return _alert_context(alert)


@router.post("/alerts/{alert_id}/play")
def play_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.channel != "voice":
        raise HTTPException(status_code=400, detail="Only voice alerts can be played")
    if alert.incident and alert.incident.status in FINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Incident is already closed")

    alarm.mark_alert_playing(db, alert, "playing")
    if alert.played_at is None:
        alert.played_at = now()
    db.commit()
    db.refresh(alert)
    payload = _alert_context(alert)
    manager.broadcast_threadsafe("alert.playing", payload)
    return payload


@router.post("/alerts/{alert_id}/stop")
def stop_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "stopped"
    db.commit()
    db.refresh(alert)
    payload = _alert_context(alert)
    manager.broadcast_threadsafe("alert.updated", payload)
    return payload


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("acknowledge_alarms")),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.status = "acknowledged"
    alert.acknowledged_at = now()
    record_audit(
        db,
        actor,
        "alert.acknowledge",
        target=f"alert:{alert.id}",
        detail=f"{alert.channel}/{alert.language}",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    db.refresh(alert)
    payload = _alert_context(alert)
    manager.broadcast_threadsafe("alert.updated", payload)
    return payload


@router.post("/alerts/incidents/{incident_id}/replay")
def replay_incident_voice(
    incident_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("acknowledge_alarms")),
):
    """Re-queue the English and Arabic warnings of an incident."""
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status_code=404, detail="Incident not found")
    if incident.status in FINAL_STATUSES:
        raise HTTPException(status_code=409, detail="Incident is already closed")

    requeued = 0
    for alert in incident.alerts:
        if alert.channel == "voice":
            alert.status = "not_started"
            alert.played_at = None
            alert.acknowledged_at = None
            requeued += 1
    record_audit(
        db,
        actor,
        "alert.replay",
        target=incident.code,
        detail=f"Re-queued {requeued} bilingual warning(s)",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    manager.broadcast_threadsafe(
        "alert.replay",
        {"incident_id": incident.id, "code": incident.code, "count": requeued},
    )
    return {"message": "Warnings re-queued", "count": requeued}


@router.post("/alerts/{alert_id}/resend")
def resend_notification(
    alert_id: int,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("acknowledge_alarms")),
):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    if alert.channel not in {"notification", "siren"}:
        raise HTTPException(status_code=400, detail="Only notification or siren alerts can be resent")
    alert.status = "sent"
    record_audit(
        db,
        actor,
        "alert.resend",
        target=f"alert:{alert.id}",
        detail=alert.channel,
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    manager.broadcast_threadsafe("alert.updated", _alert_context(alert))
    return MessageResponse(message="Alert re-sent to the monitoring center")


__all__ = ["router"]
