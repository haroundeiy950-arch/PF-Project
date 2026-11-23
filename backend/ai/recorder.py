"""Evidence recording: pre-event ring buffer + before/after incident clips."""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime
from typing import Callable, Deque, List, Optional, Tuple

import cv2 # type: ignore
import numpy as np

from backend.config import settings
from backend.database import session_scope
from backend.models import Camera, Incident, Recording
from backend.services import storage
from backend.services.alarm import broadcast_incident
from backend.utils.logging import get_logger
from backend.utils.time_utils import iso, now

log = get_logger("ai.recorder")


class RingBuffer:
    """Fixed-size buffer of encoded frames (cheap memory footprint)."""

    def __init__(self, max_frames: int) -> None:
        self.frames: Deque[Tuple[datetime, bytes]] = deque(maxlen=max(1, max_frames))

    def push(self, timestamp: datetime, jpeg: bytes) -> None:
        self.frames.append((timestamp, jpeg))

    def snapshot(self) -> List[Tuple[datetime, bytes]]:
        return list(self.frames)

    def clear(self) -> None:
        self.frames.clear()

    def __len__(self) -> int:
        return len(self.frames)


class Recorder:
    """Owns the ring buffer and writes clips asynchronously."""

    def __init__(self, camera_id: int, fps: int = 8) -> None:
        self.camera_id = camera_id
        self.fps = max(1, fps)
        pre_frames = settings.pre_event_seconds * self.fps
        self.buffer = RingBuffer(pre_frames)
        self._active_incidents: set[int] = set()
        self._lock = threading.Lock()

    def push(self, frame_jpeg: bytes, timestamp: Optional[datetime] = None) -> None:
        self.buffer.push(timestamp or now(), frame_jpeg)

    # ------------------------------------------------------------------
    def request_clip(
        self,
        incident_id: int,
        incident_code: str,
        snapshot_path: str,
        latest_frame: Callable[[], Optional[bytes]],
        detected_at: Optional[datetime] = None,
    ) -> None:
        if not settings.recording_enabled:
            return
        with self._lock:
            if incident_id in self._active_incidents:
                return
            self._active_incidents.add(incident_id)

        before = self.buffer.snapshot()
        thread = threading.Thread(
            target=self._write_clip,
            args=(incident_id, incident_code, snapshot_path, before, latest_frame, detected_at),
            daemon=True,
            name=f"clip-{incident_code}",
        )
        thread.start()

    # ------------------------------------------------------------------
    def _write_clip(
        self,
        incident_id: int,
        incident_code: str,
        snapshot_path: str,
        before: List[Tuple[datetime, bytes]],
        latest_frame: Callable[[], Optional[bytes]],
        detected_at: Optional[datetime],
    ) -> None:
        try:
            after_frames: List[bytes] = []
            post_seconds = max(0, settings.post_event_seconds)
            end = time.time() + post_seconds
            interval = 1.0 / self.fps
            while time.time() < end:
                frame = latest_frame()
                if frame:
                    after_frames.append(frame)
                time.sleep(interval)

            decoded_before = [self._decode(jpeg) for _, jpeg in before]
            decoded_before = [frame for frame in decoded_before if frame is not None]
            decoded_after = [self._decode(jpeg) for jpeg in after_frames]
            decoded_after = [frame for frame in decoded_after if frame is not None]
            frames = decoded_before + decoded_after
            if not frames:
                log.warning("No frames available for %s; clip skipped", incident_code)
                return

            height, width = frames[0].shape[:2]
            path, duration = self._encode(incident_code, frames, width, height)
            self._persist(incident_id, path, snapshot_path, len(frames), duration, detected_at)
            log.info("Clip saved for %s (%d frames, %.1fs)", incident_code, len(frames), duration)
        except Exception as exc:  # pragma: no cover - codec/filesystem dependent
            log.warning("Clip generation failed for %s: %s", incident_code, exc)
        finally:
            with self._lock:
                self._active_incidents.discard(incident_id)

    # ------------------------------------------------------------------
    @staticmethod
    def _decode(jpeg: bytes) -> Optional[np.ndarray]:
        buffer = np.frombuffer(jpeg, dtype=np.uint8)
        return cv2.imdecode(buffer, cv2.IMREAD_COLOR)

    def _encode(
        self, incident_code: str, frames: List[np.ndarray], width: int, height: int
    ) -> Tuple[str, float]:
        safe_code = "".join(char for char in incident_code if char.isalnum() or char in "-_")
        timestamp = int(time.time())
        settings.clips_dir.mkdir(parents=True, exist_ok=True)

        attempts = [
            ("mp4v", settings.clips_dir / f"{safe_code}_{timestamp}.mp4"),
            ("XVID", settings.clips_dir / f"{safe_code}_{timestamp}.avi"),
            ("MJPG", settings.clips_dir / f"{safe_code}_{timestamp}_mjpg.avi"),
        ]
        fps = float(self.fps)
        for fourcc_name, path in attempts:
            writer = cv2.VideoWriter(
                str(path), cv2.VideoWriter_fourcc(*fourcc_name), fps, (width, height)
            )
            if not writer.isOpened():
                writer.release()
                continue
            for frame in frames:
                if frame.shape[1] != width or frame.shape[0] != height:
                    frame = cv2.resize(frame, (width, height))
                writer.write(frame)
            writer.release()
            if path.exists() and path.stat().st_size > 0:
                return str(path.relative_to(settings.storage_dir)).replace("\\", "/"), len(frames) / fps

        raise RuntimeError("No usable video codec found (tried mp4v, XVID, MJPG)")

    # ------------------------------------------------------------------
    def _persist(
        self,
        incident_id: int,
        clip_path: str,
        snapshot_path: str,
        frame_count: int,
        duration: float,
        detected_at: Optional[datetime],
    ) -> None:
        with session_scope() as db:
            incident = db.get(Incident, incident_id)
            if incident is None:
                return
            incident.clip_path = clip_path
            if snapshot_path:
                existing = (
                    db.query(Recording)
                    .filter(
                        Recording.incident_id == incident_id,
                        Recording.kind == "snapshot",
                    )
                    .first()
                )
                if existing is None:
                    db.add(
                        Recording(
                            incident_id=incident_id,
                            camera_id=self.camera_id,
                            kind="snapshot",
                            path=snapshot_path,
                            started_at=detected_at,
                            ended_at=detected_at,
                            duration_seconds=0.0,
                            size_bytes=storage.file_size(snapshot_path),
                        )
                    )
            db.add(
                Recording(
                    incident_id=incident_id,
                    camera_id=self.camera_id,
                    kind="clip",
                    path=clip_path,
                    started_at=detected_at,
                    ended_at=detected_at,
                    duration_seconds=round(duration, 2),
                    size_bytes=storage.file_size(clip_path),
                )
            )
            db.flush()
            broadcast_incident(db, incident, "incident.updated")


__all__ = ["RingBuffer", "Recorder"]
