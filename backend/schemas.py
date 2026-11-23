"""Pydantic request/response schemas for the Sentinel AI API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.constants import INCIDENT_STATUSES, LEVELS, ZONE_TYPES
from backend.utils.geometry import normalize_points


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Auth & users
# ---------------------------------------------------------------------------
class LoginRequest(BaseModel):
    username: str = Field(min_length=2, max_length=60)
    password: str = Field(min_length=4, max_length=200)


class RoleOut(ORMModel):
    id: int
    name: str
    label: str
    description: str
    permissions: List[str] = []


class UserOut(ORMModel):
    id: int
    username: str
    full_name: str
    email: str
    is_active: bool
    role: RoleOut
    last_login_at: Optional[datetime] = None
    created_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=60)
    full_name: str = Field(default="", max_length=120)
    email: str = Field(default="", max_length=160)
    password: str = Field(min_length=6, max_length=200)
    role: str = "viewer"
    is_active: bool = True


class UserUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    email: Optional[str] = Field(default=None, max_length=160)
    password: Optional[str] = Field(default=None, min_length=6, max_length=200)
    role: Optional[str] = None
    is_active: Optional[bool] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


# ---------------------------------------------------------------------------
# Cameras & zones
# ---------------------------------------------------------------------------
class CameraOut(ORMModel):
    id: int
    name: str
    code: str
    location: str
    rtsp_url: str
    source_type: str
    status: str
    is_enabled: bool
    fps: int
    resolution: str
    last_seen_at: Optional[datetime] = None
    notes: str = ""
    stream_url: Optional[str] = None
    zones_count: int = 0
    active_threats: int = 0


class CameraCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: Optional[str] = Field(default=None, max_length=20)
    location: str = Field(default="", max_length=160)
    rtsp_url: str = Field(default="", max_length=500)
    source_type: str = Field(default="demo", pattern="^(demo|rtsp|file|webcam)$")
    fps: int = Field(default=8, ge=1, le=30)
    resolution: str = "960x540"
    notes: str = ""
    is_enabled: bool = True


class CameraUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    code: Optional[str] = Field(default=None, max_length=20)
    location: Optional[str] = Field(default=None, max_length=160)
    rtsp_url: Optional[str] = Field(default=None, max_length=500)
    source_type: Optional[str] = Field(default=None, pattern="^(demo|rtsp|file|webcam)$")
    fps: Optional[int] = Field(default=None, ge=1, le=30)
    resolution: Optional[str] = None
    notes: Optional[str] = None
    is_enabled: Optional[bool] = None


class LiveDeviceSelect(BaseModel):
    index: int = Field(ge=0, le=20)


class ZoneOut(ORMModel):
    id: int
    camera_id: int
    name: str
    zone_type: str
    points: List[List[float]]
    schedule_start: str
    schedule_end: str
    days: List[int]
    min_dwell_seconds: float
    min_frames: int
    cooldown_seconds: int
    is_enabled: bool
    color: str


class ZoneCreate(BaseModel):
    camera_id: int
    name: str = Field(min_length=2, max_length=120)
    zone_type: str = "public"
    points: List[List[float]] = Field(default_factory=list)
    schedule_start: str = Field(default="00:00", pattern=r"^\d{2}:\d{2}$")
    schedule_end: str = Field(default="23:59", pattern=r"^\d{2}:\d{2}$")
    days: List[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6])
    min_dwell_seconds: float = Field(default=2.0, ge=0, le=120)
    min_frames: int = Field(default=6, ge=1, le=120)
    cooldown_seconds: int = Field(default=90, ge=0, le=3600)
    is_enabled: bool = True
    color: str = "#22d3ee"

    @field_validator("zone_type")
    @classmethod
    def _valid_type(cls, value: str) -> str:
        if value not in ZONE_TYPES:
            raise ValueError(f"zone_type must be one of {ZONE_TYPES}")
        return value

    @field_validator("points")
    @classmethod
    def _valid_points(cls, value: List[List[float]]) -> List[List[float]]:
        points = normalize_points(value)
        if points and len(points) < 3:
            raise ValueError("A zone polygon needs at least 3 points")
        return points

    @field_validator("days")
    @classmethod
    def _valid_days(cls, value: List[int]) -> List[int]:
        return sorted({int(day) for day in value if 0 <= int(day) <= 6})


class ZoneUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    zone_type: Optional[str] = None
    points: Optional[List[List[float]]] = None
    schedule_start: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    schedule_end: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    days: Optional[List[int]] = None
    min_dwell_seconds: Optional[float] = Field(default=None, ge=0, le=120)
    min_frames: Optional[int] = Field(default=None, ge=1, le=120)
    cooldown_seconds: Optional[int] = Field(default=None, ge=0, le=3600)
    is_enabled: Optional[bool] = None
    color: Optional[str] = None

    @field_validator("zone_type")
    @classmethod
    def _valid_type(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in ZONE_TYPES:
            raise ValueError(f"zone_type must be one of {ZONE_TYPES}")
        return value

    @field_validator("points")
    @classmethod
    def _valid_points(cls, value: Optional[List[List[float]]]) -> Optional[List[List[float]]]:
        if value is None:
            return None
        points = normalize_points(value)
        if points and len(points) < 3:
            raise ValueError("A zone polygon needs at least 3 points")
        return points


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
class PersonOut(ORMModel):
    id: int
    full_name: str
    title: str
    consent_given: bool
    consent_at: Optional[datetime] = None
    photo_url: Optional[str] = None
    is_active: bool
    notes: str = ""
    has_embedding: bool = False


class PersonUpdate(BaseModel):
    full_name: Optional[str] = Field(default=None, max_length=120)
    title: Optional[str] = Field(default=None, max_length=120)
    consent_given: Optional[bool] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Events, incidents, alerts and evidence
# ---------------------------------------------------------------------------
class EventOut(ORMModel):
    id: int
    camera_id: int
    zone_id: Optional[int] = None
    incident_id: Optional[int] = None
    event_type: str
    target_type: str
    confidence: float
    bbox: List[float] = []
    track_id: str
    is_threat: bool
    snapshot_url: Optional[str] = None
    meta: Dict[str, Any] = {}
    occurred_at: datetime
    camera_name: Optional[str] = None
    zone_name: Optional[str] = None


class AlertOut(ORMModel):
    id: int
    incident_id: int
    channel: str
    language: str
    message: str
    status: str
    sent_to: str
    played_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    created_at: datetime


class RecordingOut(ORMModel):
    id: int
    incident_id: Optional[int] = None
    camera_id: int
    kind: str
    url: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: float
    size_bytes: int
    created_at: datetime


class AcknowledgementOut(ORMModel):
    id: int
    incident_id: int
    user_id: int
    user_name: Optional[str] = None
    note: str
    acknowledged_at: datetime


class IncidentOut(ORMModel):
    id: int
    code: str
    camera_id: int
    zone_id: Optional[int] = None
    incident_type: str
    title: str
    risk_score: int
    level: str
    status: str
    explanation: str
    factors: Dict[str, Any] = {}
    target_type: str
    face_status: str
    detected_at: datetime
    acknowledged_at: Optional[datetime] = None
    acknowledged_by_id: Optional[int] = None
    resolved_at: Optional[datetime] = None
    snapshot_url: Optional[str] = None
    clip_url: Optional[str] = None
    camera_name: Optional[str] = None
    camera_code: Optional[str] = None
    camera_location: Optional[str] = None
    zone_name: Optional[str] = None
    zone_type: Optional[str] = None
    alerts: List[AlertOut] = []
    recordings: List[RecordingOut] = []
    acknowledgements: List[AcknowledgementOut] = []
    event_count: int = 0


class IncidentAction(BaseModel):
    note: str = Field(default="", max_length=400)


class IncidentStatusUpdate(BaseModel):
    status: str
    note: str = Field(default="", max_length=400)

    @field_validator("status")
    @classmethod
    def _valid_status(cls, value: str) -> str:
        if value not in INCIDENT_STATUSES:
            raise ValueError(f"status must be one of {INCIDENT_STATUSES}")
        return value


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------
class AuditOut(ORMModel):
    id: int
    user_id: Optional[int] = None
    username: Optional[str] = None
    action: str
    target: str
    detail: str
    ip_address: str
    created_at: datetime


class HealthOut(ORMModel):
    id: int
    camera_id: Optional[int] = None
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    storage_gb: float
    status: str
    detail: str
    recorded_at: datetime


class SettingOut(ORMModel):
    key: str
    value: Dict[str, Any]


class SettingsUpdate(BaseModel):
    value: Dict[str, Any]


class MessageResponse(BaseModel):
    message: str


class LevelCount(BaseModel):
    level: str
    count: int


class RiskEvaluationPreview(BaseModel):
    score: int
    level: str
    explanation: str
    breakdown: Dict[str, float]


class Page(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[Dict[str, Any]]


VALID_LEVELS = set(LEVELS)
