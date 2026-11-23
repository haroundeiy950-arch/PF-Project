"""Runtime settings: risk weights, thresholds, voice, recording and AI.

The Settings screen can tune the whole alarm chain without a restart; camera
workers reload these values every few seconds.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends, HTTPException, Request # type: ignore
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session # type: ignore

from backend.config import settings as env_settings
from backend.constants import (
    DEFAULT_RISK_WEIGHTS,
    DEFAULT_VERIFICATION,
    FACTOR_LABELS,
    LEVEL_LABELS,
    PERMISSIONS,
    RISK_THRESHOLDS,
    ROLE_DEFINITIONS,
    THREAT_TYPE_LABELS,
    VOICE_TEMPLATES,
    ZONE_TYPE_LABELS,
)
from backend.database import get_db
from backend.deps import client_ip, get_current_user, require_permissions
from backend.models import User
from backend.schemas import MessageResponse, RiskEvaluationPreview, SettingsUpdate
from backend.services import app_settings, storage
from backend.services.audit import record_audit
from backend.services.risk import (
    RiskFactors,
    clean_weights,
    evaluate_risk,
    factor_table,
    validate_weights,
)

router = APIRouter(prefix="/api/settings", tags=["Settings"])

_FACTOR_DEFAULTS = DEFAULT_RISK_WEIGHTS


class RiskPreviewRequest(BaseModel):
    zone_type: str = "public"
    target_type: str = "person"
    hour: int = Field(default=12, ge=0, le=23)
    dwell_seconds: float = Field(default=0.0, ge=0, le=3600)
    dwell_target: float = Field(default=2.0, ge=0.1, le=3600)
    face_status: str = "none"
    repetition: int = Field(default=1, ge=1, le=100)
    behavior: str = "normal"
    inside_zone: bool = True


def _normalize(key: str, value: Any) -> Any:
    if key == "risk_weights":
        valid, error = validate_weights(value)
        if not valid:
            raise HTTPException(status_code=400, detail=error)
        return clean_weights(value)

    if key == "risk_thresholds":
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail="Thresholds must be an object")
        merged = dict(RISK_THRESHOLDS)
        for name in ("medium", "high", "critical"):
            if name in value:
                try:
                    merged[name] = int(value[name])
                except (TypeError, ValueError) as exc:
                    raise HTTPException(status_code=400, detail=f"Invalid {name} threshold") from exc
        if not (0 < merged["medium"] < merged["high"] < merged["critical"] <= 100):
            raise HTTPException(
                status_code=400,
                detail="Thresholds must satisfy 0 < medium < high < critical <= 100",
            )
        return merged

    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail=f"{key} must be an object")

    if key == "verification":
        merged = {**DEFAULT_VERIFICATION, **value}
        merged["min_frames"] = max(1, min(int(merged.get("min_frames", 6)), 120))
        merged["min_dwell_seconds"] = max(
            0.0, min(float(merged.get("min_dwell_seconds", 2.0)), 120.0)
        )
        merged["cooldown_seconds"] = max(
            0, min(int(merged.get("cooldown_seconds", 90)), 3600)
        )
        merged["group_window_seconds"] = max(
            0, min(int(merged.get("group_window_seconds", 120)), 3600)
        )
        merged["escalation_only"] = bool(merged.get("escalation_only", True))
        return merged

    if key == "voice":
        merged = {
            "enabled": bool(value.get("enabled", env_settings.voice_enabled)),
            "repeat_seconds": max(5, min(int(value.get("repeat_seconds", 20)), 300)),
            "languages": [
                language
                for language in value.get("languages", ["en", "ar"])
                if language in {"en", "ar"}
            ]
            or ["en"],
        }
        return merged

    if key == "alarm":
        return {
            "siren_enabled": bool(value.get("siren_enabled", False)),
            "webhook_url": str(value.get("webhook_url", ""))[:500],
            "notify_admin": bool(value.get("notify_admin", True)),
        }

    if key == "recording":
        return {
            "enabled": bool(value.get("enabled", True)),
            "pre_event_seconds": max(0, min(int(value.get("pre_event_seconds", 6)), 60)),
            "post_event_seconds": max(0, min(int(value.get("post_event_seconds", 3)), 60)),
            "retention_days": max(1, min(int(value.get("retention_days", 14)), 365)),
        }

    if key == "ai":
        return {
            "detector_mode": str(value.get("detector_mode", "auto")).lower(),
            "face_recognition_enabled": bool(value.get("face_recognition_enabled", False)),
            "target_fps": max(1, min(int(value.get("target_fps", 8)), 30)),
            "demo_mode": bool(value.get("demo_mode", True)),
        }

    if key == "company":
        return {
            "name": str(value.get("name", "Sentinel AI"))[:120],
            "site": str(value.get("site", "Perimeter Control Center"))[:160],
            "timezone": str(value.get("timezone", "local"))[:60],
            "notice": str(value.get("notice", ""))[:500],
        }

    return value


def _metadata() -> Dict[str, Any]:
    return {
        "risk_factors": [
            {"key": key, "label": FACTOR_LABELS.get(key, key), "default": _FACTOR_DEFAULTS[key]}
            for key in _FACTOR_DEFAULTS
        ],
        "levels": [
            {"value": level, "label": LEVEL_LABELS.get(level, level)} for level in LEVEL_LABELS
        ],
        "zone_types": [
            {"value": key, "label": label} for key, label in ZONE_TYPE_LABELS.items()
        ],
        "threat_types": [
            {"value": key, "label": label} for key, label in THREAT_TYPE_LABELS.items()
        ],
        "languages": [
            {"code": "en", "label": "English", "voice": "en-US"},
            {"code": "ar", "label": "العربية", "voice": "ar-SA"},
        ],
        "permissions": PERMISSIONS,
        "roles": [
            {
                "name": name,
                "label": str(definition["label"]),
                "description": str(definition["description"]),
                "permissions": list(definition["permissions"]),
            }
            for name, definition in ROLE_DEFINITIONS.items()
        ],
        "voice_template_count": len(VOICE_TEMPLATES),
        "environment": {
            "app_version": env_settings.app_version,
            "environment": env_settings.environment,
            "demo_mode": env_settings.demo_mode,
            "recording_enabled": env_settings.recording_enabled,
            "face_recognition_enabled": env_settings.face_recognition_enabled,
            "pipeline_enabled": env_settings.pipeline_enabled,
        },
    }


@router.get("")
def read_settings(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return {
        "settings": app_settings.get_settings(db),
        "defaults": app_settings.DEFAULT_SETTINGS,
        "metadata": _metadata(),
    }


@router.get("/risk")
def risk_config(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    settings = app_settings.get_settings(db)
    return {
        "weights": settings["risk_weights"],
        "thresholds": settings["risk_thresholds"],
        "verification": settings["verification"],
        "factors": _metadata()["risk_factors"],
    }


@router.post("/risk/preview")
def preview_risk(
    payload: RiskPreviewRequest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    config = app_settings.get_settings(db)
    result = evaluate_risk(
        RiskFactors(**payload.model_dump()),
        config["risk_weights"],
        config["risk_thresholds"],
    )
    return {
        "score": result.score,
        "level": result.level,
        "level_label": LEVEL_LABELS.get(result.level, result.level),
        "explanation": result.explanation,
        "breakdown": result.breakdown,
        "contributions": result.contributions,
        "factors": factor_table(result, config["risk_weights"]),
    }


@router.put("")
def update_settings(
    request: Request,
    values: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_settings")),
):
    unknown = [key for key in values if key not in app_settings.DEFAULT_SETTINGS]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Unknown settings group(s): {', '.join(unknown)}")
    normalized = {key: _normalize(key, value) for key, value in values.items()}
    updated = app_settings.update_settings(db, normalized)
    record_audit(
        db,
        actor,
        "settings.update",
        target=", ".join(sorted(normalized.keys())),
        detail="Settings updated from the control center",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    return {"settings": updated, "message": "Settings saved"}


@router.patch("/{key}")
def update_setting_group(
    key: str,
    payload: SettingsUpdate,
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_settings")),
):
    if key not in app_settings.DEFAULT_SETTINGS:
        raise HTTPException(status_code=404, detail="Unknown settings group")
    normalized = _normalize(key, payload.value)
    updated = app_settings.set_setting(db, key, normalized)
    record_audit(
        db,
        actor,
        "settings.update",
        target=key,
        detail="Settings group updated",
        ip_address=client_ip(request),
        commit=False,
    )
    db.commit()
    return {"key": key, "value": updated}


@router.post("/retention/run")
def run_retention(
    request: Request,
    db: Session = Depends(get_db),
    actor: User = Depends(require_permissions("manage_settings")),
):
    config = app_settings.get_settings(db)
    days = int(config["recording"].get("retention_days", env_settings.retention_days))
    result = storage.purge_expired_recordings(db, retention_days=days)
    record_audit(
        db,
        actor,
        "storage.retention",
        target="recordings",
        detail=f"Deleted {result['deleted']} recording(s), freed {result['freed_bytes']} bytes",
        ip_address=client_ip(request),
    )
    return {
        "message": f"Retention cleanup finished · {result['deleted']} file(s) removed",
        "retention_days": days,
        **result,
    }


__all__ = ["router"]
