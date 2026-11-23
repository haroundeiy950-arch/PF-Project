"""Image processing helpers: overlay rendering, encoding and snapshots."""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import cv2 # type: ignore
import numpy as np

from backend.config import settings
from backend.constants import LEVEL_COLORS
from backend.utils.geometry import bbox_center
from backend.utils.logging import get_logger
from backend.utils.time_utils import now

log = get_logger("imaging")

FONT = cv2.FONT_HERSHEY_SIMPLEX
GREEN = (86, 220, 120)
CYAN = (220, 210, 34)
RED = (60, 60, 240)
AMBER = (40, 180, 250)
WHITE = (240, 244, 248)
DARK = (18, 22, 28)


def _hex_to_bgr(color: str) -> Tuple[int, int, int]:
    color = color.lstrip("#")
    if len(color) != 6:
        return CYAN
    return (int(color[4:6], 16), int(color[2:4], 16), int(color[0:2], 16))


def _put_label(
    frame: np.ndarray,
    text: str,
    origin: Tuple[int, int],
    fg: Tuple[int, int, int] = DARK,
    bg: Tuple[int, int, int] = WHITE,
    scale: float = 0.5,
    thickness: int = 1,
) -> None:
    x, y = origin
    (tw, th), baseline = cv2.getTextSize(text, FONT, scale, thickness)
    x = max(0, min(x, frame.shape[1] - tw - 10))
    y = max(th + 6, min(y, frame.shape[0] - 4))
    cv2.rectangle(frame, (x - 4, y - th - 6), (x + tw + 5, y + baseline + 2), bg, -1)
    cv2.putText(frame, text, (x, y), FONT, scale, fg, thickness, cv2.LINE_AA)


def draw_detection(
    frame: np.ndarray,
    bbox: Sequence[float],
    label: str,
    color: Tuple[int, int, int] = CYAN,
    thickness: int = 2,
    show_id: bool = True,
) -> None:
    height, width = frame.shape[:2]
    x = int(bbox[0] * width)
    y = int(bbox[1] * height)
    w = int(bbox[2] * width)
    h = int(bbox[3] * height)
    x, y = max(0, x), max(0, y)
    cv2.rectangle(frame, (x, y), (x + w, y + h), color, thickness, cv2.LINE_AA)
    # Corner accents for the surveillance look
    length = max(8, min(w, h) // 5)
    for (px, py, dx, dy) in (
        (x, y, 1, 1),
        (x + w, y, -1, 1),
        (x, y + h, 1, -1),
        (x + w, y + h, -1, -1),
    ):
        cv2.line(frame, (px, py), (px + dx * length, py), color, thickness + 1)
        cv2.line(frame, (px, py), (px, py + dy * length), color, thickness + 1)
    if show_id:
        _put_label(frame, label, (x, max(16, y - 8)), bg=color, fg=DARK, scale=0.45)


def draw_zone(
    frame: np.ndarray,
    points: Sequence[Sequence[float]],
    label: str,
    zone_type: str = "public",
    color: Optional[str] = None,
    alpha: float = 0.16,
) -> None:
    if len(points) < 3:
        return
    height, width = frame.shape[:2]
    polygon = np.array(
        [[int(float(px) * width), int(float(py) * height)] for px, py in points], dtype=np.int32
    )
    palette = {"restricted": "#ef4444", "limited": "#f59e0b", "public": "#22d3ee"}
    bgr = _hex_to_bgr(color or palette.get(zone_type, "#22d3ee"))
    overlay = frame.copy()
    cv2.fillPoly(overlay, [polygon], bgr)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)
    cv2.polylines(frame, [polygon], True, bgr, 2, cv2.LINE_AA)

    anchor = polygon[polygon[:, 1].argmin()]
    _put_label(frame, label.upper(), (int(anchor[0]) + 6, int(anchor[1]) + 18), bg=bgr, scale=0.45)


def draw_header(
    frame: np.ndarray,
    camera_name: str,
    camera_code: str,
    location: str = "",
    threat_level: str = "normal",
    risk_score: Optional[int] = None,
) -> None:
    height, width = frame.shape[:2]
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (width, 46), (10, 14, 20), -1)
    cv2.addWeighted(overlay, 0.72, frame, 0.28, 0, frame)

    cv2.circle(frame, (22, 23), 6, RED if threat_level in {"high", "critical"} else GREEN, -1)
    cv2.putText(
        frame,
        f"{camera_code}  {camera_name}".upper(),
        (38, 29),
        FONT,
        0.52,
        WHITE,
        1,
        cv2.LINE_AA,
    )
    if location:
        cv2.putText(frame, location, (38, 42), FONT, 0.35, (160, 178, 194), 1, cv2.LINE_AA)

    timestamp = now().strftime("%Y-%m-%d %H:%M:%S")
    (tw, _), _ = cv2.getTextSize(timestamp, FONT, 0.42, 1)
    cv2.putText(frame, timestamp, (width - tw - 18, 29), FONT, 0.42, WHITE, 1, cv2.LINE_AA)

    if threat_level in {"high", "critical"}:
        badge = "DANGER" if threat_level == "critical" else "ALERT"
        bgr = _hex_to_bgr(LEVEL_COLORS.get(threat_level, "#ef4444"))
        _put_label(
            frame,
            f"{badge} {risk_score if risk_score is not None else ''}".strip(),
            (width - 150, 44),
            bg=bgr,
            fg=WHITE,
            scale=0.45,
        )


def apply_scanlines(frame: np.ndarray, strength: float = 0.06) -> np.ndarray:
    height = frame.shape[0]
    lines = np.ones((height, 1, 3), dtype=np.float32)
    lines[::3, :, :] = 1.0 - strength
    return np.clip(frame.astype(np.float32) * lines, 0, 255).astype(np.uint8)


def add_vignette(frame: np.ndarray, strength: float = 0.35) -> np.ndarray:
    height, width = frame.shape[:2]
    kernel_x = cv2.getGaussianKernel(width, width * 0.7)
    kernel_y = cv2.getGaussianKernel(height, height * 0.7)
    mask = kernel_y @ kernel_x.T
    mask = mask / mask.max()
    mask = np.clip((mask - strength) / (1 - strength), 0, 1)
    mask = mask[..., None]
    return np.clip(frame.astype(np.float32) * (0.55 + 0.45 * mask), 0, 255).astype(np.uint8)


def annotate_frame(
    frame: np.ndarray,
    camera: Dict[str, Any],
    zones: Iterable[Any] = (),
    detections: Iterable[Dict[str, Any]] = (),
    threat_level: str = "normal",
    risk_score: Optional[int] = None,
    banner: Optional[str] = None,
) -> np.ndarray:
    annotated = frame.copy()
    for zone in zones:
        draw_zone(
            annotated,
            zone.points,
            f"{zone.name} · {zone.zone_type}",
            zone.zone_type,
            zone.color,
            0.12,
        )
    for detection in detections:
        bbox = detection.get("bbox") or [0, 0, 0, 0]
        target = detection.get("target_type", "object")
        zone_type = detection.get("zone_type")
        color = RED if zone_type == "restricted" and target == "person" else CYAN
        label = detection.get("label") or target.title()
        draw_detection(annotated, bbox, label, color=color)

    draw_header(
        annotated,
        camera.get("name", "Camera"),
        camera.get("code", "CAM"),
        camera.get("location", ""),
        threat_level,
        risk_score,
    )

    if banner:
        height, width = annotated.shape[:2]
        overlay = annotated.copy()
        cv2.rectangle(overlay, (0, height - 58), (width, height), (10, 14, 20), -1)
        cv2.addWeighted(overlay, 0.78, annotated, 0.22, 0, annotated)
        cv2.putText(annotated, banner, (20, height - 26), FONT, 0.62, WHITE, 2, cv2.LINE_AA)

    return annotated


def encode_jpeg(frame: np.ndarray, quality: int = 80) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not ok:
        raise RuntimeError("JPEG encoding failed")
    return buffer.tobytes()


def save_snapshot(
    frame: np.ndarray,
    incident_code: str,
    quality: int = 88,
) -> str:
    """Save evidence to storage/snapshots and return a relative path."""
    settings.snapshots_dir.mkdir(parents=True, exist_ok=True)
    safe_code = "".join(char for char in incident_code if char.isalnum() or char in "-_")
    filename = f"{safe_code}_{int(time.time())}.jpg"
    path = settings.snapshots_dir / filename
    cv2.imwrite(str(path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    return f"snapshots/{filename}"


def save_face_photo(data: bytes, person_id: int) -> str:
    settings.faces_dir.mkdir(parents=True, exist_ok=True)
    filename = f"person_{person_id}_{int(time.time())}.jpg"
    path = settings.faces_dir / filename
    path.write_bytes(data)
    return f"faces/{filename}"


def draw_danger_overlay(
    frame: np.ndarray,
    title: str = "DANGER",
    subtitle: str = "",
    level: str = "critical",
) -> None:
    """Large red threat frame + banner, matching the reference mockups."""
    height, width = frame.shape[:2]
    color = _hex_to_bgr(LEVEL_COLORS.get(level, "#ef4444"))
    cv2.rectangle(frame, (0, 0), (width - 1, height - 1), color, 6)

    panel_height = 108
    overlay = frame.copy()
    cv2.rectangle(overlay, (16, 54), (min(width - 16, 470), 54 + panel_height), (6, 8, 12), -1)
    cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)
    cv2.rectangle(frame, (16, 54), (min(width - 16, 470), 54 + panel_height), color, 2)

    cv2.putText(frame, title, (34, 106), FONT, 1.15, color, 3, cv2.LINE_AA)
    if subtitle:
        cv2.putText(
            frame,
            subtitle[:52].upper(),
            (34, 140),
            FONT,
            0.5,
            WHITE,
            1,
            cv2.LINE_AA,
        )
    cv2.putText(
        frame,
        now().strftime("%H:%M:%S"),
        (width - 116, height - 22),
        FONT,
        0.55,
        color,
        2,
        cv2.LINE_AA,
    )


def placeholder_image(width: int = 960, height: int = 540, text: str = "NO SIGNAL") -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[:] = (18, 22, 28)
    for index in range(0, width, 48):
        cv2.line(frame, (index, 0), (index, height), (26, 32, 40), 1)
    for index in range(0, height, 48):
        cv2.line(frame, (0, index), (width, index), (26, 32, 40), 1)
    (tw, th), _ = cv2.getTextSize(text, FONT, 0.9, 2)
    cv2.putText(
        frame,
        text,
        ((width - tw) // 2, (height + th) // 2),
        FONT,
        0.9,
        (120, 140, 160),
        2,
        cv2.LINE_AA,
    )
    return frame


def risk_gauge_frame(score: int, level: str, size: int = 160) -> np.ndarray:
    """Small square gauge used by reports and thumbnails."""
    canvas = np.zeros((size, size, 3), dtype=np.uint8)
    canvas[:] = (14, 18, 24)
    color = _hex_to_bgr(LEVEL_COLORS.get(level, "#22c55e"))
    center = (size // 2, size // 2)
    cv2.ellipse(canvas, center, (60, 60), 0, 135, 405, (40, 48, 58), 10)
    sweep = int(270 * max(0, min(100, score)) / 100)
    cv2.ellipse(canvas, center, (60, 60), 0, 135, 135 + sweep, color, 10)
    text = str(score)
    (tw, th), _ = cv2.getTextSize(text, FONT, 1.0, 2)
    cv2.putText(
        canvas,
        text,
        ((size - tw) // 2, (size + th) // 2 - 6),
        FONT,
        1.0,
        WHITE,
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        canvas,
        level.upper(),
        ((size - cv2.getTextSize(level.upper(), FONT, 0.42, 1)[0][0]) // 2, size - 30),
        FONT,
        0.42,
        color,
        1,
        cv2.LINE_AA,
    )
    return canvas
