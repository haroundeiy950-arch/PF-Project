"""Continuous security recording: non-stop video segments on disk.

An event clip only shows *what triggered an alarm*.  A security camera also has
to preserve everything that happened between alarms, so this recorder writes
every streamed frame into time-sliced MP4 files and registers each finished
segment in the evidence archive.  Files are pruned by the normal retention
worker together with snapshots and incident clips.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple

import cv2  # type: ignore
import numpy as np

from backend.config import settings
from backend.database import session_scope
from backend.models import Recording
from backend.utils.logging import get_logger
from backend.utils.time_utils import now

log = get_logger("ai.continuous")

_CODECS: Tuple[Tuple[str, str], ...] = (("mp4v", ".mp4"), ("XVID", ".avi"), ("MJPG", ".avi"))


class ContinuousRecorder:
    """Streaming MP4 writer that rotates segments and archives them."""

    def __init__(self, camera_id: int, code: str, fps: Optional[int] = None) -> None:
        self.camera_id = int(camera_id)
        self.code = str(code or f"CAM-{camera_id:02d}")
        self.fps = max(1, int(fps or settings.target_fps))
        self.segment_seconds = max(5, int(settings.continuous_segment_seconds))
        self.enabled = bool(settings.continuous_recording_enabled)
        self._writer: Optional[cv2.VideoWriter] = None
        self._path: Optional[Path] = None
        self._started_at: Optional[datetime] = None
        self._frames = 0
        self._size = (0, 0)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def push(self, frame_jpeg: bytes, timestamp: Optional[datetime] = None) -> None:
        """Append one encoded camera frame to the current segment."""
        if not self.enabled or not frame_jpeg:
            return
        stamp = timestamp or now()
        with self._lock:
            frame = self._decode(frame_jpeg)
            if frame is None:
                return
            height, width = frame.shape[:2]
            try:
                if (
                    self._writer is None
                    or self._path is None
                    or self._started_at is None
                    or (stamp - self._started_at).total_seconds() >= self.segment_seconds
                    or (width, height) != self._size
                ):
                    self._rotate(stamp, width, height)
                if self._writer is not None:
                    self._writer.write(frame)
                    self._frames += 1
            except Exception as exc:  # pragma: no cover - codec dependent
                log.warning("Continuous recording write failed: %s", exc)
                self._finalize()

    def close(self) -> None:
        """Flush and archive the last segment (called on worker shutdown)."""
        with self._lock:
            self._finalize()

    # ------------------------------------------------------------------
    @staticmethod
    def _decode(jpeg: bytes) -> Optional[np.ndarray]:
        try:
            return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception:  # pragma: no cover - corrupt frame
            return None

    def _rotate(self, stamp: datetime, width: int, height: int) -> None:
        self._finalize()
        settings.continuous_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(char for char in self.code if char.isalnum() or char in "-_")
        prefix = f"{safe}_{stamp.strftime('%Y%m%d-%H%M%S')}_{int(time.time() * 1000) % 100000}"
        for codec, suffix in _CODECS:
            path = settings.continuous_dir / f"{prefix}{suffix}"
            try:
                writer = cv2.VideoWriter(
                    str(path), cv2.VideoWriter_fourcc(*codec), float(self.fps), (width, height)
                )
            except Exception:  # pragma: no cover - codec dependent
                writer = None
            if writer is not None and writer.isOpened():
                self._writer = writer
                self._path = path
                self._started_at = stamp
                self._frames = 0
                self._size = (width, height)
                log.info("Continuous recording started: %s", path.name)
                return
            if writer is not None:
                writer.release()
        log.warning("No usable video codec for continuous recording (tried %s)", ", ".join(c[0] for c in _CODECS))

    def _finalize(self) -> None:
        writer, path, started, frames = self._writer, self._path, self._started_at, self._frames
        self._writer = None
        self._path = None
        self._started_at = None
        self._frames = 0
        if writer is not None:
            writer.release()
        if path is None or frames == 0 or not path.exists() or path.stat().st_size == 0:
            if path is not None:
                path.unlink(missing_ok=True)
            return
        duration = frames / self.fps if self.fps else 0.0
        relative = str(path.relative_to(settings.storage_dir)).replace("\\", "/")
        try:
            self._persist(relative, started or now(), now(), duration, path.stat().st_size)
            log.info("Continuous segment saved: %s (%.1fs)", path.name, duration)
        except Exception as exc:  # pragma: no cover - database dependent
            log.warning("Could not archive continuous segment %s: %s", path.name, exc)

    def _persist(
        self, path: str, started_at: datetime, ended_at: datetime, duration: float, size: int
    ) -> None:
        with session_scope() as db:
            db.add(
                Recording(
                    camera_id=self.camera_id,
                    kind="continuous",
                    path=path,
                    started_at=started_at,
                    ended_at=ended_at,
                    duration_seconds=round(duration, 2),
                    size_bytes=size,
                )
            )


__all__ = ["ContinuousRecorder"]
