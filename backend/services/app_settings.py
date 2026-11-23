"""Runtime application settings (risk weights, voice, retention...).

Settings are stored as JSON rows so an administrator can tune the system from
the Settings screen without a restart.  Defaults live in code and are merged
with the database values on read.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict

from sqlalchemy import select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.config import settings as env_settings
from backend.constants import (
    DEFAULT_RISK_WEIGHTS,
    DEFAULT_VERIFICATION,
    RISK_THRESHOLDS,
)
from backend.models import AppSetting
from backend.services.risk import clean_weights

DEFAULT_SETTINGS: Dict[str, Any] = {
    "risk_weights": deepcopy(DEFAULT_RISK_WEIGHTS),
    "risk_thresholds": deepcopy(RISK_THRESHOLDS),
    "verification": deepcopy(DEFAULT_VERIFICATION),
    "voice": {
        "enabled": env_settings.voice_enabled,
        "repeat_seconds": env_settings.voice_repeat_seconds,
        "languages": ["en", "ar"],
    },
    "alarm": {
        "siren_enabled": env_settings.siren_enabled,
        "webhook_url": env_settings.webhook_url,
        "notify_admin": True,
    },
    "recording": {
        "enabled": env_settings.recording_enabled,
        "pre_event_seconds": env_settings.pre_event_seconds,
        "post_event_seconds": env_settings.post_event_seconds,
        "retention_days": env_settings.retention_days,
    },
    "ai": {
        "detector_mode": env_settings.detector_mode,
        "face_recognition_enabled": env_settings.face_recognition_enabled,
        "target_fps": env_settings.target_fps,
        "demo_mode": env_settings.demo_mode,
    },
    "company": {
        "name": "Sentinel AI",
        "site": "Perimeter Control Center",
        "timezone": "local",
        "notice": "CCTV in operation. Authorized personnel only.",
    },
}


def _merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


def get_settings(db: Session) -> Dict[str, Any]:
    rows = db.scalars(select(AppSetting)).all()
    stored = {row.key: row.value for row in rows}
    merged = _merge(DEFAULT_SETTINGS, stored)
    merged["risk_weights"] = clean_weights(merged.get("risk_weights"))
    return merged


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    return get_settings(db).get(key, default)


def set_setting(db: Session, key: str, value: Dict[str, Any]) -> Dict[str, Any]:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value
    db.commit()
    return row.value


def update_settings(db: Session, values: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in values.items():
        if key not in DEFAULT_SETTINGS:
            continue
        set_setting(db, key, value)
    return get_settings(db)


def runtime_alarm_config(db: Session) -> Dict[str, Any]:
    config = get_settings(db)
    return {
        "risk_weights": config["risk_weights"],
        "risk_thresholds": config["risk_thresholds"],
        "verification": config["verification"],
        "voice": config["voice"],
        "recording": config["recording"],
    }


__all__ = [
    "DEFAULT_SETTINGS",
    "get_settings",
    "get_setting",
    "set_setting",
    "update_settings",
    "runtime_alarm_config",
]
