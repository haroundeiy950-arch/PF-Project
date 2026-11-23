"""Video sources: demo renderer, RTSP/file cameras and local webcams."""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional

import cv2 # type: ignore
import numpy as np

from backend.ai.demo import DemoScene
from backend.ai.detector import Detection
from backend.ai.discovery import has_signal, open_webcam, probe_webcams
from backend.config import settings
from backend.utils.logging import get_logger

log = get_logger("ai.source")

# Keep RTSP latency low (used by OpenCV's FFMPEG backend on first open).
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|stimeout;5000000|buffer_size;1024000",
)


class FrameSource(ABC):
    """A source of BGR frames plus optional ground-truth detections."""

    kind = "base"

    @abstractmethod
    def read(self) -> Optional[np.ndarray]:
        ...

    def detections(self) -> Optional[List[Detection]]:
        return None

    def close(self) -> None:
        return None

    def describe(self) -> str:
        return self.kind


class DemoSource(FrameSource):
    """Synthetic camera feed used when no real RTSP camera is configured."""

    kind = "demo"

    def __init__(self, camera_id: int, code: str = "CAM-01") -> None:
        self.scene = DemoScene(camera_id=camera_id, code=code)
        self._elapsed = 0.0
        self._last = time.monotonic()

    def read(self) -> Optional[np.ndarray]:
        current = time.monotonic()
        self._elapsed = self.scene.elapsed(current)
        frame = self.scene.render(self._elapsed)
        self._last = current
        return frame

    def detections(self) -> Optional[List[Detection]]:
        return [obj.to_detection(self.scene.night) for obj in self.scene.objects(self._elapsed)]

    def describe(self) -> str:
        return f"demo://{self.scene.profile_key}"


class OpenCVSource(FrameSource):
    """RTSP / video file / webcam source with automatic reconnection.

    Webcams are opened with a backend that actually delivers frames (DirectShow
    before MSMF on Windows) and the source transparently rotates through other
    detected devices when the selected one is blank or disappears.  That keeps
    the live feed and the recorder running without manual intervention.
    """

    kind = "opencv"

    def __init__(self, target: str, source_type: str = "rtsp", fps: int = 8) -> None:
        self.original_target = str(target)
        self.target = self.original_target
        self.source_type = source_type
        self.fps = fps
        self.capture: Optional[cv2.VideoCapture] = None
        self.backend = ""
        self._last_open_attempt = 0.0
        self._blank_since: Optional[float] = None
        self._candidates: List[str] = [str(self._capture_target())]
        self._candidate_pos = 0
        if self.source_type == "webcam" and settings.live_only:
            # The configured device stays first; working devices are tried next
            # if it is blank, unplugged or reserved by another application.
            devices = probe_webcams()
            for device in devices:
                if device.has_signal and str(device.index) not in self._candidates:
                    self._candidates.append(str(device.index))
            for device in devices:
                if device.frames_read and str(device.index) not in self._candidates:
                    self._candidates.append(str(device.index))
        self._open()

    def _capture_target(self):
        if self.source_type == "webcam":
            try:
                return int(self.target)
            except (TypeError, ValueError):
                return settings.live_camera_index
        if self.source_type == "file":
            path = Path(self.target)
            if not path.is_absolute():
                path = Path(settings.storage_dir).parent / path
            return str(path)
        return self.target

    def _open(self) -> bool:
        self._last_open_attempt = time.monotonic()
        self._blank_since = None
        if self.source_type == "webcam":
            count = len(self._candidates)
            for offset in range(count):
                position = (self._candidate_pos + offset) % count
                target = self._candidates[position]
                try:
                    capture, backend, frame, _frames = open_webcam(int(target))
                except Exception as exc:  # pragma: no cover - hardware dependent
                    log.warning("Could not open webcam %s: %s", target, exc)
                    continue
                if capture is None:
                    continue
                # A blank configured camera is kept so the UI can show a
                # diagnostic, but only after every working device was tried.
                blank = frame is not None and not has_signal(frame)
                if blank and offset < count - 1:
                    capture.release()
                    continue
                self.capture = capture
                self.backend = backend
                self.target = target
                self._candidate_pos = position
                log.info(
                    "Camera source connected: webcam %s via %s%s",
                    target,
                    backend or "default",
                    " (no image yet)" if blank else "",
                )
                return True
            return False

        target = self._capture_target()
        try:
            capture = cv2.VideoCapture(target)
            if self.source_type == "rtsp":
                capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not capture.isOpened():
                capture.release()
                return False
            self.capture = capture
            self.backend = capture.getBackendName() or "default"
            self.target = str(target)
            log.info("Camera source connected: %s", target)
            return True
        except Exception as exc:  # pragma: no cover - hardware dependent
            log.warning("Could not open camera source %s: %s", target, exc)
            return False

    def _rotate_candidate(self) -> None:
        if len(self._candidates) > 1:
            self._candidate_pos = (self._candidate_pos + 1) % len(self._candidates)

    def read(self) -> Optional[np.ndarray]:
        if self.capture is None:
            if time.monotonic() - self._last_open_attempt < 1.5:
                return None
            self._rotate_candidate()
            if not self._open():
                return None
        assert self.capture is not None
        ok, frame = self.capture.read()
        if not ok or frame is None:
            self.capture.release()
            self.capture = None
            self._rotate_candidate()
            return None
        if self.source_type == "webcam" and settings.live_only:
            if not has_signal(frame):
                if self._blank_since is None:
                    self._blank_since = time.monotonic()
                elif time.monotonic() - self._blank_since >= max(1.0, settings.webcam_switch_seconds):
                    # Hand this frame to the worker for the diagnostic overlay,
                    # then reconnect (possibly to a different device).
                    self.capture.release()
                    self.capture = None
                    self._rotate_candidate()
            else:
                self._blank_since = None
        return frame

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

    def describe(self) -> str:
        suffix = f" ({self.backend})" if self.backend else ""
        return f"{self.source_type}://{self.target}{suffix}"


def build_source(camera) -> FrameSource:
    """Create a source from a Camera model or an equivalent dict."""
    source_type = getattr(camera, "source_type", "demo")
    url = getattr(camera, "rtsp_url", "") or ""
    camera_id = int(getattr(camera, "id", 1))
    code = getattr(camera, "code", f"CAM-{camera_id:02d}")
    fps = int(getattr(camera, "fps", settings.target_fps))

    if settings.live_only:
        # Live monitoring always prefers real hardware.  A demo camera record
        # is transparently treated as the configured local webcam.
        if source_type == "rtsp" and url:
            return OpenCVSource(url, source_type="rtsp", fps=fps)
        if source_type == "file" and url:
            return OpenCVSource(url, source_type="file", fps=fps)
        target = url if source_type == "webcam" and url else str(settings.live_camera_index)
        return OpenCVSource(target, source_type="webcam", fps=fps)

    if settings.demo_mode and (source_type == "demo" or not url):
        return DemoSource(camera_id, code)
    if source_type in {"rtsp", "file", "webcam"}:
        if source_type != "webcam" and not url:
            return DemoSource(camera_id, code)
        return OpenCVSource(url, source_type=source_type, fps=fps)
    return DemoSource(camera_id, code)


__all__ = ["FrameSource", "DemoSource", "OpenCVSource", "build_source"]
