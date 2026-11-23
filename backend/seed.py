"""First-run database seeding.

Creates the three built-in roles, three demo users, four demo cameras with
zones, authorized personnel records and 24 hours of realistic incidents so the
dashboard, analytics, playback and audit screens are never empty.
"""

from __future__ import annotations

import random
import time
from datetime import timedelta
from typing import Dict, List, Optional, Tuple

import cv2 # type: ignore
import numpy as np
from sqlalchemy import select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.ai.demo import DemoScene
from backend.ai.discovery import preferred_camera_index, probe_webcams
from backend.ai.recorder import Recorder
from backend.config import settings
from backend.constants import (
    LEVEL_LABELS,
    ROLE_DEFINITIONS,
    THREAT_TYPE_LABELS,
    VOICE_TEMPLATES,
)
from backend.models import (
    Acknowledgement,
    Alert,
    AuditLog,
    AuthorizedPerson,
    Camera,
    Event,
    Incident,
    Recording,
    Role,
    SystemHealth,
    User,
    Zone,
)
from backend.security import hash_password
from backend.services import storage
from backend.services import app_settings, imaging
from backend.services.risk import RiskFactors, evaluate_risk
from backend.services.voice import build_voice_messages, incident_title
from backend.utils.logging import get_logger
from backend.utils.time_utils import now

log = get_logger("seed")
RNG = random.Random(20261116)

DEMO_USERS = [
    ("admin", "admin123", "admin", "Haroun Salem", "haroun@sentinel.local"),
    ("operator", "operator123", "operator", "Layla Nasser", "layla@sentinel.local"),
    ("viewer", "viewer123", "viewer", "Guest Observer", "viewer@sentinel.local"),
]

CAMERA_SEEDS = [
    {
        "name": "Main Entrance Gate",
        "code": "CAM-01",
        "location": "North Gate · Entrance",
        "zones": [
            ("Gate Access", "restricted", [[0.36, 0.34], [0.66, 0.34], [0.66, 0.98], [0.36, 0.98]], "#ef4444"),
            ("Approach Road", "public", [[0.0, 0.56], [1.0, 0.56], [1.0, 1.0], [0.0, 1.0]], "#22d3ee"),
        ],
    },
    {
        "name": "North Perimeter",
        "code": "CAM-02",
        "location": "Perimeter · Fence line B",
        "zones": [
            ("Fence Breach Zone", "restricted", [[0.22, 0.36], [0.78, 0.36], [0.78, 0.94], [0.22, 0.94]], "#ef4444"),
            ("Outer Yard", "limited", [[0.0, 0.6], [1.0, 0.6], [1.0, 1.0], [0.0, 1.0]], "#f59e0b"),
        ],
    },
    {
        "name": "Staff Parking Lot",
        "code": "CAM-03",
        "location": "West Wing · Parking",
        "zones": [
            ("Staff Bays", "limited", [[0.34, 0.52], [0.78, 0.52], [0.78, 1.0], [0.34, 1.0]], "#f59e0b"),
            ("Parking Lot", "public", [[0.0, 0.55], [1.0, 0.55], [1.0, 1.0], [0.0, 1.0]], "#22d3ee"),
        ],
    },
    {
        "name": "Vault Access Corridor",
        "code": "CAM-04",
        "location": "Secure Wing · Level B2",
        "zones": [
            ("Vault Door", "restricted", [[0.34, 0.28], [0.66, 0.28], [0.66, 0.98], [0.34, 0.98]], "#ef4444"),
            ("Corridor", "public", [[0.0, 0.45], [1.0, 0.45], [1.0, 1.0], [0.0, 1.0]], "#22d3ee"),
        ],
    },
]

AUTHORIZED = [
    ("Haroun Salem", "Security Director", True),
    ("Layla Nasser", "Control Room Operator", True),
]

THREAT_BY_LEVEL = {
    "critical": ["restricted_intrusion", "vehicle_intrusion", "abnormal_activity"],
    "high": ["restricted_intrusion", "loitering", "abnormal_activity"],
    "medium": ["loitering", "unknown_face", "vehicle_intrusion", "abnormal_activity"],
}


# ---------------------------------------------------------------------------
def _ensure_roles(db: Session) -> Dict[str, Role]:
    roles: Dict[str, Role] = {}
    for name, definition in ROLE_DEFINITIONS.items():
        role = db.scalar(select(Role).where(Role.name == name))
        if role is None:
            role = Role(
                name=name,
                label=str(definition["label"]),
                description=str(definition["description"]),
                permissions=list(definition["permissions"]),
            )
            db.add(role)
        else:
            role.label = str(definition["label"])
            role.description = str(definition["description"])
            role.permissions = list(definition["permissions"])
        roles[name] = role
    db.flush()
    return roles


def _ensure_users(db: Session, roles: Dict[str, Role]) -> Dict[str, User]:
    users: Dict[str, User] = {}
    for username, password, role_name, full_name, email in DEMO_USERS:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            user = User(
                username=username,
                full_name=full_name,
                email=email,
                password_hash=hash_password(password),
                role_id=roles[role_name].id,
                is_active=True,
                last_login_at=now() - timedelta(minutes=RNG.randint(5, 120)),
            )
            db.add(user)
        users[username] = user
    db.flush()
    return users


def _ensure_cameras(db: Session) -> List[Camera]:
    cameras: List[Camera] = []
    for index, spec in enumerate(CAMERA_SEEDS, start=1):
        camera = db.scalar(select(Camera).where(Camera.code == spec["code"]))
        if camera is None:
            camera = Camera(
                name=str(spec["name"]),
                code=str(spec["code"]),
                location=str(spec["location"]),
                rtsp_url="",
                source_type="demo",
                status="starting",
                is_enabled=True,
                fps=settings.target_fps,
                resolution=f"{settings.frame_width}x{settings.frame_height}",
                notes="Synthetic demo feed. Replace with an RTSP URL for a real camera.",
            )
            db.add(camera)
            db.flush()
        cameras.append(camera)

        existing = {zone.name for zone in camera.zones}
        for name, zone_type, points, color in spec["zones"]:
            if name in existing:
                continue
            db.add(
                Zone(
                    camera_id=camera.id,
                    name=name,
                    zone_type=zone_type,
                    points=points,
                    schedule_start="00:00",
                    schedule_end="23:59",
                    days=[0, 1, 2, 3, 4, 5, 6],
                    min_dwell_seconds=2.0,
                    min_frames=6,
                    cooldown_seconds=45,
                    is_enabled=True,
                    color=color,
                )
            )
    db.flush()
    return cameras


# ---------------------------------------------------------------------------
def _synthetic_avatar(name: str, path) -> str:
    initials = "".join(part[0] for part in name.split()[:2]).upper()
    canvas = np.zeros((320, 320, 3), dtype=np.uint8)
    canvas[:] = (26, 32, 40)
    for index in range(0, 320, 32):
        cv2.line(canvas, (index, 0), (index, 320), (30, 38, 48), 1)
        cv2.line(canvas, (0, index), (320, index), (30, 38, 48), 1)
    cv2.circle(canvas, (160, 128), 56, (52, 62, 72), -1, cv2.LINE_AA)
    cv2.ellipse(canvas, (160, 260), (94, 80), 0, 180, 360, (52, 62, 72), -1)
    (tw, th), _ = cv2.getTextSize(initials, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)
    cv2.putText(canvas, initials, (160 - tw // 2, 148), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (120, 200, 210), 2, cv2.LINE_AA)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), canvas)
    return str(path.relative_to(settings.storage_dir)).replace("\\", "/")


def _ensure_persons(db: Session) -> List[AuthorizedPerson]:
    persons: List[AuthorizedPerson] = []
    for index, (name, title, consent) in enumerate(AUTHORIZED, start=1):
        person = db.scalar(select(AuthorizedPerson).where(AuthorizedPerson.full_name == name))
        if person is None:
            photo_path = _synthetic_avatar(name, settings.faces_dir / f"person_{index}.jpg")
            person = AuthorizedPerson(
                full_name=name,
                title=title,
                consent_given=consent,
                consent_at=now() - timedelta(days=30),
                photo_path=photo_path,
                is_active=True,
                notes="Enrolled with written consent. Embedding encrypted at rest.",
            )
            db.add(person)
        persons.append(person)
    db.flush()
    return persons


# ---------------------------------------------------------------------------
def _level_factors(level: str) -> RiskFactors:
    if level == "critical":
        return RiskFactors(
            zone_type="restricted",
            target_type="person",
            hour=2,
            dwell_seconds=12,
            dwell_target=2,
            face_status="unknown",
            repetition=3,
            behavior="running",
        )
    if level == "high":
        return RiskFactors(
            zone_type="restricted",
            target_type="person",
            hour=20,
            dwell_seconds=6,
            dwell_target=10,
            face_status="unknown",
            repetition=2,
            behavior="loitering",
        )
    return RiskFactors(
        zone_type="limited",
        target_type="person",
        hour=14,
        dwell_seconds=4,
        dwell_target=10,
        face_status="unknown",
        repetition=1,
        behavior="approaching",
    )


def _snapshot(
    scene: DemoScene,
    camera: Camera,
    level: str,
    threat_type: str,
    code: str,
    zones_list,
) -> str:
    elapsed = RNG.uniform(0, scene.cycle)
    frame = scene.render(elapsed)
    objects = scene.objects(elapsed)
    for zone in zones_list:
        imaging.draw_zone(frame, zone.points, f"{zone.name} · {zone.zone_type}", zone.zone_type, zone.color)
    for index, obj in enumerate(objects):
        box = obj.bbox()
        imaging.draw_detection(
            frame,
            box,
            f"{obj.kind.upper()} · {int(obj.confidence * 100)}%",
            imaging.RED if index == 0 and level in {"high", "critical"} else imaging.CYAN,
            thickness=3 if index == 0 else 2,
        )
    imaging.draw_header(frame, camera.name, camera.code, camera.location, level, None)
    if level in {"high", "critical"}:
        imaging.draw_danger_overlay(
            frame,
            "DANGER" if level == "critical" else "ALERT",
            THREAT_TYPE_LABELS.get(threat_type, threat_type),
            level,
        )
    return imaging.save_snapshot(frame, code)


def _clip(
    scene: DemoScene,
    recorder: Recorder,
    code: str,
) -> Tuple[str, float]:
    start = RNG.uniform(0, scene.cycle)
    fps = 8
    frames = []
    for index in range(16):
        frame = scene.render((start + index / fps) % scene.cycle)
        frames.append(frame)
    path, duration = recorder._encode(code, frames, frames[0].shape[1], frames[0].shape[0])
    return path, duration


def _seed_history(db: Session, cameras: List[Camera], operator: User) -> Dict[str, int]:
    scenes = {camera.id: DemoScene(camera.id, camera.code) for camera in cameras}
    recorders = {camera.id: Recorder(camera.id, fps=8) for camera in cameras}
    zones_by_camera = {
        camera.id: db.scalars(
            select(Zone).where(Zone.camera_id == camera.id).order_by(Zone.id)
        ).all()
        for camera in cameras
    }
    counts = {"incidents": 0, "events": 0, "recordings": 0}
    now_value = now()

    # 26 incidents spread across 24 hours, newest first for the active threat.
    plan: List[Tuple[int, str, int, str]] = []
    for minutes_ago in (3, 37, 96, 180, 240, 310, 420, 520, 640, 780):
        plan.append((minutes_ago, "critical" if minutes_ago < 300 else "medium", RNG.randint(0, 3), "open" if minutes_ago == 3 else "acknowledged"))
    for index in range(8):
        plan.append((RNG.randint(60, 1400), "high", RNG.randint(0, 3), RNG.choice(["acknowledged", "resolved", "resolved"])))
    for index in range(12):
        plan.append((RNG.randint(60, 1430), "medium", RNG.randint(0, 3), RNG.choice(["resolved", "resolved", "false_alarm", "acknowledged"])))

    for sequence, (minutes_ago, level, camera_index, status) in enumerate(plan):
        camera = cameras[camera_index]
        zones = zones_by_camera[camera.id]
        zone = next((item for item in zones if item.zone_type == ("restricted" if level in {"high", "critical"} else "limited")), zones[0])
        detected_at = now_value - timedelta(minutes=minutes_ago, seconds=RNG.randint(0, 59))
        threat_type = RNG.choice(THREAT_BY_LEVEL[level])
        risk = evaluate_risk(_level_factors(level))
        code = f"INC-{detected_at.strftime('%Y%m%d')}-{sequence + 1:04d}"
        while db.scalar(select(Incident).where(Incident.code == code)):
            code = f"INC-{detected_at.strftime('%Y%m%d')}-{sequence + 100:04d}"

        snapshot_rel = _snapshot(scenes[camera.id], camera, level, threat_type, code, zones)
        incident = Incident(
            code=code,
            camera_id=camera.id,
            zone_id=zone.id,
            incident_type=threat_type,
            title=incident_title(threat_type, camera.name),
            risk_score=risk.score,
            level=risk.level,
            status=status,
            explanation=risk.explanation,
            factors={
                "contributions": risk.contributions,
                "breakdown": risk.breakdown,
                "dwell_seconds": round(RNG.uniform(3, 14), 1),
                "behavior": "running" if level == "critical" else "loitering",
                "frames_seen": RNG.randint(18, 90),
            },
            target_type="vehicle" if threat_type == "vehicle_intrusion" else "person",
            track_id=f"T-{RNG.randint(1000, 9999)}",
            face_status="known" if threat_type not in {"unknown_face", "restricted_intrusion", "loitering", "abnormal_activity"} else "unknown",
            detected_at=detected_at,
            acknowledged_at=detected_at + timedelta(minutes=RNG.randint(1, 8)) if status in {"acknowledged", "resolved"} else None,
            acknowledged_by_id=operator.id if status in {"acknowledged", "resolved"} else None,
            resolved_at=detected_at + timedelta(minutes=RNG.randint(9, 40)) if status in {"resolved", "false_alarm"} else None,
            snapshot_path=snapshot_rel,
            meta={"seeded": True, "behavior": "running" if level == "critical" else "loitering"},
        )
        db.add(incident)
        db.flush()

        db.add(
            Recording(
                incident_id=incident.id,
                camera_id=camera.id,
                kind="snapshot",
                path=snapshot_rel,
                started_at=detected_at,
                ended_at=detected_at,
                duration_seconds=0.0,
                size_bytes=storage.file_size(snapshot_rel),
                created_at=detected_at,
                updated_at=detected_at,
            )
        )
        counts["recordings"] += 1

        # Generate a real playable clip for a representative subset.
        if sequence < 8:
            try:
                clip_path, duration = _clip(scenes[camera.id], recorders[camera.id], code)
                incident.clip_path = clip_path
                db.add(
                    Recording(
                        incident_id=incident.id,
                        camera_id=camera.id,
                        kind="clip",
                        path=clip_path,
                        started_at=detected_at,
                        ended_at=detected_at + timedelta(seconds=duration),
                        duration_seconds=duration,
                        size_bytes=storage.file_size(clip_path),
                        created_at=detected_at,
                        updated_at=detected_at,
                    )
                )
                counts["recordings"] += 1
            except Exception as exc:  # pragma: no cover - codec dependent
                log.warning("Seed clip failed: %s", exc)

        for message in build_voice_messages(threat_type, camera.name, camera.code):
            if status == "open":
                alert_status = "not_started"
            elif status == "acknowledged":
                alert_status = "acknowledged"
            else:
                alert_status = "stopped"
            db.add(
                Alert(
                    incident_id=incident.id,
                    channel="voice",
                    language=message["language"],
                    message=message["text"],
                    status=alert_status,
                    played_at=detected_at if alert_status != "not_started" else None,
                    acknowledged_at=detected_at + timedelta(minutes=2) if alert_status == "acknowledged" else None,
                    detail="Bilingual warning stored with incident",
                )
            )
        db.add(
            Alert(
                incident_id=incident.id,
                channel="notification",
                language="en",
                message=f"{incident.title}. {risk.explanation}",
                status="sent",
                sent_to="local-console",
                detail="Sent to administrator / remote monitoring center",
            )
        )
        if level == "critical":
            db.add(
                Alert(
                    incident_id=incident.id,
                    channel="siren",
                    language="en",
                    message="Local siren triggered",
                    status="playing" if status == "open" else "stopped",
                    sent_to="local-siren",
                )
            )

        if status in {"acknowledged", "resolved"}:
            db.add(
                Acknowledgement(
                    incident_id=incident.id,
                    alert_id=None,
                    user_id=operator.id,
                    note=RNG.choice(["Verified on site.", "Guard dispatched.", "Checked camera and cleared area."]),
                    acknowledged_at=incident.acknowledged_at or (detected_at + timedelta(minutes=2)),
                    created_at=incident.acknowledged_at or (detected_at + timedelta(minutes=2)),
                    updated_at=incident.acknowledged_at or (detected_at + timedelta(minutes=2)),
                )
            )

        for event_index in range(RNG.randint(2, 4)):
            bbox = [round(RNG.uniform(0.2, 0.7), 3), round(RNG.uniform(0.3, 0.55), 3), 0.08, 0.32]
            db.add(
                Event(
                    camera_id=camera.id,
                    zone_id=zone.id,
                    incident_id=incident.id,
                    event_type=threat_type,
                    target_type=incident.target_type,
                    confidence=round(RNG.uniform(0.78, 0.99), 3),
                    bbox=bbox,
                    track_id=f"T-{RNG.randint(1000, 9999)}",
                    is_threat=True,
                    snapshot_path=snapshot_rel,
                    meta={"seeded": True, "risk_score": risk.score, "level": risk.level},
                    occurred_at=detected_at + timedelta(seconds=event_index * 3),
                    created_at=detected_at,
                    updated_at=detected_at,
                )
            )
            counts["events"] += 1
        counts["incidents"] += 1

    # Normal activity events for the KPI cards.
    for index in range(46):
        camera = RNG.choice(cameras)
        minutes_ago = RNG.randint(0, 240)
        occurred = now_value - timedelta(minutes=minutes_ago, seconds=RNG.randint(0, 59))
        target = RNG.choice(["person", "vehicle", "person", "person"])
        db.add(
            Event(
                camera_id=camera.id,
                event_type=target,
                target_type=target,
                confidence=round(RNG.uniform(0.7, 0.99), 3),
                bbox=[round(RNG.uniform(0.1, 0.8), 3), round(RNG.uniform(0.4, 0.7), 3), 0.09, 0.3],
                track_id=f"T-{RNG.randint(1000, 9999)}",
                is_threat=False,
                meta={"seeded": True, "face_status": RNG.choice(["known", "unknown", "none"])},
                occurred_at=occurred,
                created_at=occurred,
                updated_at=occurred,
            )
        )
        counts["events"] += 1

    # System health history for the last 24 hours.
    for hours_ago in range(24, -1, -1):
        stamp = now_value - timedelta(hours=hours_ago)
        db.add(
            SystemHealth(
                cpu_percent=round(RNG.uniform(22, 54), 1),
                memory_percent=round(RNG.uniform(38, 66), 1),
                disk_percent=round(RNG.uniform(41, 58), 1),
                storage_gb=round(RNG.uniform(2.1, 3.6), 2),
                status="healthy",
                detail="4/4 cameras online",
                recorded_at=stamp,
                created_at=stamp,
                updated_at=stamp,
            )
        )

    # Audit trail samples.
    actions = [
        ("auth.login", "session", "Successful login"),
        ("incident.acknowledge", "incident", "Operator acknowledged alarm"),
        ("camera.update", "camera", "Updated camera notes"),
        ("settings.update", "settings", "Risk weights reviewed"),
        ("export.csv", "reports", "Exported incident report"),
    ]
    for index, (action, target, detail) in enumerate(actions):
        stamp = now_value - timedelta(hours=RNG.randint(1, 40))
        db.add(
            AuditLog(
                user_id=operator.id if index % 2 else None,
                action=action,
                target=target,
                detail=detail,
                ip_address="127.0.0.1",
                created_at=stamp,
                updated_at=stamp,
            )
        )
    db.flush()
    return counts


# ---------------------------------------------------------------------------
def ensure_live_camera(db: Session) -> Camera:
    """Register the physical camera and remove demo cameras from the live view.

    Only the login accounts and one real camera are created.  No incidents,
    events, snapshots or clips are generated in this mode.
    """
    roles = _ensure_roles(db)
    _ensure_users(db, roles)
    cameras = list(db.scalars(select(Camera).order_by(Camera.id)).all())
    primary = cameras[0] if cameras else None

    # Pick the device that actually delivers an image at startup so the feed
    # opens directly, without an operator having to choose one by hand.
    raw_index = str(getattr(primary, "rtsp_url", "") or "").strip() if primary else ""
    configured = int(raw_index) if raw_index.isdigit() else settings.live_camera_index
    devices = probe_webcams()
    current = next((item for item in devices if item.index == configured and item.has_signal), None)
    index = configured if current is not None else preferred_camera_index(devices)
    if index is None:
        index = configured
    log.info("Live camera startup device: %s (configured %s)", index, configured)

    if primary is None:
        primary = Camera(
            name=settings.live_camera_name,
            code="CAM-01",
            location="Direct camera feed",
            source_type="webcam",
            rtsp_url=str(index),
            status="starting",
            is_enabled=True,
            fps=settings.live_camera_fps,
            resolution=f"{settings.frame_width}x{settings.frame_height}",
            notes="Live physical camera. Continuous video and event evidence are saved to disk.",
        )
        db.add(primary)
    else:
        primary.name = settings.live_camera_name
        primary.location = "Direct camera feed"
        primary.source_type = "webcam"
        primary.rtsp_url = str(index)
        primary.is_enabled = True
        primary.fps = settings.live_camera_fps
        primary.resolution = f"{settings.frame_width}x{settings.frame_height}"
        primary.notes = "Live physical camera. Continuous video and event evidence are saved to disk."
    # The camera needs its primary key before the zone can reference it.
    db.flush()
    # A default monitoring zone lets the detector turn real motion into
    # verified incidents, which is what triggers snapshot/clip saving.
    existing_zone = db.scalar(select(Zone).where(Zone.camera_id == primary.id))
    if existing_zone is None:
        db.add(
            Zone(
                camera_id=primary.id,
                name="Live View",
                zone_type="limited",
                points=[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
                schedule_start="00:00",
                schedule_end="23:59",
                days=[0, 1, 2, 3, 4, 5, 6],
                min_dwell_seconds=2.0,
                min_frames=6,
                cooldown_seconds=45,
                is_enabled=True,
                color="#22d3ee",
            )
        )
    for extra in cameras[1:]:
        extra.is_enabled = False
    db.flush()
    return primary


def seed_database(db: Session) -> Dict[str, object]:
    """Populate an empty database.  Returns a summary dictionary."""
    users_existing = db.scalar(select(User).limit(1))
    if users_existing is not None:
        return {"seeded": False, "reason": "database already contains users"}

    roles = _ensure_roles(db)
    users = _ensure_users(db, roles)
    cameras = _ensure_cameras(db)
    _ensure_persons(db)
    for key, value in app_settings.DEFAULT_SETTINGS.items():
        app_settings.set_setting(db, key, value)

    counts = _seed_history(db, cameras, users["operator"])
    db.commit()
    log.info(
        "Seeded database: %d cameras, %d incidents, %d events, %d recordings",
        len(cameras),
        counts["incidents"],
        counts["events"],
        counts["recordings"],
    )
    return {"seeded": True, "users": 3, "cameras": len(cameras), **counts}


def seed_if_needed(db: Session) -> Dict[str, object]:
    if settings.live_only:
        camera = ensure_live_camera(db)
        db.commit()
        return {
            "seeded": True,
            "mode": "live",
            "cameras": 1,
            "camera_id": camera.id,
            "evidence_written": settings.evidence_enabled and settings.recording_enabled,
        }
    if not settings.seed_demo_data:
        return {"seeded": False, "reason": "SEED_DEMO_DATA disabled"}
    return seed_database(db)


__all__ = ["seed_database", "seed_if_needed", "ensure_live_camera", "DEMO_USERS"]
