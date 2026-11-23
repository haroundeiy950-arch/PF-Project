"""Zone resolution and time-schedule handling.

Zones are stored in normalized 0..1 image coordinates so they remain valid at
any stream resolution.  A background pipeline refreshes this cache every few
seconds; API writes call ``invalidate()`` immediately.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import select # type: ignore
from sqlalchemy.orm import Session # type: ignore

from backend.models import Zone
from backend.utils.geometry import point_in_polygon
from backend.utils.time_utils import now

WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


@dataclass
class ZoneSnapshot:
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

    @classmethod
    def from_model(cls, zone: Zone) -> "ZoneSnapshot":
        return cls(
            id=zone.id,
            camera_id=zone.camera_id,
            name=zone.name,
            zone_type=zone.zone_type,
            points=[list(point) for point in (zone.points or [])],
            schedule_start=zone.schedule_start,
            schedule_end=zone.schedule_end,
            days=list(zone.days or []),
            min_dwell_seconds=zone.min_dwell_seconds,
            min_frames=zone.min_frames,
            cooldown_seconds=zone.cooldown_seconds,
            is_enabled=zone.is_enabled,
            color=zone.color,
        )


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        hour, minute = value.split(":")[:2]
        return time(int(hour) % 24, int(minute) % 60)
    except (ValueError, AttributeError):
        return fallback


def schedule_active(
    start: str,
    end: str,
    days: Sequence[int],
    at: Optional[datetime] = None,
) -> bool:
    """Check the weekly schedule of a zone (supports overnight windows)."""
    at = at or now()
    if days and at.weekday() not in set(days):
        return False
    start_time = _parse_hhmm(start, time(0, 0))
    end_time = _parse_hhmm(end, time(23, 59))
    current = at.time()
    if start_time <= end_time:
        return start_time <= current <= end_time
    # Overnight window such as 22:00 -> 06:00
    return current >= start_time or current <= end_time


def describe_schedule(start: str, end: str, days: Sequence[int]) -> str:
    if not days or len(set(days)) == 7:
        label = "Every day"
    else:
        label = ", ".join(WEEKDAY_LABELS[day] for day in sorted(set(days)) if 0 <= day <= 6)
    return f"{label} · {start}–{end}"


class ZoneCache:
    """In-memory cache of zone polygons used by the camera workers."""

    def __init__(self) -> None:
        self._by_camera: Dict[int, List[ZoneSnapshot]] = {}
        self._by_id: Dict[int, ZoneSnapshot] = {}

    def invalidate(self) -> None:
        self._by_camera.clear()
        self._by_id.clear()

    def refresh(self, db: Session) -> int:
        zones = db.scalars(select(Zone).where(Zone.is_enabled.is_(True))).all()
        by_camera: Dict[int, List[ZoneSnapshot]] = {}
        by_id: Dict[int, ZoneSnapshot] = {}
        for zone in zones:
            snapshot = ZoneSnapshot.from_model(zone)
            by_camera.setdefault(zone.camera_id, []).append(snapshot)
            by_id[zone.id] = snapshot
        self._by_camera = by_camera
        self._by_id = by_id
        return len(by_id)

    def zones_for(self, camera_id: int) -> List[ZoneSnapshot]:
        return list(self._by_camera.get(camera_id, []))

    def get(self, zone_id: Optional[int]) -> Optional[ZoneSnapshot]:
        if zone_id is None:
            return None
        return self._by_id.get(zone_id)

    def find_zone(self, camera_id: int, point: Sequence[float]) -> Optional[ZoneSnapshot]:
        """Return the most sensitive zone containing the point."""
        matches = [
            zone
            for zone in self._by_camera.get(camera_id, [])
            if zone.is_enabled and len(zone.points) >= 3 and point_in_polygon(point, zone.points)
        ]
        if not matches:
            return None
        priority = {"restricted": 3, "limited": 2, "public": 1}
        matches.sort(key=lambda zone: priority.get(zone.zone_type, 0), reverse=True)
        return matches[0]

    def any_zone(self, camera_id: int) -> Optional[ZoneSnapshot]:
        zones = self._by_camera.get(camera_id, [])
        return zones[0] if zones else None


zone_cache = ZoneCache()

__all__ = [
    "ZoneSnapshot",
    "ZoneCache",
    "zone_cache",
    "schedule_active",
    "describe_schedule",
    "WEEKDAY_LABELS",
]
