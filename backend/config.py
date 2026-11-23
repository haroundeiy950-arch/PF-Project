"""Application configuration.

All values can be overridden with environment variables or a ``.env`` file
placed next to ``requirements.txt``.  The module is intentionally free of
heavy dependencies so it can be imported by tests, scripts and workers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from dotenv import load_dotenv # type: ignore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: str) -> List[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    """Runtime settings for the whole application."""

    app_name: str = os.getenv("APP_NAME", "Sentinel AI")
    app_version: str = "1.0.0"
    environment: str = os.getenv("ENVIRONMENT", "development")

    secret_key: str = os.getenv("SECRET_KEY", "sentinel-ai-change-this-secret-key")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = _env_int("ACCESS_TOKEN_EXPIRE_MINUTES", 720)
    password_iterations: int = _env_int("PASSWORD_ITERATIONS", 240_000)

    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _env_int("PORT", 8000)
    cors_origins: List[str] = field(
        default_factory=lambda: _env_list(
            "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000"
        )
    )

    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./storage/sentinel.db")
    storage_dir: Path = Path(os.getenv("STORAGE_DIR", str(PROJECT_ROOT / "storage")))
    seed_demo_data: bool = _env_bool("SEED_DEMO_DATA", True)
    reset_database: bool = _env_bool("RESET_DATABASE", False)

    # AI pipeline ---------------------------------------------------------
    pipeline_enabled: bool = _env_bool("PIPELINE_ENABLED", True)
    detector_mode: str = os.getenv("DETECTOR_MODE", "auto").lower()

    # Live-only camera mode -------------------------------------------------
    # LIVE_ONLY uses the physical camera and skips all demo media/history.
    # Evidence is controlled independently: with EVIDENCE_ENABLED the real AI
    # worker detects motion/threats and saves event snapshots and clips.
    live_only: bool = _env_bool("LIVE_ONLY", True)
    evidence_enabled: bool = _env_bool("EVIDENCE_ENABLED", True)
    live_camera_index: int = _env_int("LIVE_CAMERA_INDEX", 0)
    live_camera_name: str = os.getenv("LIVE_CAMERA_NAME", "Live Security Camera")
    live_camera_fps: int = _env_int("LIVE_CAMERA_FPS", 15)
    camera_discovery_max_index: int = _env_int("CAMERA_DISCOVERY_MAX_INDEX", 5)
    # auto tries DirectShow before MSMF on Windows (MSMF often opens a camera
    # but returns no frames).  dshow / msmf force a specific backend.
    webcam_backend: str = os.getenv("WEBCAM_BACKEND", "auto")
    webcam_switch_seconds: float = _env_float("WEBCAM_SWITCH_SECONDS", 6.0)

    demo_mode: bool = _env_bool("DEMO_MODE", True)
    demo_autotrigger: bool = _env_bool("DEMO_AUTOTRIGGER", True)
    target_fps: int = _env_int("TARGET_FPS", 8)
    frame_width: int = _env_int("FRAME_WIDTH", 960)
    frame_height: int = _env_int("FRAME_HEIGHT", 540)
    yolo_model: str = os.getenv("YOLO_MODEL", "yolov8n.pt")
    yolo_confidence: float = _env_float("YOLO_CONFIDENCE", 0.35)
    face_recognition_enabled: bool = _env_bool("FACE_RECOGNITION_ENABLED", False)
    face_match_threshold: float = _env_float("FACE_MATCH_THRESHOLD", 0.42)

    recording_enabled: bool = _env_bool("RECORDING_ENABLED", True)
    pre_event_seconds: int = _env_int("PRE_EVENT_SECONDS", 6)
    post_event_seconds: int = _env_int("POST_EVENT_SECONDS", 3)
    retention_days: int = _env_int("RETENTION_DAYS", 14)

    # Continuous recording: a security camera writes video all the time, not
    # only when an incident is verified.  Segments are MP4 files in
    # storage/clips/continuous and are pruned by the normal retention worker.
    continuous_recording_enabled: bool = _env_bool("CONTINUOUS_RECORDING_ENABLED", True)
    continuous_segment_seconds: int = _env_int("CONTINUOUS_SEGMENT_SECONDS", 300)
    save_motion_snapshots: bool = _env_bool("SAVE_MOTION_SNAPSHOTS", True)

    voice_enabled: bool = _env_bool("VOICE_ENABLED", True)
    voice_repeat_seconds: int = _env_int("VOICE_REPEAT_SECONDS", 20)
    siren_enabled: bool = _env_bool("SIREN_ENABLED", False)
    webhook_url: str = os.getenv("WEBHOOK_URL", "")

    frontend_dist: Path = Path(
        os.getenv("FRONTEND_DIST", str(PROJECT_ROOT / "frontend" / "dist"))
    )

    @property
    def snapshots_dir(self) -> Path:
        return self.storage_dir / "snapshots"

    @property
    def clips_dir(self) -> Path:
        return self.storage_dir / "clips"

    @property
    def continuous_dir(self) -> Path:
        return self.clips_dir / "continuous"

    @property
    def faces_dir(self) -> Path:
        return self.storage_dir / "faces"

    @property
    def exports_dir(self) -> Path:
        return self.storage_dir / "exports"

    def ensure_directories(self) -> None:
        for directory in (
            self.storage_dir,
            self.snapshots_dir,
            self.clips_dir,
            self.continuous_dir,
            self.faces_dir,
            self.exports_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
