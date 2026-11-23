"""Object detection engines.

* ``YoloDetector`` — Ultralytics YOLO, used when the AI extras are installed.
* ``MotionDetector`` — OpenCV MOG2 fallback that needs no model download and
  keeps the system functional on low-end hardware.
* ``build_detector`` — chooses the engine from configuration and degrades
  gracefully (Section 14: start small without a GPU).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence

import cv2 # type: ignore
import numpy as np

from backend.config import settings
from backend.utils.logging import get_logger

log = get_logger("ai.detector")

# COCO class ids -> Sentinel target types
YOLO_CLASS_MAP = {
    0: ("person", "Person"),
    1: ("vehicle", "Bicycle"),
    2: ("vehicle", "Car"),
    3: ("vehicle", "Motorcycle"),
    5: ("vehicle", "Bus"),
    7: ("vehicle", "Truck"),
}
MIN_BOX_AREA = 0.0012
MAX_DETECTIONS = 12


@dataclass
class Detection:
    """A single detection in normalized 0..1 coordinates."""

    bbox: List[float]
    target_type: str = "person"
    confidence: float = 0.0
    label: str = ""
    face_status: str = "none"  # known | unknown | none
    face_name: Optional[str] = None
    behavior: str = "normal"
    threat_hint: Optional[str] = None
    night: Optional[bool] = None
    is_motion: bool = False
    meta: dict = field(default_factory=dict)

    def center(self) -> tuple[float, float]:
        return (self.bbox[0] + self.bbox[2] / 2.0, self.bbox[1] + self.bbox[3] / 2.0)

    def area(self) -> float:
        return float(self.bbox[2]) * float(self.bbox[3])


class BaseDetector(ABC):
    name: str = "base"

    @abstractmethod
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Return detections for a BGR frame."""


def _normalized_box(x1: float, y1: float, x2: float, y2: float, width: int, height: int) -> List[float]:
    x1 = max(0.0, min(width, x1))
    y1 = max(0.0, min(height, y1))
    x2 = max(0.0, min(width, x2))
    y2 = max(0.0, min(height, y2))
    return [
        round(x1 / width, 5),
        round(y1 / height, 5),
        round(max(0.0, x2 - x1) / width, 5),
        round(max(0.0, y2 - y1) / height, 5),
    ]


class YoloDetector(BaseDetector):
    name = "yolo"

    def __init__(self, model_path: Optional[str] = None, confidence: Optional[float] = None) -> None:
        from ultralytics import YOLO  # type: ignore # lazy, heavy import

        self.model_path = model_path or settings.yolo_model
        self.confidence = confidence or settings.yolo_confidence
        self.model = YOLO(self.model_path)
        self._warned = False
        log.info("YOLO detector ready (%s)", self.model_path)

    def detect(self, frame: np.ndarray) -> List[Detection]:
        height, width = frame.shape[:2]
        try:
            results = self.model.predict(frame, conf=self.confidence, verbose=False)
        except Exception as exc:  # pragma: no cover - inference failure
            log.warning("YOLO inference failed: %s", exc)
            return []

        detections: List[Detection] = []
        for result in results:
            boxes = getattr(result, "boxes", None)
            if boxes is None:
                continue
            for box in boxes:
                class_id = int(box.cls[0].item())
                mapping = YOLO_CLASS_MAP.get(class_id)
                if mapping is None:
                    continue
                target_type, label = mapping
                confidence = float(box.conf[0].item())
                x1, y1, x2, y2 = [float(value) for value in box.xyxy[0].tolist()]
                bbox = _normalized_box(x1, y1, x2, y2, width, height)
                if bbox[2] * bbox[3] < MIN_BOX_AREA:
                    continue
                detections.append(
                    Detection(
                        bbox=bbox,
                        target_type=target_type,
                        confidence=confidence,
                        label=f"{label} {confidence:.0%}",
                    )
                )
                if len(detections) >= MAX_DETECTIONS:
                    break
        return detections


class MotionDetector(BaseDetector):
    """OpenCV background subtraction fallback."""

    name = "motion"

    def __init__(self, min_area: float = 0.0025) -> None:
        self.subtractor = cv2.createBackgroundSubtractorMOG2(
            history=240, varThreshold=36, detectShadows=True
        )
        self.min_area = min_area
        self._frame_count = 0

    def detect(self, frame: np.ndarray) -> List[Detection]:
        height, width = frame.shape[:2]
        self._frame_count += 1
        blurred = cv2.GaussianBlur(frame, (5, 5), 0)
        mask = self.subtractor.apply(blurred)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)
        mask = cv2.dilate(mask, kernel, iterations=2)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections: List[Detection] = []
        for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:MAX_DETECTIONS]:
            area = cv2.contourArea(contour)
            if area < self.min_area * width * height:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            if h < 12 or w < 8:
                continue
            aspect = h / max(1, w)
            bbox = _normalized_box(x, y, x + w, y + h, width, height)
            detections.append(
                Detection(
                    bbox=bbox,
                    target_type="person" if aspect >= 1.1 else "unknown",
                    confidence=0.55,
                    label="Motion",
                    is_motion=True,
                    behavior="normal",
                )
            )
        return detections


def build_detector(mode: Optional[str] = None) -> BaseDetector:
    """Create the configured detector, falling back to motion detection."""
    mode = (mode or settings.detector_mode).lower()
    if mode == "demo":
        return MotionDetector()
    if mode in {"auto", "yolo"}:
        try:
            return YoloDetector()
        except Exception as exc:
            log.warning("YOLO unavailable (%s); falling back to OpenCV motion detection", exc)
            if mode == "yolo":
                return MotionDetector()
    return MotionDetector()


__all__ = [
    "Detection",
    "BaseDetector",
    "YoloDetector",
    "MotionDetector",
    "build_detector",
    "YOLO_CLASS_MAP",
]
