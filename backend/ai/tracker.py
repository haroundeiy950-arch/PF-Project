"""Light-weight IoU tracker.

Gives every target a stable id so the system can measure dwell time, detect
loitering and group consecutive detections into a single incident.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Deque, Dict, List, Optional, Sequence, Tuple

from backend.ai.detector import Detection
from backend.utils.geometry import bbox_center, bbox_iou
from backend.utils.time_utils import now


@dataclass
class Track:
    id: str
    bbox: List[float]
    target_type: str
    confidence: float
    first_seen: datetime
    last_seen: datetime
    hits: int = 1
    misses: int = 0
    face_status: str = "none"
    face_name: Optional[str] = None
    behavior: str = "normal"
    threat_hint: Optional[str] = None
    night: Optional[bool] = None
    label: str = ""
    is_motion: bool = False
    history: Deque[Tuple[float, float, float]] = field(default_factory=lambda: deque(maxlen=12))

    @property
    def dwell_seconds(self) -> float:
        return max(0.0, (self.last_seen - self.first_seen).total_seconds())

    def speed(self) -> float:
        """Normalized frame-widths per second over the recent history."""
        if len(self.history) < 2:
            return 0.0
        first_time, first_x, first_y = self.history[0]
        last_time, last_x, last_y = self.history[-1]
        dt = max(1e-3, last_time - first_time)
        return math.hypot(last_x - first_x, last_y - first_y) / dt

    def update_from_detection(self, detection: Detection, timestamp: datetime) -> None:
        self.bbox = [round(value, 5) for value in detection.bbox]
        self.target_type = detection.target_type
        self.confidence = detection.confidence
        self.last_seen = timestamp
        self.hits += 1
        self.misses = 0
        if detection.face_status != "none":
            self.face_status = detection.face_status
            self.face_name = detection.face_name
        if detection.behavior and detection.behavior != "normal":
            self.behavior = detection.behavior
        if detection.threat_hint:
            self.threat_hint = detection.threat_hint
        if detection.night is not None:
            self.night = detection.night
        if detection.label:
            self.label = detection.label
        self.is_motion = detection.is_motion
        center_x, center_y = bbox_center(self.bbox)
        self.history.append((timestamp.timestamp(), center_x, center_y))

    def inferred_behavior(self) -> str:
        """Combine object-supplied behaviour with motion analysis."""
        if self.behavior not in {"", "normal"}:
            return self.behavior
        speed = self.speed()
        if speed > 0.42:
            return "running"
        if self.dwell_seconds > 12 and speed < 0.02:
            return "loitering"
        if self.dwell_seconds > 5 and speed < 0.04:
            return "approaching"
        return "normal"


class IouTracker:
    def __init__(
        self,
        iou_threshold: float = 0.22,
        max_misses: int = 4,
        id_prefix: str = "T",
    ) -> None:
        self.iou_threshold = iou_threshold
        self.max_misses = max_misses
        self.id_prefix = id_prefix
        self.tracks: Dict[str, Track] = {}
        self._next_id = 1

    # ------------------------------------------------------------------
    def _new_id(self) -> str:
        identifier = f"{self.id_prefix}-{self._next_id:04d}"
        self._next_id += 1
        return identifier

    def reset(self) -> None:
        self.tracks.clear()
        self._next_id = 1

    # ------------------------------------------------------------------
    def update(
        self,
        detections: Sequence[Detection],
        timestamp: Optional[datetime] = None,
    ) -> List[Track]:
        timestamp = timestamp or now()
        unmatched_tracks = set(self.tracks.keys())
        matched_pairs: List[Tuple[str, Detection]] = []

        # Greedy best-IoU matching, same target family only.
        for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
            best_id: Optional[str] = None
            best_iou = self.iou_threshold
            for track_id in unmatched_tracks:
                track = self.tracks[track_id]
                if track.target_type != detection.target_type and detection.target_type != "unknown":
                    continue
                score = bbox_iou(track.bbox, detection.bbox)
                if score >= best_iou:
                    best_iou = score
                    best_id = track_id
            if best_id is not None:
                matched_pairs.append((best_id, detection))
                unmatched_tracks.discard(best_id)
                self.tracks[best_id].update_from_detection(detection, timestamp)
            else:
                new_track = Track(
                    id=self._new_id(),
                    bbox=[round(value, 5) for value in detection.bbox],
                    target_type=detection.target_type,
                    confidence=detection.confidence,
                    first_seen=timestamp,
                    last_seen=timestamp,
                    hits=1,
                    face_status=detection.face_status,
                    face_name=detection.face_name,
                    behavior=detection.behavior or "normal",
                    threat_hint=detection.threat_hint,
                    night=detection.night,
                    label=detection.label,
                    is_motion=detection.is_motion,
                )
                center_x, center_y = bbox_center(new_track.bbox)
                new_track.history.append((timestamp.timestamp(), center_x, center_y))
                self.tracks[new_track.id] = new_track

        stale: List[str] = []
        for track_id in unmatched_tracks:
            track = self.tracks[track_id]
            track.misses += 1
            if track.misses > self.max_misses:
                stale.append(track_id)
        for track_id in stale:
            self.tracks.pop(track_id, None)

        # Active tracks sorted by threat relevance then age.
        active = [track for track in self.tracks.values() if track.misses == 0]
        active.sort(key=lambda item: item.dwell_seconds, reverse=True)
        return active

    def get(self, track_id: str) -> Optional[Track]:
        return self.tracks.get(track_id)


__all__ = ["Track", "IouTracker"]
