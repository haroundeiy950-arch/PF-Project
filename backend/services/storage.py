"""Evidence storage helpers: URLs, retention cleanup and disk statistics."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.config import settings
from backend.models import Recording
from backend.utils.logging import get_logger
from backend.utils.time_utils import now

log = get_logger("storage")


def media_url(relative_path: Optional[str]) -> Optional[str]:
    """Convert a stored relative path into a browser URL."""
    if not relative_path:
        return None
    normalized = str(relative_path).replace("\\", "/").lstrip("/")
    return f"/media/{normalized}"


def absolute_path(relative_path: str) -> Path:
    return Path(settings.storage_dir) / str(relative_path).replace("\\", "/")


def file_size(relative_path: str) -> int:
    try:
        return absolute_path(relative_path).stat().st_size
    except OSError:
        return 0


def delete_file(relative_path: str) -> bool:
    try:
        path = absolute_path(relative_path)
        if path.is_file():
            path.unlink()
            return True
    except OSError as exc:  # pragma: no cover - filesystem dependent
        log.warning("Could not delete %s: %s", relative_path, exc)
    return False


def disk_status() -> dict:
    usage = shutil.disk_usage(settings.storage_dir)
    total_gb = usage.total / (1024**3)
    used_gb = usage.used / (1024**3)
    free_gb = usage.free / (1024**3)
    storage_gb = sum(
        path.stat().st_size for path in Path(settings.storage_dir).rglob("*") if path.is_file()
    ) / (1024**3)
    return {
        "total_gb": round(total_gb, 1),
        "used_gb": round(used_gb, 1),
        "free_gb": round(free_gb, 1),
        "percent": round((used_gb / total_gb) * 100, 1) if total_gb else 0.0,
        "storage_gb": round(storage_gb, 2),
    }


def storage_estimate_per_camera_gb_per_day(bitrate_mbps: float = 2.0) -> float:
    """Section 14: 2 Mbps ≈ 21 GB/day for continuous recording."""
    return round((bitrate_mbps * 1_000_000 / 8) * 86_400 / (1024**3), 1)


def purge_expired_recordings(db: Session, retention_days: Optional[int] = None) -> dict:
    days = retention_days if retention_days is not None else settings.retention_days
    if days <= 0:
        return {"deleted": 0, "freed_bytes": 0}

    cutoff = now() - timedelta(days=days)
    recordings = db.scalars(select(Recording).where(Recording.created_at < cutoff)).all()
    deleted = 0
    freed = 0
    for recording in recordings:
        size = file_size(recording.path)
        if delete_file(recording.path):
            deleted += 1
            freed += size
        db.delete(recording)
    if deleted:
        db.commit()
        log.info("Retention cleanup removed %d recordings (%.1f MB)", deleted, freed / 1e6)
    return {"deleted": deleted, "freed_bytes": freed}


__all__ = [
    "media_url",
    "absolute_path",
    "file_size",
    "delete_file",
    "disk_status",
    "storage_estimate_per_camera_gb_per_day",
    "purge_expired_recordings",
]
