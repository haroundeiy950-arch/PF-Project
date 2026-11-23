"""Direct live-camera worker.

Streams the real camera straight into the dashboard.  Frames are encoded in
memory for the MJPEG view and, when continuous recording is enabled, written to
time-sliced video segments on disk.  The worker never creates incidents.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

import cv2  # type: ignore
import numpy as np

from backend.ai.continuous import ContinuousRecorder
from backend.ai.discovery import has_signal, probe_webcams
from backend.ai.pipeline import CameraRuntime
from backend.ai.source import OpenCVSource
from backend.config import settings
from backend.services import imaging
from backend.utils.logging import get_logger

log = get_logger("ai.live")


class LiveCameraWorker(threading.Thread):
    """Minimal, low-latency path from a physical camera to the MJPEG stream."""

    def __init__(self, runtime: CameraRuntime) -> None:
        super().__init__(name=f"live-camera-{runtime.camera_id}", daemon=True)
        self.runtime = runtime
        self.camera: Dict[str, Any] = runtime.camera
        self.camera_id = runtime.camera_id
        self.stop_event = threading.Event()
        self.fps_target = max(1, int(self.camera.get("fps", settings.live_camera_fps)))
        self._fps_window: deque = deque(maxlen=20)
        self._candidates = self._build_candidates()
        self.continuous = ContinuousRecorder(
            self.camera_id,
            str(self.camera.get("code", f"CAM-{self.camera_id:02d}")),
            fps=self.fps_target,
        )

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self.stop_event.set()

    def _build_candidates(self) -> List[Tuple[str, str]]:
        source_type = str(self.camera.get("source_type", "webcam"))
        target = str(self.camera.get("rtsp_url", "") or "").strip()
        if source_type == "rtsp" and target:
            return [(target, "rtsp")]
        if source_type == "file" and target:
            return [(target, "file")]

        indices: List[int] = []
        if target.isdigit():
            indices.append(int(target))
        if settings.live_camera_index not in indices:
            indices.append(settings.live_camera_index)
        for device in probe_webcams():
            if (device.has_signal or device.frames_read) and device.index not in indices:
                indices.append(device.index)
        return [(str(index), "webcam") for index in indices]

    # ------------------------------------------------------------------
    def run(self) -> None:
        log.info(
            "Starting live camera %s (%s) — direct feed",
            self.camera.get("code"),
            self.camera.get("name"),
        )
        try:
            while not self.stop_event.is_set():
                connected = False
                for target, kind in self._candidates:
                    if self.stop_event.is_set():
                        break
                    source = OpenCVSource(target, source_type=kind, fps=self.fps_target)
                    try:
                        if self._stream_from(source):
                            connected = True
                    finally:
                        source.close()
                    if self.stop_event.is_set():
                        break
                    connected = True if self.runtime.status == "online" else connected

                if self.stop_event.is_set():
                    break
                if not connected:
                    self.runtime.set_status("offline", "No live camera image available")
                self._publish_placeholder("NO CAMERA SIGNAL")
                self.stop_event.wait(5.0)
                self._candidates = self._build_candidates()
        finally:
            self.continuous.close()
            self.runtime.set_status("stopped")
            log.info("Live camera %s stopped", self.camera.get("code"))

    # ------------------------------------------------------------------
    def _stream_from(self, source: OpenCVSource) -> bool:
        """Stream one source until it stops producing frames."""
        blank_since: Optional[float] = None
        first_frame_at = time.monotonic()
        last_publish: Optional[float] = None
        produced = False
        interval = 1.0 / self.fps_target

        while not self.stop_event.is_set():
            loop_start = time.monotonic()
            frame = source.read()
            if frame is None:
                if time.monotonic() - first_frame_at > 4.0:
                    return False
                time.sleep(0.1)
                continue

            produced = True
            if not has_signal(frame):
                if blank_since is None:
                    blank_since = time.monotonic()
                elif time.monotonic() - blank_since > 1.5:
                    # Keep the stream and recorder alive so a camera that comes
                    # back (or a different device) appears immediately.
                    self.runtime.set_status("offline", "Camera is connected but shows no image")
            else:
                blank_since = None
                first_frame_at = time.monotonic()
                self.runtime.set_status("online")

            frame = self._fit_frame(frame)
            self._draw_live_overlay(frame, no_image=blank_since is not None)
            published_at = time.monotonic()
            if last_publish is not None:
                delta = published_at - last_publish
                if delta > 0:
                    self._fps_window.append(delta)
            last_publish = published_at
            average = sum(self._fps_window) / len(self._fps_window) if self._fps_window else 0.0
            fps = round(1.0 / average, 1) if average > 0 else 0.0
            jpeg = imaging.encode_jpeg(frame, quality=82)
            self.runtime.publish(jpeg, [], fps, "normal", 0)
            self.continuous.push(jpeg)

            elapsed = time.monotonic() - loop_start
            if elapsed < interval:
                time.sleep(interval - elapsed)
        return produced

    # ------------------------------------------------------------------
    def _fit_frame(self, frame: np.ndarray) -> np.ndarray:
        width, height = settings.frame_width, settings.frame_height
        if frame.shape[1] != width or frame.shape[0] != height:
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        return frame

    def _draw_live_overlay(self, frame: np.ndarray, no_image: bool = False) -> None:
        imaging.draw_header(
            frame,
            str(self.camera.get("name", "Live Camera")),
            str(self.camera.get("code", "CAM")),
            str(self.camera.get("location", "")),
        )
        height, width = frame.shape[:2]
        cv2.rectangle(frame, (0, height - 34), (width, height), (10, 14, 20), -1)
        if no_image:
            text = "NO IMAGE FROM DEVICE  •  CHECK CAMERA / WINDOW PRIVACY SETTINGS"
            color = (100, 160, 240)
        elif settings.continuous_recording_enabled:
            text = "LIVE  •  DIRECT CAMERA  •  CONTINUOUSLY RECORDED"
            color = (120, 230, 160)
        else:
            text = "LIVE  •  DIRECT CAMERA  •  NOT RECORDED"
            color = (160, 178, 194)
        cv2.putText(
            frame,
            text,
            (16, height - 11),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )

    def _publish_placeholder(self, text: str) -> None:
        frame = imaging.placeholder_image(settings.frame_width, settings.frame_height, text)
        self._draw_live_overlay(frame, no_image=True)
        self.runtime.publish(imaging.encode_jpeg(frame, quality=70), [], 0.0, "normal", 0)


__all__ = ["LiveCameraWorker"]
