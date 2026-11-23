"""SQLAlchemy ORM models — mirrors Section 12 of the requirements document."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import ( # type: ignore
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship # type: ignore

from backend.database import Base
from backend.utils.time_utils import now


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now, nullable=False)


class Role(Base, TimestampMixin):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    description: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    permissions: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    users: Mapped[List["User"]] = relationship(back_populates="role")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    role: Mapped[Role] = relationship(back_populates="users")
    acknowledgements: Mapped[List["Acknowledgement"]] = relationship(back_populates="user")
    audit_logs: Mapped[List["AuditLog"]] = relationship(back_populates="user")


class Camera(Base, TimestampMixin):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    location: Mapped[str] = mapped_column(String(160), default="", nullable=False)
    rtsp_url: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), default="demo", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fps: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    resolution: Mapped[str] = mapped_column(String(20), default="960x540", nullable=False)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)

    zones: Mapped[List["Zone"]] = relationship(back_populates="camera", cascade="all, delete-orphan")
    events: Mapped[List["Event"]] = relationship(back_populates="camera")
    incidents: Mapped[List["Incident"]] = relationship(back_populates="camera")
    recordings: Mapped[List["Recording"]] = relationship(back_populates="camera")


class Zone(Base, TimestampMixin):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    zone_type: Mapped[str] = mapped_column(String(20), default="public", nullable=False)
    points: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    schedule_start: Mapped[str] = mapped_column(String(5), default="00:00", nullable=False)
    schedule_end: Mapped[str] = mapped_column(String(5), default="23:59", nullable=False)
    days: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    min_dwell_seconds: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    min_frames: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=90, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    color: Mapped[str] = mapped_column(String(20), default="#22d3ee", nullable=False)

    camera: Mapped[Camera] = relationship(back_populates="zones")
    events: Mapped[List["Event"]] = relationship(back_populates="zone")


class AuthorizedPerson(Base, TimestampMixin):
    __tablename__ = "authorized_persons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    title: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    consent_given: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    embedding_encrypted: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)
    photo_path: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), nullable=False, index=True)
    zone_id: Mapped[Optional[int]] = mapped_column(ForeignKey("zones.id"), nullable=True, index=True)
    incident_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), default="motion", nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(30), default="unknown", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    bbox: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    track_id: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    is_threat: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    snapshot_path: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    meta: Mapped[dict] = mapped_column("meta", JSON, default=dict, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False, index=True)

    camera: Mapped[Camera] = relationship(back_populates="events")
    zone: Mapped[Optional[Zone]] = relationship(back_populates="events")
    incident: Mapped[Optional["Incident"]] = relationship(back_populates="events")

    __table_args__ = (Index("ix_events_camera_time", "camera_id", "occurred_at"),)


class Incident(Base, TimestampMixin):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False, index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), nullable=False, index=True)
    zone_id: Mapped[Optional[int]] = mapped_column(ForeignKey("zones.id"), nullable=True)
    incident_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    risk_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(20), default="normal", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False, index=True)
    explanation: Mapped[str] = mapped_column(Text, default="", nullable=False)
    factors: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), default="person", nullable=False)
    track_id: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    face_status: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False, index=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    acknowledged_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    snapshot_path: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    clip_path: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    meta: Mapped[dict] = mapped_column("meta", JSON, default=dict, nullable=False)

    camera: Mapped[Camera] = relationship(back_populates="incidents")
    zone: Mapped[Optional[Zone]] = relationship("Zone")
    events: Mapped[List[Event]] = relationship(back_populates="incident")
    alerts: Mapped[List["Alert"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    recordings: Mapped[List["Recording"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )
    acknowledgements: Mapped[List["Acknowledgement"]] = relationship(
        back_populates="incident", cascade="all, delete-orphan"
    )


class Alert(Base, TimestampMixin):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(30), default="voice", nullable=False)
    language: Mapped[str] = mapped_column(String(5), default="en", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="not_started", nullable=False)
    sent_to: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    played_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    acknowledged_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="alerts")


class Recording(Base, TimestampMixin):
    __tablename__ = "recordings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("incidents.id"), nullable=True, index=True
    )
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), default="clip", nullable=False)
    path: Mapped[str] = mapped_column(String(400), nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_seconds: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    incident: Mapped[Optional[Incident]] = relationship(back_populates="recordings")
    camera: Mapped[Camera] = relationship(back_populates="recordings")


class Acknowledgement(Base, TimestampMixin):
    __tablename__ = "acknowledgements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int] = mapped_column(
        ForeignKey("incidents.id"), nullable=False, index=True
    )
    alert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("alerts.id"), nullable=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    note: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    acknowledged_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False)

    incident: Mapped[Incident] = relationship(back_populates="acknowledgements")
    user: Mapped[User] = relationship(back_populates="acknowledgements")


class AuditLog(Base, TimestampMixin):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ip_address: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False, index=True)

    user: Mapped[Optional[User]] = relationship(back_populates="audit_logs")


class SystemHealth(Base, TimestampMixin):
    __tablename__ = "system_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cameras.id"), nullable=True)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    memory_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    disk_percent: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    storage_gb: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="online", nullable=False)
    detail: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=now, nullable=False, index=True)


class AppSetting(Base, TimestampMixin):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
