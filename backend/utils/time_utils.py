"""Time helpers.

The system stores **server local time** everywhere so that the operator sees
the same wall-clock value that the cameras record.  All helpers return naive
``datetime`` objects which SQLite stores losslessly.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Optional, Tuple


def now() -> datetime:
    """Current server local time (naive)."""
    return datetime.now().replace(microsecond=0)


def iso(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat()


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip().replace("Z", "")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        return None


def seconds_since(value: Optional[datetime]) -> float:
    if value is None:
        return 0.0
    return max(0.0, (now() - value).total_seconds())


def human_duration(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, sec = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {sec}s" if sec else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def day_bounds(days_ago: int = 0) -> Tuple[datetime, datetime]:
    target: date = now().date() - timedelta(days=days_ago)
    start = datetime.combine(target, time.min)
    return start, start + timedelta(days=1)


def start_of_hour(dt: Optional[datetime] = None) -> datetime:
    dt = dt or now()
    return dt.replace(minute=0, second=0, microsecond=0)
