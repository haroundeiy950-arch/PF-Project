"""Optional face recognition (InsightFace) with graceful degradation.

Face recognition is **never** a reason to trigger a danger alarm on its own
(Section 3).  The engine only reports ``known`` / ``unknown`` and a similarity
score; the risk engine caps its contribution at a few points.

InsightFace is an optional dependency.  Install it with
``pip install -r requirements-ai.txt``.  Without it the system keeps working
and the UI shows "face engine unavailable".
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import cv2 # type: ignore
import numpy as np

from backend.config import settings
from backend.utils.logging import get_logger

log = get_logger("ai.face")


@dataclass
class FaceMatch:
    status: str = "none"  # known | unknown | none
    name: Optional[str] = None
    similarity: float = 0.0
    available: bool = False
    engine: str = "insightface"


class FaceEngine:
    """Wraps InsightFace; all heavy work happens lazily in a lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._app = None
        self._init_error: Optional[str] = None
        self._initialized = False

    # ------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._ensure() and self._app is not None

    @property
    def status(self) -> dict:
        return {
            "available": self._app is not None,
            "engine": "insightface",
            "error": self._init_error,
        }

    def _ensure(self) -> bool:
        if self._initialized:
            return self._app is not None
        with self._lock:
            if self._initialized:
                return self._app is not None
            self._initialized = True
            try:
                from insightface.app import FaceAnalysis  # type: ignore # lazy import

                app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
                app.prepare(ctx_id=-1, det_size=(640, 640))
                self._app = app
                log.info("InsightFace face recognition ready")
            except Exception as exc:
                self._init_error = str(exc)
                log.warning("InsightFace unavailable: %s", exc)
        return self._app is not None

    # ------------------------------------------------------------------
    def _largest_face(self, image: np.ndarray):
        if not self.available:
            return None
        faces = self._app.get(image)
        if not faces:
            return None
        return max(faces, key=lambda face: (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))

    def analyze(
        self,
        frame: np.ndarray,
        bbox: Optional[Sequence[float]] = None,
        gallery: Optional[List[Tuple[str, np.ndarray]]] = None,
        threshold: Optional[float] = None,
    ) -> FaceMatch:
        if not self.available:
            return FaceMatch(status="none", available=False)

        image = frame
        if bbox and len(bbox) == 4:
            height, width = frame.shape[:2]
            x = max(0, int(bbox[0] * width) - 20)
            y = max(0, int(bbox[1] * height) - 20)
            w = int(bbox[2] * width) + 40
            h = int(bbox[3] * height) + 40
            crop = frame[y : min(height, y + h), x : min(width, x + w)]
            if crop.size:
                image = crop

        with self._lock:
            face = self._largest_face(image)
        if face is None:
            return FaceMatch(status="none", available=True)

        embedding = np.asarray(face.normed_embedding, dtype=np.float32)
        threshold = settings.face_match_threshold if threshold is None else threshold
        best_name: Optional[str] = None
        best_score = -1.0
        for name, known in gallery or []:
            if known is None or known.size != embedding.size:
                continue
            score = float(np.dot(embedding, known))
            if score > best_score:
                best_score = score
                best_name = name

        if best_name is not None and best_score >= threshold:
            return FaceMatch(status="known", name=best_name, similarity=best_score, available=True)
        return FaceMatch(status="unknown", similarity=max(0.0, best_score), available=True)

    def extract_embedding(self, image_bytes: bytes) -> Optional[List[float]]:
        """Extract a normalized embedding for enrollment."""
        if not self.available:
            return None
        buffer = np.frombuffer(image_bytes, dtype=np.uint8)
        image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
        if image is None:
            return None
        with self._lock:
            face = self._largest_face(image)
        if face is None:
            return None
        return [float(value) for value in np.asarray(face.normed_embedding, dtype=np.float32)]


_engine: Optional[FaceEngine] = None
_engine_lock = threading.Lock()


def get_face_engine() -> FaceEngine:
    global _engine
    with _engine_lock:
        if _engine is None:
            _engine = FaceEngine()
        return _engine


def build_face_engine() -> FaceEngine:
    return get_face_engine()


__all__ = ["FaceMatch", "FaceEngine", "get_face_engine", "build_face_engine"]
