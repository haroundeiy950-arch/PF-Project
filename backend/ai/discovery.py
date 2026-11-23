"""Real camera discovery, backend selection and signal checks.

This module only inspects physical capture devices.  It never opens a file or
returns a synthetic image, so the dashboard can tell the difference between a
genuine live camera and "no signal".

On Windows the default OpenCV backend (MSMF) frequently opens a webcam but
delivers no frames at all, while DirectShow works.  ``open_webcam`` therefore
tries several backends and keeps the one that actually produces an image.
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

import cv2  # type: ignore
import numpy as np

from backend.config import settings
from backend.utils.logging import get_logger

log = get_logger("ai.discovery")


@dataclass
class CameraDevice:
    index: int
    label: str
    width: int
    height: int
    fps: float
    has_signal: bool
    brightness: float
    variance: float
    backend: str = "any"
    frames_read: int = 0
    note: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


def has_signal(frame: Optional[np.ndarray]) -> bool:
    """True when a frame contains a real image, not a black/blank sensor."""
    if frame is None or frame.size == 0:
        return False
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    small = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)
    # A blank webcam (privacy shutter, disabled device or virtual camera) is
    # almost always uniform and very dark.  Real scenes have visible variation.
    return float(small.std()) > 3.0 and float(small.mean()) > 4.0


def webcam_backends() -> List[Tuple[str, int]]:
    """Backends to try, in order, for a local webcam on this platform."""
    preference = settings.webcam_backend.strip().lower()
    if preference in {"dshow", "directshow"} and os.name == "nt":
        return [("DSHOW", cv2.CAP_DSHOW)]
    if preference == "msmf" and os.name == "nt":
        return [("MSMF", cv2.CAP_MSMF)]
    if preference not in {"auto", ""}:
        # Unknown explicit value: let OpenCV decide.
        return [("ANY", cv2.CAP_ANY)]
    if os.name == "nt":
        # DirectShow succeeds on systems where MSMF silently returns no frames.
        return [("DSHOW", cv2.CAP_DSHOW), ("MSMF", cv2.CAP_MSMF), ("ANY", cv2.CAP_ANY)]
    return [("ANY", cv2.CAP_ANY)]


def open_webcam(
    index: int, probes: int = 4, settle: float = 0.05
) -> Tuple[Optional[cv2.VideoCapture], str, Optional[np.ndarray], int]:
    """Open a webcam and return ``(capture, backend, frame, frames_read)``.

    The first backend that delivers a frame with a real image wins.  If every
    backend is silent (or black) the capture that read the most frames is kept,
    so the live view can still show a diagnostic instead of an empty box.
    Callers own the returned capture and must release it.
    """
    best: Optional[Tuple[cv2.VideoCapture, str, Optional[np.ndarray], int]] = None
    saw_frames = False
    for name, backend_id in webcam_backends():
        capture: Optional[cv2.VideoCapture] = None
        try:
            capture = cv2.VideoCapture(int(index), backend_id)
            if not capture.isOpened():
                capture.release()
                continue
            frame: Optional[np.ndarray] = None
            frames_read = 0
            for _ in range(max(1, probes)):
                ok, candidate = capture.read()
                if ok and candidate is not None:
                    frames_read += 1
                    frame = candidate
                    if has_signal(frame):
                        break
                time.sleep(settle)
            if frames_read == 0 and saw_frames:
                # A backend that opened the device but delivered nothing is
                # enough evidence that the remaining backends will not help.
                capture.release()
                break
            saw_frames = saw_frames or frames_read > 0
            result = (capture, name, frame, frames_read)
            if frame is not None and has_signal(frame):
                if best is not None and best[0] is not capture:
                    best[0].release()
                return result
            if best is None or frames_read > best[3]:
                if best is not None:
                    best[0].release()
                best = result
            else:
                capture.release()
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.warning("Could not open camera %s with %s: %s", index, name, exc)
            if capture is not None:
                capture.release()
    return best or (None, "", None, 0)


def _probe_index(index: int) -> Optional[CameraDevice]:
    capture, backend, frame, frames_read = open_webcam(index)
    if capture is None:
        return None
    try:
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        gray = (
            cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            if frame is not None and frame.ndim == 3
            else frame
        )
        brightness = float(gray.mean()) if gray is not None else 0.0
        variance = float(gray.std()) if gray is not None else 0.0
        signal = has_signal(frame) if frames_read else False
        if signal:
            note = "Live image detected"
        elif frames_read:
            note = "Connected but no image — check device state / privacy shutter"
        else:
            note = "Device opened but delivered no frames"
        return CameraDevice(
            index=index,
            label=f"Camera {index}",
            width=width,
            height=height,
            fps=round(fps, 1),
            has_signal=signal,
            brightness=round(brightness, 1),
            variance=round(variance, 1),
            backend=backend,
            frames_read=frames_read,
            note=note,
        )
    finally:
        capture.release()


def probe_webcams(max_index: Optional[int] = None) -> List[CameraDevice]:
    """Probe local webcam indices and report which ones show a live image."""
    limit = max_index if max_index is not None else settings.camera_discovery_max_index
    devices: List[CameraDevice] = []
    for index in range(max(0, limit)):
        device = _probe_index(index)
        if device is not None:
            devices.append(device)
    return devices


def preferred_camera_index(devices: Optional[List[CameraDevice]] = None) -> Optional[int]:
    """Pick the first camera that actually produces an image.

    A device that only produces black frames is a last resort: it is returned
    when nothing better exists so the live view can still show diagnostics.
    """
    candidates = devices if devices is not None else probe_webcams()
    for device in candidates:
        if device.has_signal:
            return device.index
    for device in candidates:
        if device.frames_read > 0:
            return device.index
    return candidates[0].index if candidates else None


__all__ = [
    "CameraDevice",
    "has_signal",
    "webcam_backends",
    "open_webcam",
    "probe_webcams",
    "preferred_camera_index",
]
