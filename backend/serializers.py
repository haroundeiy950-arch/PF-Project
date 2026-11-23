"""Serializers shared by routers and services."""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.models import AuditLog, AuthorizedPerson, Camera, Role, SystemHealth, User
from backend.services import storage
from backend.utils.time_utils import iso


def role_payload(role: Role) -> Dict[str, Any]:
    return {
        "id": role.id,
        "name": role.name,
        "label": role.label,
        "description": role.description,
        "permissions": list(role.permissions or []),
    }


def user_payload(user: User) -> Dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "full_name": user.full_name,
        "email": user.email,
        "is_active": user.is_active,
        "role": role_payload(user.role),
        "last_login_at": iso(user.last_login_at),
        "created_at": iso(user.created_at),
        "updated_at": iso(user.updated_at),
    }


def camera_payload(
    camera: Camera,
    runtime: Optional[Dict[str, Any]] = None,
    zones_count: int = 0,
    active_threats: int = 0,
) -> Dict[str, Any]:
    payload = {
        "id": camera.id,
        "name": camera.name,
        "code": camera.code,
        "location": camera.location,
        "rtsp_url": camera.rtsp_url,
        "source_type": camera.source_type,
        "status": camera.status,
        "is_enabled": camera.is_enabled,
        "fps": camera.fps,
        "resolution": camera.resolution,
        "last_seen_at": iso(camera.last_seen_at),
        "notes": camera.notes,
        "zones_count": zones_count,
        "active_threats": active_threats,
        "stream_url": f"/api/cameras/{camera.id}/stream",
        "snapshot_url": f"/api/cameras/{camera.id}/snapshot",
    }
    if runtime:
        payload.update(
            {
                "status": runtime.get("status", camera.status),
                "runtime_fps": runtime.get("fps", 0.0),
                "runtime_frames": runtime.get("frames", 0),
                "threat_level": runtime.get("threat_level", "normal"),
                "risk_score": runtime.get("risk_score", 0),
                "last_frame_at": runtime.get("last_frame_at"),
            }
        )
    return payload


def person_payload(person: AuthorizedPerson) -> Dict[str, Any]:
    return {
        "id": person.id,
        "full_name": person.full_name,
        "title": person.title,
        "consent_given": person.consent_given,
        "consent_at": iso(person.consent_at),
        "photo_url": storage.media_url(person.photo_path),
        "is_active": person.is_active,
        "notes": person.notes,
        "has_embedding": bool(person.embedding_encrypted),
        "created_at": iso(person.created_at),
    }


def audit_payload(entry: AuditLog) -> Dict[str, Any]:
    return {
        "id": entry.id,
        "user_id": entry.user_id,
        "username": entry.user.username if entry.user else "system",
        "action": entry.action,
        "target": entry.target,
        "detail": entry.detail,
        "ip_address": entry.ip_address,
        "created_at": iso(entry.created_at),
    }


def health_payload(row: SystemHealth) -> Dict[str, Any]:
    return {
        "id": row.id,
        "camera_id": row.camera_id,
        "cpu_percent": row.cpu_percent,
        "memory_percent": row.memory_percent,
        "disk_percent": row.disk_percent,
        "storage_gb": row.storage_gb,
        "status": row.status,
        "detail": row.detail,
        "recorded_at": iso(row.recorded_at),
    }


__all__ = [
    "role_payload",
    "user_payload",
    "camera_payload",
    "person_payload",
    "audit_payload",
    "health_payload",
]
