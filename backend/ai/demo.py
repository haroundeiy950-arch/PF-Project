"""Synthetic demo camera renderer.

The demo mode produces realistic-looking surveillance frames (night IR, gate,
perimeter fence, parking lot, vault corridor) together with ground-truth
detections.  This lets the whole chain — verification, risk score, alarm,
voice warning, evidence capture — run end-to-end without real cameras.

The renderer is intentionally deterministic: the same cycle repeats so that
demos and tests are reproducible.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import cv2 # type: ignore
import numpy as np

from backend.ai.detector import Detection

W, H = 960, 540


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


@dataclass
class DemoObject:
    kind: str  # person | vehicle
    x: float
    y: float
    w: float
    h: float
    behavior: str = "normal"
    face_status: str = "none"
    face_name: Optional[str] = None
    threat_hint: Optional[str] = None
    confidence: float = 0.92
    label: str = ""

    def bbox(self) -> List[float]:
        return [
            round(_clamp(self.x, 0, 1), 5),
            round(_clamp(self.y, 0, 1), 5),
            round(_clamp(self.w, 0, 1), 5),
            round(_clamp(self.h, 0, 1), 5),
        ]

    def to_detection(self, night: bool) -> Detection:
        return Detection(
            bbox=self.bbox(),
            target_type=self.kind,
            confidence=self.confidence,
            label=self.label
            or (f"{'Person' if self.kind == 'person' else 'Vehicle'} {self.confidence:.0%}"),
            face_status=self.face_status,
            face_name=self.face_name,
            behavior=self.behavior,
            threat_hint=self.threat_hint,
            night=night,
        )


# ---------------------------------------------------------------------------
# Scene profiles
# ---------------------------------------------------------------------------
PROFILE_ORDER = ["entrance", "perimeter", "parking", "vault"]

_SCENE_META = {
    "entrance": {
        "name": "Main Entrance Gate",
        "cycle": 42.0,
        "night": False,
        "sky": (118, 126, 132),
        "horizon": 0.55,
        "ground": (58, 62, 68),
    },
    "perimeter": {
        "name": "North Perimeter Fence",
        "cycle": 36.0,
        "night": True,
        "sky": (14, 20, 28),
        "horizon": 0.58,
        "ground": (22, 30, 32),
    },
    "parking": {
        "name": "Staff Parking Lot",
        "cycle": 46.0,
        "night": True,
        "sky": (18, 26, 38),
        "horizon": 0.60,
        "ground": (28, 32, 38),
    },
    "vault": {
        "name": "Vault Access Corridor",
        "cycle": 34.0,
        "night": True,
        "sky": (12, 18, 20),
        "horizon": 0.62,
        "ground": (20, 26, 26),
    },
}


class DemoScene:
    """Renders one synthetic camera feed."""

    def __init__(self, camera_id: int, code: str = "CAM-01", seed_offset: int = 0) -> None:
        profile_key = PROFILE_ORDER[(max(1, camera_id) - 1) % len(PROFILE_ORDER)]
        self.camera_id = camera_id
        self.code = code
        self.profile_key = profile_key
        self.meta = _SCENE_META[profile_key]
        self.cycle = float(self.meta["cycle"])
        self.night = bool(self.meta["night"])
        self.offset = (camera_id * 5.3 + seed_offset * 1.7) % self.cycle
        self._started = time.monotonic() + self.offset
        self._rng = np.random.default_rng(1000 + camera_id)
        self._grain: Optional[np.ndarray] = None
        self._grain_tick = 0
        self._W, self._H = W, H

    # ------------------------------------------------------------------
    def elapsed(self, at: Optional[float] = None) -> float:
        timestamp = time.monotonic() if at is None else at
        return (timestamp - self._started) % self.cycle

    # ------------------------------------------------------------------
    def objects(self, elapsed: Optional[float] = None) -> List[DemoObject]:
        t = self.elapsed() if elapsed is None else elapsed
        if self.profile_key == "entrance":
            return self._entrance(t)
        if self.profile_key == "perimeter":
            return self._perimeter(t)
        if self.profile_key == "parking":
            return self._parking(t)
        return self._vault(t)

    # ------------------------------------------------------------------
    # Scenario scripts (all coordinates normalized)
    # ------------------------------------------------------------------
    def _entrance(self, t: float) -> List[DemoObject]:
        objects: List[DemoObject] = []
        if t < 10:
            progress = _ease(t / 10)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(0.02, 0.36, progress),
                    0.60,
                    0.075,
                    0.30,
                    face_status="known",
                    face_name="Haroun Salem",
                    label="Person · authorized",
                )
            )
        elif t < 16:
            progress = _ease((t - 10) / 6)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(0.36, 0.60, progress),
                    0.60,
                    0.078,
                    0.31,
                    face_status="unknown",
                    behavior="approaching",
                    threat_hint="restricted_intrusion",
                )
            )
        elif t < 28:
            sway = math.sin((t - 16) * 1.2) * 0.006
            objects.append(
                DemoObject(
                    "person",
                    0.60 + sway,
                    0.60,
                    0.080,
                    0.32,
                    face_status="unknown",
                    behavior="loitering",
                    threat_hint="loitering",
                )
            )
        elif t < 34:
            progress = _ease((t - 28) / 6)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(0.60, 0.96, progress),
                    0.60,
                    0.080,
                    0.32,
                    face_status="unknown",
                    behavior="running",
                    threat_hint="abnormal_activity",
                )
            )
        else:
            progress = _ease((t - 34) / 8)
            objects.append(
                DemoObject(
                    "vehicle",
                    _lerp(0.98, -0.10, progress),
                    0.835,
                    0.24,
                    0.15,
                    confidence=0.95,
                    label="Vehicle · sedan",
                )
            )
        return objects

    def _perimeter(self, t: float) -> List[DemoObject]:
        objects: List[DemoObject] = []
        if 4 <= t < 14:
            progress = _ease((t - 4) / 10)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(-0.02, 0.98, progress),
                    0.62,
                    0.070,
                    0.29,
                    face_status="unknown",
                    behavior="erratic",
                    threat_hint="restricted_intrusion",
                )
            )
        elif 14 <= t < 22:
            progress = _ease((t - 14) / 8)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(0.98, 0.55, progress),
                    0.62,
                    0.072,
                    0.30,
                    face_status="unknown",
                    behavior="running",
                    threat_hint="abnormal_activity",
                )
            )

        if 24 <= t < 35:
            progress = _ease((t - 24) / 11)
            objects.append(
                DemoObject(
                    "vehicle",
                    _lerp(-0.15, 1.1, progress),
                    0.885,
                    0.22,
                    0.13,
                    confidence=0.94,
                    label="Patrol vehicle",
                )
            )
        return objects

    def _parking(self, t: float) -> List[DemoObject]:
        objects: List[DemoObject] = []
        if t < 13:
            progress = _ease(t / 13)
            objects.append(
                DemoObject(
                    "vehicle",
                    _lerp(-0.2, 1.05, progress),
                    0.80,
                    0.23,
                    0.15,
                    confidence=0.96,
                    label="Vehicle · SUV",
                )
            )
        elif 15 <= t < 36:
            sway = math.sin((t - 15) * 0.9) * 0.012
            behavior = "loitering" if t < 30 else "approaching"
            objects.append(
                DemoObject(
                    "person",
                    0.56 + sway,
                    0.63,
                    0.075,
                    0.30,
                    face_status="unknown",
                    behavior=behavior,
                    threat_hint="loitering",
                )
            )
        if 22 <= t < 32:
            objects.append(
                DemoObject(
                    "vehicle",
                    0.20,
                    0.74,
                    0.20,
                    0.13,
                    confidence=0.9,
                    label="Parked vehicle",
                )
            )
        return objects

    def _vault(self, t: float) -> List[DemoObject]:
        objects: List[DemoObject] = []
        if 5 <= t < 9:
            progress = _ease((t - 5) / 4)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(0.10, 0.55, progress),
                    0.55,
                    0.078,
                    0.33,
                    face_status="unknown",
                    behavior="running",
                    threat_hint="abnormal_activity",
                )
            )
        elif 9 <= t < 21:
            sway = math.sin((t - 9) * 1.4) * 0.007
            objects.append(
                DemoObject(
                    "person",
                    0.565 + sway,
                    0.55,
                    0.082,
                    0.34,
                    face_status="unknown",
                    behavior="loitering",
                    threat_hint="loitering",
                )
            )
        elif 21 <= t < 27:
            progress = _ease((t - 21) / 6)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(0.565, 0.06, progress),
                    0.55,
                    0.080,
                    0.33,
                    face_status="unknown",
                    behavior="running",
                    threat_hint="abnormal_activity",
                )
            )
        elif 28 <= t < 34:
            progress = _ease((t - 28) / 6)
            objects.append(
                DemoObject(
                    "person",
                    _lerp(0.08, 0.42, progress),
                    0.58,
                    0.072,
                    0.31,
                    face_status="known",
                    face_name="Layla Nasser",
                    label="Person · authorized",
                )
            )
        return objects

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render(self, elapsed: Optional[float] = None) -> np.ndarray:
        t = self.elapsed() if elapsed is None else elapsed
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        self._draw_background(frame)
        if self.profile_key == "entrance":
            self._draw_entrance(frame, t)
        elif self.profile_key == "perimeter":
            self._draw_perimeter(frame, t)
        elif self.profile_key == "parking":
            self._draw_parking(frame, t)
        else:
            self._draw_vault(frame, t)

        for obj in self.objects(t):
            if obj.kind == "person":
                self._draw_person(frame, obj, t)
            else:
                self._draw_vehicle(frame, obj, t)

        self._draw_hud(frame)
        self._post_process(frame)
        return frame

    # ------------------------------------------------------------------
    def _draw_background(self, frame: np.ndarray) -> None:
        sky = self.meta["sky"]
        horizon = int(self.meta["horizon"] * H)
        sky_top = np.array([max(0, int(c * 0.55)) for c in sky], dtype=np.float32)
        sky_bottom = np.array(sky, dtype=np.float32)
        gradient = np.linspace(0, 1, horizon, dtype=np.float32)[:, None]
        band = sky_top[None, :] * (1 - gradient) + sky_bottom[None, :] * gradient
        frame[:horizon, :, :] = np.repeat(band[:, None, :], W, axis=1).astype(np.uint8)

        ground = np.array(self.meta["ground"], dtype=np.float32)
        bottom = ground * 0.55
        gradient = np.linspace(0, 1, H - horizon, dtype=np.float32)[:, None]
        band = ground[None, :] * (1 - gradient) + bottom[None, :] * gradient
        frame[horizon:, :, :] = np.repeat(band[:, None, :], W, axis=1).astype(np.uint8)

        # Perspective lines
        vanishing = (W // 2, horizon)
        line_color = (48, 54, 60) if not self.night else (30, 40, 40)
        for offset in range(-W, W + 1, 110):
            cv2.line(
                frame,
                vanishing,
                (W // 2 + offset * 3, H),
                line_color,
                1,
                cv2.LINE_AA,
            )
        for index, y in enumerate(range(horizon + 20, H, 42)):
            cv2.line(frame, (0, y), (W, y), line_color, 1, cv2.LINE_AA)

    # ------------------------------------------------------------------
    def _draw_entrance(self, frame: np.ndarray, t: float) -> None:
        horizon = int(self.meta["horizon"] * H)
        # Guard booth
        cv2.rectangle(frame, (70, horizon - 150), (300, horizon + 90), (52, 58, 64), -1)
        cv2.rectangle(frame, (70, horizon - 150), (300, horizon + 90), (36, 40, 46), 2)
        cv2.rectangle(frame, (100, horizon - 125), (270, horizon - 20), (120, 150, 160), -1)
        cv2.putText(frame, "SECURITY", (116, horizon - 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 30, 40), 2)

        # Gate posts + boom barrier
        cv2.rectangle(frame, (455, horizon - 175), (482, horizon + 130), (74, 78, 84), -1)
        cv2.rectangle(frame, (592, horizon - 175), (619, horizon + 130), (74, 78, 84), -1)
        cv2.rectangle(frame, (482, horizon - 175), (592, horizon - 158), (150, 154, 160), -1)
        lift = int(60 + 20 * math.sin(t * 0.4))
        cv2.line(frame, (620, horizon - 120 - lift // 3), (760, horizon - 190 - lift // 3), (40, 40, 210), 6)
        cv2.line(frame, (620, horizon - 120 - lift // 3), (760, horizon - 190 - lift // 3), (190, 40, 40), 2)

        # Road markings
        for index in range(5):
            x = 340 + index * 90
            cv2.line(frame, (x, horizon + 90), (x - 30, H), (150, 155, 160), 3)
        cv2.putText(
            frame, "AUTHORIZED VEHICLES ONLY", (330, horizon + 170),
            cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 184, 190), 1, cv2.LINE_AA,
        )

        # Trees
        for x, scale in ((int(W * 0.86), 1.0), (int(W * 0.93), 0.75)):
            cv2.rectangle(frame, (x, horizon - 60), (x + 10, horizon + 70), (40, 34, 30), -1)
            cv2.circle(frame, (x + 5, horizon - 80), int(58 * scale), (26, 44, 32), -1)
            cv2.circle(frame, (x - 24, horizon - 62), int(38 * scale), (30, 50, 36), -1)

    # ------------------------------------------------------------------
    def _draw_perimeter(self, frame: np.ndarray, t: float) -> None:
        horizon = int(self.meta["horizon"] * H)
        # Moon + glow
        moon = (int(W * 0.82), int(horizon * 0.32))
        glow = frame.copy()
        cv2.circle(glow, moon, 48, (80, 90, 70), -1, cv2.LINE_AA)
        cv2.addWeighted(glow, 0.25, frame, 0.75, 0, frame)
        cv2.circle(frame, moon, 22, (210, 214, 190), -1, cv2.LINE_AA)

        # Treeline
        points = []
        for x in range(0, W + 40, 40):
            height = 30 + int(22 * abs(math.sin(x * 0.013)))
            points.append([x, horizon - height])
        polygon = np.array(points + [[W, horizon], [0, horizon]], dtype=np.int32)
        cv2.fillPoly(frame, [polygon], (18, 26, 24))

        # Fence
        fence_color = (70, 82, 78)
        for x in range(0, W, 64):
            cv2.line(frame, (x, horizon - 55), (x, horizon + 120), fence_color, 2)
        for y in (horizon - 42, horizon + 20, horizon + 80):
            cv2.line(frame, (0, y), (W, y), fence_color, 2)
        for x in range(0, W - 64, 64):
            cv2.line(frame, (x, horizon - 42), (x + 64, horizon + 20), (54, 64, 60), 1)
            cv2.line(frame, (x + 64, horizon - 42), (x, horizon + 20), (54, 64, 60), 1)
        # Warning sign
        cv2.rectangle(frame, (70, horizon + 40), (250, horizon + 120), (30, 40, 70), -1)
        cv2.rectangle(frame, (70, horizon + 40), (250, horizon + 120), (60, 80, 160), 2)
        cv2.putText(frame, "RESTRICTED", (88, horizon + 78), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 210, 240), 1, cv2.LINE_AA)
        cv2.putText(frame, "AREA", (140, horizon + 105), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 210, 240), 1, cv2.LINE_AA)
        # Security lamp
        cv2.line(frame, (760, horizon + 100), (760, horizon - 90), (60, 66, 60), 4)
        lamp = frame.copy()
        cv2.circle(lamp, (760, horizon - 100), 60, (60, 90, 90), -1, cv2.LINE_AA)
        cv2.addWeighted(lamp, 0.22, frame, 0.78, 0, frame)

    # ------------------------------------------------------------------
    def _draw_parking(self, frame: np.ndarray, t: float) -> None:
        horizon = int(self.meta["horizon"] * H)
        # Parking bays
        for index in range(-1, 7):
            x1 = int(W * 0.08 + index * 150)
            x2 = int(W * 0.08 + index * 150 + 95)
            cv2.line(frame, (x1, horizon + 70), (x2 + 40, H), (120, 122, 126), 2)
            cv2.line(frame, (x2, horizon + 70), (x2 + 90, H), (120, 122, 126), 2)
        # Static parked cars
        for index, (x, y, color) in enumerate(
            ((0.16, 0.66, (56, 62, 78)), (0.79, 0.68, (60, 52, 52)))
        ):
            self._draw_car_shape(frame, x, y, 0.20, 0.13, color, lights=False)
            cv2.putText(
                frame, f"P-{index + 3:02d}", (int(x * W) + 10, int(y * H) + 22),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (170, 178, 184), 1, cv2.LINE_AA,
            )
        # Lamp posts
        for x in (0.05, 0.5, 0.95):
            px = int(x * W)
            cv2.line(frame, (px, horizon + 110), (px, horizon - 120), (52, 56, 58), 4)
            glow = frame.copy()
            cv2.circle(glow, (px, horizon - 126), 70, (70, 90, 90), -1, cv2.LINE_AA)
            cv2.addWeighted(glow, 0.18, frame, 0.82, 0, frame)
            cv2.circle(frame, (px, horizon - 126), 8, (190, 210, 210), -1)
        cv2.putText(frame, "STAFF PARKING", (40, horizon + 150), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (160, 170, 180), 1, cv2.LINE_AA)

    # ------------------------------------------------------------------
    def _draw_vault(self, frame: np.ndarray, t: float) -> None:
        horizon = int(self.meta["horizon"] * H)
        # Corridor walls converging to the vault door
        cv2.line(frame, (0, 0), (int(W * 0.38), horizon), (40, 52, 52), 3)
        cv2.line(frame, (W, 0), (int(W * 0.62), horizon), (40, 52, 52), 3)
        door = (int(W * 0.38), horizon - 150, int(W * 0.24), 220)
        cv2.rectangle(frame, (door[0], door[1]), (door[0] + door[2], door[1] + door[3]), (62, 68, 70), -1)
        cv2.rectangle(frame, (door[0], door[1]), (door[0] + door[2], door[1] + door[3]), (30, 36, 38), 3)
        cv2.circle(frame, (door[0] + door[2] // 2, door[1] + 40), 8, (40, 220, 220), -1)
        cv2.putText(frame, "VAULT", (door[0] + 48, door[1] + 102), cv2.FONT_HERSHEY_SIMPLEX, 0.72, (180, 190, 190), 2, cv2.LINE_AA)
        cv2.putText(frame, "AUTHORIZED PERSONNEL", (door[0] + 6, door[1] + 132), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (150, 160, 160), 1, cv2.LINE_AA)
        # Red alarm lamp glow
        if int(t) % 6 < 3:
            glow = frame.copy()
            cv2.circle(glow, (door[0] + door[2] // 2, door[1] - 22), 44, (40, 40, 200), -1, cv2.LINE_AA)
            cv2.addWeighted(glow, 0.28, frame, 0.72, 0, frame)
        cv2.circle(frame, (door[0] + door[2] // 2, door[1] - 22), 8, (70, 70, 230), -1)
        # Cones
        for x in (0.24, 0.72):
            px = int(x * W)
            cv2.circle(frame, (px, horizon + 90), 10, (60, 120, 200), -1)
            cv2.line(frame, (px - 10, horizon + 90), (px - 16, horizon + 130), (40, 70, 120), 3)
            cv2.line(frame, (px + 10, horizon + 90), (px + 16, horizon + 130), (40, 70, 120), 3)

    # ------------------------------------------------------------------
    def _draw_person(self, frame: np.ndarray, obj: DemoObject, t: float) -> None:
        x = int(obj.x * W)
        y = int(obj.y * H)
        w = int(obj.w * W)
        h = int(obj.h * H)
        cx = x + w // 2
        top = y

        color = (36, 46, 56) if not self.night else (28, 52, 44)
        rim = (110, 140, 150) if not self.night else (70, 150, 110)
        head_radius = max(5, int(w * 0.30))
        head_center = (cx, top + head_radius + 2)
        hip_y = top + int(h * 0.58)
        swing = math.sin(t * 7 + obj.x * 12) * (w * 0.26)
        if obj.behavior == "running":
            swing *= 1.6
        stride = int(w * 0.22)

        # Legs
        cv2.line(frame, (cx, hip_y), (cx - stride + int(swing), y + h), color, max(4, w // 7), cv2.LINE_AA)
        cv2.line(frame, (cx, hip_y), (cx + stride + int(swing), y + h), color, max(4, w // 7), cv2.LINE_AA)
        # Torso
        cv2.line(frame, (cx, top + head_radius * 2), (cx, hip_y), color, max(7, w // 3), cv2.LINE_AA)
        # Arms
        arm_swing = int(-swing * 0.8)
        cv2.line(frame, (cx, top + head_radius * 2 + 8), (cx - int(w * 0.32), hip_y - int(h * 0.05) + arm_swing), color, max(3, w // 9), cv2.LINE_AA)
        cv2.line(frame, (cx, top + head_radius * 2 + 8), (cx + int(w * 0.32), hip_y - int(h * 0.05) - arm_swing), color, max(3, w // 9), cv2.LINE_AA)
        # Head + rim light
        cv2.circle(frame, head_center, head_radius, color, -1, cv2.LINE_AA)
        cv2.circle(frame, head_center, head_radius, rim, 1, cv2.LINE_AA)
        # Subtle outline to read against the background
        cv2.ellipse(frame, (cx, top + int(h * 0.5)), (int(w * 0.30), int(h * 0.48)), 0, 0, 360, rim, 1, cv2.LINE_AA)

        # Small face marker for unknown identities
        if obj.face_status == "unknown":
            cv2.rectangle(
                frame,
                (cx - head_radius - 3, head_center[1] - head_radius - 3),
                (cx + head_radius + 3, head_center[1] + head_radius + 3),
                (60, 60, 220),
                1,
            )

    def _draw_vehicle(self, frame: np.ndarray, obj: DemoObject, t: float) -> None:
        color = (58, 62, 70) if not self.night else (40, 44, 50)
        self._draw_car_shape(frame, obj.x, obj.y, obj.w, obj.h, color, lights=True)
        # Motion blur hint
        if abs(math.sin(t * 2)) > 0.5:
            cv2.line(
                frame,
                (int(obj.x * W) - 30, int((obj.y + obj.h * 0.6) * H)),
                (int(obj.x * W) + 4, int((obj.y + obj.h * 0.6) * H)),
                (80, 84, 90),
                2,
                cv2.LINE_AA,
            )

    def _draw_car_shape(
        self,
        frame: np.ndarray,
        x: float,
        y: float,
        w: float,
        h: float,
        color: Tuple[int, int, int],
        lights: bool = True,
    ) -> None:
        left = int(x * W)
        top = int(y * H)
        width = int(w * W)
        height = int(h * H)
        if width <= 0 or height <= 0:
            return
        body_h = int(height * 0.55)
        cv2.rectangle(frame, (left, top + height - body_h), (left + width, top + height), color, -1)
        cabin = [
            [int(left + width * 0.18), top + height - body_h],
            [int(left + width * 0.30), top + int(height * 0.12)],
            [int(left + width * 0.70), top + int(height * 0.12)],
            [int(left + width * 0.84), top + height - body_h],
        ]
        cv2.fillPoly(frame, [np.array(cabin, dtype=np.int32)], (color[0] + 10, color[1] + 12, color[2] + 14))
        cv2.polylines(frame, [np.array(cabin, dtype=np.int32)], True, (30, 36, 42), 2, cv2.LINE_AA)
        # Wheels
        radius = max(5, height // 5)
        for wx in (left + int(width * 0.22), left + int(width * 0.78)):
            cv2.circle(frame, (wx, top + height - body_h // 2), radius, (14, 16, 18), -1, cv2.LINE_AA)
        if lights:
            cv2.circle(frame, (left + width - 6, top + height - body_h // 2), 4, (200, 230, 240), -1)
            if self.night:
                beam = frame.copy()
                cv2.fillPoly(
                    beam,
                    [np.array([[left + width, top + height - body_h], [W, top + height - body_h - 30], [W, top + height + 10]], dtype=np.int32)],
                    (60, 90, 100),
                )
                cv2.addWeighted(beam, 0.25, frame, 0.75, 0, frame)

    # ------------------------------------------------------------------
    def _draw_hud(self, frame: np.ndarray) -> None:
        cv2.putText(
            frame,
            "SIMULATED CAMERA FEED · DEMO MODE",
            (18, H - 16),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            (130, 140, 150),
            1,
            cv2.LINE_AA,
        )
        if self.night:
            cv2.putText(
                frame, "IR", (W - 52, H - 16), cv2.FONT_HERSHEY_SIMPLEX,
                0.55, (80, 200, 120), 2, cv2.LINE_AA,
            )

    def _post_process(self, frame: np.ndarray) -> None:
        if self.night:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            tinted = np.stack(
                [np.clip(gray * 0.45, 0, 255), np.clip(gray * 1.02 + 26, 0, 255), np.clip(gray * 0.55, 0, 255)],
                axis=-1,
            ).astype(np.uint8)
            frame[:] = np.clip(frame * 0.25 + tinted * 0.75, 0, 255).astype(np.uint8)
        self._grain_tick += 1
        if self._grain is None or self._grain_tick % 4 == 0:
            self._grain = self._rng.normal(0, 4.5, (H // 2, W // 2, 1)).astype(np.float32)
        grain = cv2.resize(self._grain, (W, H), interpolation=cv2.INTER_LINEAR)
        grain = grain.reshape(H, W, 1)
        frame[:] = np.clip(frame.astype(np.float32) + grain, 0, 255).astype(np.uint8)
        # Vignette
        mask = np.ones((H, W), dtype=np.float32)
        cv2.ellipse(mask, (W // 2, H // 2), (int(W * 0.62), int(H * 0.62)), 0, 0, 360, 0.72, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), 60)
        frame[:] = np.clip(frame.astype(np.float32) * mask[..., None], 0, 255).astype(np.uint8)
        # Scanlines
        frame[::3] = (frame[::3] * 0.94).astype(np.uint8)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------
def build_demo_scene(camera_id: int, code: str = "CAM-01") -> DemoScene:
    return DemoScene(camera_id=camera_id, code=code)


def demo_objects(camera_id: int, elapsed: float) -> List[DemoObject]:
    scene = DemoScene(camera_id=camera_id)
    return scene.objects(elapsed)


__all__ = ["DemoScene", "DemoObject", "build_demo_scene", "demo_objects", "PROFILE_ORDER"]
