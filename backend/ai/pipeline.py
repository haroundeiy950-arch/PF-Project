"""Per-camera AI pipeline worker.

Pipeline stages (mirrors Section 9 of the document):

    stream → motion/objects → face → tracking → verification → risk score
           → visual threat → alarm chain → evidence → WebSocket

The worker runs in its own thread and owns a database-agnostic view of the
camera.  Short database sessions are opened only when state changes.
"""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import cv2 # type: ignore
import numpy as np
from sqlalchemy import select # type: ignore

from backend.ai.continuous import ContinuousRecorder
from backend.ai.detector import Detection, build_detector
from backend.ai.discovery import has_signal
from backend.ai.face import FaceEngine, FaceMatch, get_face_engine
from backend.ai.recorder import Recorder
from backend.ai.source import FrameSource, OpenCVSource, build_source
from backend.ai.tracker import IouTracker, Track
from backend.config import settings
from backend.constants import (
    DEFAULT_RISK_WEIGHTS,
    DEFAULT_VERIFICATION,
    RISK_THRESHOLDS,
    THREAT_TYPE_LABELS,
)
from backend.database import session_scope
from backend.models import AuthorizedPerson, Camera, Incident, Recording, Zone
from backend.realtime import manager
from backend.services import alarm, app_settings, imaging, storage, zones
from backend.services.crypto import decrypt_bytes
from backend.services.risk import RiskFactors, RiskResult, evaluate_risk
from backend.services.verification import IncidentGate
from backend.utils.geometry import bbox_center
from backend.utils.logging import get_logger
from backend.utils.time_utils import now

log = get_logger("ai.pipeline")


# ---------------------------------------------------------------------------
# Runtime view of a camera (thread-safe snapshot for streaming)
# ---------------------------------------------------------------------------
class CameraRuntime:
    def __init__(self, camera: Dict[str, Any]) -> None:
        self.camera = camera
        self.camera_id = int(camera["id"])
        self._lock = threading.Lock()
        self.latest_jpeg: Optional[bytes] = None
        self.detections: List[Dict[str, Any]] = []
        self.status: str = "starting"
        self.error: str = ""
        self.fps: float = 0.0
        self.frames: int = 0
        self.threat_level: str = "normal"
        self.risk_score: int = 0
        self.last_frame_at = None
        self.started_at = now()
        self.worker: Optional["CameraWorker"] = None

    def publish(
        self,
        jpeg: bytes,
        detections: List[Dict[str, Any]],
        fps: float,
        threat_level: str = "normal",
        risk_score: int = 0,
    ) -> None:
        with self._lock:
            self.latest_jpeg = jpeg
            self.detections = detections
            self.fps = fps
            self.threat_level = threat_level
            self.risk_score = risk_score
            self.frames += 1
            self.last_frame_at = now()

    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self.latest_jpeg

    def get_meta(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "fps": self.fps,
                "frames": self.frames,
                "threat_level": self.threat_level,
                "risk_score": self.risk_score,
                "last_frame_at": self.last_frame_at.isoformat() if self.last_frame_at else None,
            }

    def set_status(self, status: str, error: str = "") -> None:
        changed = status != self.status or error != self.error
        self.status = status
        self.error = error
        if changed:
            manager.broadcast_threadsafe(
                "camera.status",
                {
                    "camera_id": self.camera_id,
                    "code": self.camera.get("code"),
                    "status": status,
                    "error": error,
                    "fps": round(self.fps, 1),
                },
            )

    def as_dict(self) -> Dict[str, Any]:
        meta = self.get_meta()
        return {
            **self.camera,
            "runtime_status": self.status,
            "runtime_fps": round(meta["fps"], 1),
            "runtime_frames": meta["frames"],
            "runtime_threat_level": meta["threat_level"],
            "runtime_risk_score": meta["risk_score"],
            "error": self.error,
        }


# ---------------------------------------------------------------------------
# Camera worker
# ---------------------------------------------------------------------------
class CameraWorker(threading.Thread):
    def __init__(self, runtime: CameraRuntime) -> None:
        super().__init__(name=f"camera-{runtime.camera_id}", daemon=True)
        self.runtime = runtime
        self.camera = runtime.camera
        self.camera_id = runtime.camera_id
        self.stop_event = threading.Event()

        self.source: Optional[FrameSource] = None
        self.detector = None
        self.tracker = IouTracker()
        self.gate = IncidentGate()
        self.recorder = Recorder(self.camera_id, fps=int(self.camera.get("fps", settings.target_fps)))
        self.continuous = ContinuousRecorder(
            self.camera_id,
            str(self.camera.get("code", f"CAM-{self.camera_id:02d}")),
            fps=int(self.camera.get("fps", settings.target_fps)),
        )
        self.face_engine: Optional[FaceEngine] = None
        self._gallery: List[tuple[str, np.ndarray]] = []
        self._last_gallery_load = 0.0
        self._last_settings_load = 0.0
        self._logged_tracks: Dict[str, float] = {}
        self._recent: Dict[tuple, List[float]] = {}
        self._last_merge: Dict[int, float] = {}
        self._banner_until = 0.0
        self._banner_text = ""
        self._risk_weights = dict(DEFAULT_RISK_WEIGHTS)
        self._risk_thresholds = dict(RISK_THRESHOLDS)
        self._verification = dict(DEFAULT_VERIFICATION)
        self._fps_window: deque = deque(maxlen=24)
        self._last_frame_size = (settings.frame_width, settings.frame_height)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self.stop_event.set()

    # ------------------------------------------------------------------
    def run(self) -> None:  # noqa: C901 - pipeline orchestration
        log.info("Starting camera worker %s (%s)", self.camera.get("code"), self.camera.get("name"))
        try:
            self.source = build_source(SimpleNamespace(**self.camera))
        except Exception as exc:
            log.error("Camera %s could not open source: %s", self.camera_id, exc)
            self.runtime.set_status("offline", str(exc))
            return

        if isinstance(self.source, OpenCVSource) and self.source.capture is None:
            self.runtime.set_status("connecting", "Waiting for the camera device")
        else:
            self.runtime.set_status("online")
        if self.source.detections() is None:
            self.detector = build_detector(self.camera.get("detector_mode"))
        if settings.face_recognition_enabled:
            self.face_engine = get_face_engine()

        self._load_settings(force=True)
        self._load_gallery(force=True)

        fps_target = max(1, int(self.camera.get("fps", settings.target_fps)))
        frame_interval = 1.0 / fps_target
        last_loop = time.monotonic()
        blank_since: Optional[float] = None

        while not self.stop_event.is_set():
            loop_start = time.monotonic()
            try:
                frame = self.source.read() if self.source else None
                if frame is None:
                    self.runtime.set_status("offline", "No frames received")
                    self._publish_placeholder("NO SIGNAL")
                    time.sleep(0.8)
                    continue

                # In live mode a connected but black sensor must be reported as
                # "no signal" instead of a healthy online camera.  The frame is
                # still streamed (with a warning) so the operator can see the
                # device state immediately and the recorder never has a gap.
                if not settings.live_only or has_signal(frame):
                    blank_since = None
                    self.runtime.set_status("online")
                elif blank_since is None:
                    blank_since = time.monotonic()
                elif time.monotonic() - blank_since > 1.5:
                    self.runtime.set_status("offline", "Camera is connected but shows no image")
                frame = self._fit_frame(frame)
                stamp = now()
                raw_detections = self.source.detections() if self.source else None
                if raw_detections is None and self.detector is not None:
                    raw_detections = self.detector.detect(frame)
                detections = raw_detections or []

                if time.monotonic() - self._last_settings_load > 15:
                    self._load_settings()
                if time.monotonic() - self._last_gallery_load > 60:
                    self._load_gallery()

                tracks = self.tracker.update(detections, stamp)

                for track in tracks:
                    try:
                        self._process_track(frame, track, stamp)
                    except Exception as exc:  # keep one bad track from killing the feed
                        log.warning("Track processing error on %s: %s", self.camera.get("code"), exc)

                self._update_overlay(frame, tracks, self._compute_fps(loop_start))
                stream_jpeg = self.runtime.get_jpeg()
                if stream_jpeg:
                    # Event clips capture incidents; the continuous recorder
                    # preserves every second in between.
                    self.continuous.push(stream_jpeg, stamp)
                    self.recorder.push(stream_jpeg, stamp)

                self._prune_state()

                elapsed = time.monotonic() - loop_start
                sleep_for = max(0.0, frame_interval - elapsed)
                if sleep_for:
                    time.sleep(sleep_for)
            except Exception as exc:  # pragma: no cover - defensive
                log.exception("Camera worker %s failed: %s", self.camera_id, exc)
                self.runtime.set_status("degraded", str(exc))
                time.sleep(1.0)

        self.continuous.close()
        if self.source:
            self.source.close()
        self.runtime.set_status("stopped")
        log.info("Camera worker %s stopped", self.camera.get("code"))

    # ------------------------------------------------------------------
    def _fit_frame(self, frame: np.ndarray) -> np.ndarray:
        width = settings.frame_width
        height = settings.frame_height
        if frame.shape[1] != width or frame.shape[0] != height:
            frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
        self._last_frame_size = (width, height)
        return frame

    # ------------------------------------------------------------------
    def _compute_fps(self, loop_start: float) -> float:
        self._fps_window.append(time.monotonic() - loop_start)
        if len(self._fps_window) < 3:
            return 0.0
        average = sum(self._fps_window) / len(self._fps_window)
        return round(1.0 / average, 1) if average > 0 else 0.0

    # ------------------------------------------------------------------
    def _publish_placeholder(self, text: str) -> None:
        width, height = self._last_frame_size
        frame = imaging.placeholder_image(width, height, text)
        camera_name = self.camera.get("name", "Camera")
        code = self.camera.get("code", "CAM")
        imaging.draw_header(frame, camera_name, code, self.camera.get("location", ""))
        jpeg = imaging.encode_jpeg(frame, quality=70)
        self.runtime.publish(jpeg, [], 0.0, "normal", 0)

    # ------------------------------------------------------------------
    def _update_overlay(self, frame: np.ndarray, tracks: Sequence[Track], fps: float) -> None:
        detections: List[Dict[str, Any]] = []
        for track in tracks:
            zone = zones.zone_cache.find_zone(self.camera_id, bbox_center(track.bbox))
            detections.append(
                {
                    "bbox": track.bbox,
                    "target_type": track.target_type,
                    "label": f"{track.target_type.title()} {track.id.split('-')[-1]}",
                    "zone_type": zone.zone_type if zone else None,
                }
            )

        banner = None
        threat_level = "normal"
        score = 0
        if time.monotonic() < self._banner_until:
            banner = self._banner_text
            threat_level = self.runtime.threat_level
            score = self.runtime.risk_score

        annotated = imaging.annotate_frame(
            frame,
            self.camera,
            zones.zone_cache.zones_for(self.camera_id),
            detections,
            threat_level,
            score or None,
            banner,
        )
        if threat_level == "critical":
            imaging.draw_danger_overlay(
                annotated,
                "DANGER",
                THREAT_TYPE_LABELS.get(
                    self.runtime.camera.get("__last_threat__", "restricted_intrusion"),
                    "Security threat",
                ),
            )
        if settings.live_only and not banner:
            height, width = annotated.shape[:2]
            cv2.rectangle(annotated, (0, height - 30), (width, height), (10, 14, 20), -1)
            continuous = settings.continuous_recording_enabled
            event_saving = settings.evidence_enabled and settings.recording_enabled
            no_image = not has_signal(frame)
            if no_image:
                footer = "NO IMAGE FROM DEVICE  •  CHECK CAMERA / WINDOW PRIVACY SETTINGS"
                color = (100, 160, 240)
            elif continuous and event_saving:
                footer = "LIVE  •  CONTINUOUS + EVENT EVIDENCE SAVED"
                color = (120, 230, 160)
            elif continuous:
                footer = "LIVE  •  CONTINUOUS RECORDING"
                color = (120, 230, 160)
            elif event_saving:
                footer = "LIVE  •  EVENT SNAPSHOTS + CLIPS SAVED"
                color = (120, 230, 160)
            else:
                footer = "LIVE  •  NOT RECORDED"
                color = (160, 178, 194)
            cv2.putText(
                annotated,
                footer,
                (16, height - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.42,
                color,
                1,
                cv2.LINE_AA,
            )
        jpeg = imaging.encode_jpeg(annotated, quality=82)
        self.runtime.publish(jpeg, detections, fps, threat_level, score)

    # ------------------------------------------------------------------
    def _process_track(self, frame: np.ndarray, track: Track, stamp) -> None:
        center = bbox_center(track.bbox)
        zone = zones.zone_cache.find_zone(self.camera_id, center)
        zone_type = zone.zone_type if zone else "public"

        # Public space without a configured zone: only unusual behaviour counts.
        if zone is None and track.target_type == "person" and track.dwell_seconds < 6:
            self._log_normal_event(frame, track, zone, stamp)
            return

        schedule_ok = True
        if zone is not None:
            schedule_ok = zones.schedule_active(
                zone.schedule_start, zone.schedule_end, zone.days, stamp
            )
        min_frames = zone.min_frames if zone else self._verification.get("min_frames", 6)
        min_dwell = (
            zone.min_dwell_seconds if zone else self._verification.get("min_dwell_seconds", 2.0)
        )

        reason = self.gate.check_rules(
            frames_seen=track.hits,
            dwell_seconds=track.dwell_seconds,
            min_frames=min_frames,
            min_dwell_seconds=min_dwell,
            schedule_ok=schedule_ok,
            zone_enabled=zone.is_enabled if zone else True,
        )
        if reason is not None:
            if reason == "dwell_pending" or reason == "outside_schedule":
                self._log_normal_event(frame, track, zone, stamp)
            return

        face_status = track.face_status
        if (
            self.face_engine is not None
            and self._gallery
            and track.hits == max(1, min_frames)
            and track.target_type == "person"
        ):
            match: FaceMatch = self.face_engine.analyze(
                frame, track.bbox, self._gallery, settings.face_match_threshold
            )
            if match.status != "none":
                track.face_status = match.status
                track.face_name = match.name
                face_status = match.status

        behavior = track.inferred_behavior()
        night = (
            track.night
            if track.night is not None
            else (stamp.hour >= 19 or stamp.hour < 6)
        )
        key = (self.camera_id, zone.id if zone else None, zone_type)
        repetition = self._repetition_count(key) + 1

        factors = RiskFactors(
            zone_type=zone_type,
            target_type=track.target_type,
            hour=0 if night else stamp.hour,
            dwell_seconds=track.dwell_seconds,
            dwell_target=max(1.0, min_dwell),
            face_status=face_status,
            repetition=repetition,
            behavior=behavior,
            inside_zone=zone is not None,
        )
        risk = evaluate_risk(factors, self._risk_weights, self._risk_thresholds)
        threat_type = self._threat_type(track, zone_type, behavior, risk)

        if risk.level == "normal" or threat_type == "motion":
            self._log_normal_event(frame, track, zone, stamp)
            return

        group_key = (self.camera_id, zone.id if zone else None, threat_type, track.id)
        decision = self.gate.register(stamp, key, group_key, risk.level, 0)
        if decision.action == "suppress":
            return

        if decision.action == "update" and decision.incident_id:
            last_merge = self._last_merge.get(decision.incident_id, 0.0)
            if time.monotonic() - last_merge >= 5.0:
                self._last_merge[decision.incident_id] = time.monotonic()
                self._merge_incident(decision.incident_id, track, zone, risk, behavior, stamp)
            return

        incident_id = self._create_incident_from_track(
            frame, track, zone, risk, threat_type, face_status, behavior, stamp
        )
        if incident_id:
            self.gate.bind(stamp, key, group_key, risk.level, incident_id)
            self._record_repetition(key)
            self._banner_until = time.monotonic() + 10
            self._banner_text = (
                f"{risk.level.upper()} · {risk.score}/100 · "
                f"{THREAT_TYPE_LABELS.get(threat_type, threat_type)}"
            )
            self.runtime.threat_level = risk.level
            self.runtime.risk_score = risk.score
            self.runtime.camera["__last_threat__"] = threat_type

    # ------------------------------------------------------------------
    def _threat_type(self, track: Track, zone_type: str, behavior: str, risk: RiskResult) -> str:
        if track.threat_hint:
            return track.threat_hint
        if zone_type == "restricted":
            return "vehicle_intrusion" if track.target_type == "vehicle" else "restricted_intrusion"
        if track.target_type == "vehicle" and zone_type == "limited" and risk.level in {"high", "critical"}:
            return "vehicle_intrusion"
        if track.face_status == "unknown":
            if behavior == "loitering":
                return "loitering"
            if behavior in {"running", "erratic"}:
                return "abnormal_activity"
            return "unknown_face"
        if behavior in {"running", "erratic"}:
            return "abnormal_activity"
        if behavior == "loitering":
            return "loitering"
        if zone_type == "limited":
            return "abnormal_activity"
        return "motion"

    # ------------------------------------------------------------------
    def _render_snapshot(
        self,
        frame: np.ndarray,
        track: Track,
        zone,
        risk: RiskResult,
        threat_type: str,
    ) -> np.ndarray:
        snapshot = frame.copy()
        for item in zones.zone_cache.zones_for(self.camera_id):
            imaging.draw_zone(snapshot, item.points, f"{item.name} · {item.zone_type}", item.zone_type, item.color)
        imaging.draw_detection(
            snapshot,
            track.bbox,
            f"{track.target_type.upper()} · {risk.score}/100",
            imaging.RED if risk.level in {"high", "critical"} else imaging.AMBER,
            thickness=3,
        )
        imaging.draw_header(
            snapshot,
            self.camera.get("name", "Camera"),
            self.camera.get("code", "CAM"),
            self.camera.get("location", ""),
            risk.level,
            risk.score,
        )
        if risk.level in {"high", "critical"}:
            imaging.draw_danger_overlay(
                snapshot,
                "DANGER" if risk.level == "critical" else "ALERT",
                THREAT_TYPE_LABELS.get(threat_type, threat_type),
            )
        return snapshot

    # ------------------------------------------------------------------
    def _create_incident_from_track(
        self,
        frame: np.ndarray,
        track: Track,
        zone,
        risk: RiskResult,
        threat_type: str,
        face_status: str,
        behavior: str,
        stamp,
    ) -> Optional[int]:
        snapshot = self._render_snapshot(frame, track, zone, risk, threat_type)
        payload: Dict[str, Any] = {}
        incident_id = 0
        code = ""
        snapshot_rel = ""

        try:
            with session_scope() as db:
                camera = db.get(Camera, self.camera_id)
                if camera is None:
                    return None
                zone_model = db.get(Zone, zone.id) if zone else None
                incident = alarm.create_incident(
                    db,
                    camera,
                    threat_type=threat_type,
                    risk=risk,
                    target_type=track.target_type,
                    track_id=track.id,
                    face_status=face_status,
                    zone=zone_model,
                    snapshot_path="",
                    detected_at=stamp,
                    factors={
                        "behavior": behavior,
                        "dwell_seconds": round(track.dwell_seconds, 2),
                        "frames_seen": track.hits,
                        "face_name": track.face_name,
                        "night": bool(track.night),
                    },
                    meta={
                        "bbox": track.bbox,
                        "track_id": track.id,
                        "behavior": behavior,
                        "confidence": track.confidence,
                    },
                )
                incident_id = incident.id
                code = incident.code
                snapshot_rel = imaging.save_snapshot(snapshot, incident.code)
                incident.snapshot_path = snapshot_rel
                event = alarm.create_event(
                    db,
                    camera,
                    event_type=threat_type,
                    target_type=track.target_type,
                    confidence=track.confidence,
                    bbox=track.bbox,
                    track_id=track.id,
                    zone=zone_model,
                    is_threat=True,
                    snapshot_path=snapshot_rel,
                    incident_id=incident.id,
                    meta={
                        "risk_score": risk.score,
                        "level": risk.level,
                        "behavior": behavior,
                        "face_status": face_status,
                    },
                    occurred_at=stamp,
                )
                db.flush()
                payload = alarm.incident_payload(incident, camera, zone_model)
                _ = event

            self.recorder.request_clip(
                incident_id,
                code,
                snapshot_rel,
                self.runtime.get_jpeg,
                stamp,
            )
            manager.broadcast_threadsafe("incident.created", payload)
            manager.broadcast_threadsafe("stats.refresh", {"reason": "incident"})
            log.warning(
                "INCIDENT %s · %s · %s · score=%s · camera=%s",
                code,
                threat_type,
                risk.level,
                risk.score,
                self.camera.get("code"),
            )
            return incident_id
        except Exception as exc:
            log.exception("Could not create incident: %s", exc)
            return None

    # ------------------------------------------------------------------
    def _merge_incident(
        self,
        incident_id: int,
        track: Track,
        zone,
        risk: RiskResult,
        behavior: str,
        stamp,
    ) -> None:
        try:
            with session_scope() as db:
                incident = db.get(Incident, incident_id)
                if incident is None:
                    return
                incident_type = incident.incident_type
                camera = db.get(Camera, self.camera_id)
                zone_model = db.get(Zone, zone.id) if zone else None
                event = alarm.create_event(
                    db,
                    camera,
                    event_type=incident_type,
                    target_type=track.target_type,
                    confidence=track.confidence,
                    bbox=track.bbox,
                    track_id=track.id,
                    zone=zone_model,
                    is_threat=True,
                    incident_id=incident.id,
                    meta={"merged": True, "behavior": behavior},
                    occurred_at=stamp,
                )
                alarm.add_event_to_incident(db, incident, event, risk, escalate=risk.level == "critical")
                db.flush()
                payload = alarm.incident_payload(incident, camera, zone_model)
                event_payload = alarm.event_payload(event, camera)
            manager.broadcast_threadsafe("incident.updated", payload)
            manager.broadcast_threadsafe("event.created", event_payload)
            self._banner_until = time.monotonic() + 8
            self._banner_text = (
                f"{risk.level.upper()} · {risk.score}/100 · "
                f"{THREAT_TYPE_LABELS.get(incident_type, incident_type)}"
            )
            self.runtime.threat_level = risk.level
            self.runtime.risk_score = risk.score
        except Exception as exc:
            log.warning("Could not merge incident %s: %s", incident_id, exc)

    # ------------------------------------------------------------------
    def _log_normal_event(self, frame: np.ndarray, track: Track, zone, stamp) -> None:
        identifier = track.id
        if identifier in self._logged_tracks:
            return
        self._logged_tracks[identifier] = time.monotonic()
        event_type = "motion" if track.is_motion else (
            "vehicle" if track.target_type == "vehicle" else "person"
        )
        try:
            with session_scope() as db:
                camera = db.get(Camera, self.camera_id)
                if camera is None:
                    return
                zone_model = db.get(Zone, zone.id) if zone else None
                event = alarm.create_event(
                    db,
                    camera,
                    event_type=event_type,
                    target_type=track.target_type,
                    confidence=track.confidence,
                    bbox=track.bbox,
                    track_id=track.id,
                    zone=zone_model,
                    is_threat=False,
                    meta={
                        "behavior": track.inferred_behavior(),
                        "face_status": track.face_status,
                        "face_name": track.face_name,
                        "dwell_seconds": round(track.dwell_seconds, 1),
                    },
                    occurred_at=stamp,
                )
                # "Save anything that happens": ordinary motion and person
                # events get a JPEG in the archive even when no alarm is raised.
                if (
                    settings.live_only
                    and settings.evidence_enabled
                    and settings.save_motion_snapshots
                ):
                    try:
                        snapshot = frame.copy()
                        imaging.draw_detection(
                            snapshot,
                            track.bbox,
                            f"{track.target_type.upper()} · {event_type.upper()}",
                            imaging.CYAN,
                            2,
                        )
                        imaging.draw_header(
                            snapshot, camera.name, camera.code, camera.location
                        )
                        code = (
                            f"EVT-{camera.code}-{stamp.strftime('%Y%m%d%H%M%S')}"
                            f"-{track.id[-4:]}"
                        )
                        snapshot_rel = imaging.save_snapshot(snapshot, code)
                        event.snapshot_path = snapshot_rel
                        db.add(
                            Recording(
                                camera_id=self.camera_id,
                                kind="snapshot",
                                path=snapshot_rel,
                                started_at=stamp,
                                ended_at=stamp,
                                size_bytes=storage.file_size(snapshot_rel),
                            )
                        )
                    except Exception as exc:  # pragma: no cover - filesystem dependent
                        log.warning("Motion snapshot could not be saved: %s", exc)
                payload = alarm.event_payload(event, camera)
            manager.broadcast_threadsafe("event.created", payload)
        except Exception as exc:
            log.debug("Normal event logging failed: %s", exc)

    # ------------------------------------------------------------------
    def _repetition_count(self, key: tuple) -> int:
        window = self._recent.get(key) or []
        cutoff = time.monotonic() - 300
        window = [entry for entry in window if entry >= cutoff]
        self._recent[key] = window
        return len(window)

    def _record_repetition(self, key: tuple) -> None:
        self._recent.setdefault(key, []).append(time.monotonic())

    def _prune_state(self) -> None:
        if len(self._logged_tracks) > 400:
            cutoff = sorted(self._logged_tracks.values())[200]
            self._logged_tracks = {
                key: value for key, value in self._logged_tracks.items() if value >= cutoff
            }
        if len(self._recent) > 200:
            self._recent = dict(list(self._recent.items())[-100:])

    # ------------------------------------------------------------------
    def _load_settings(self, force: bool = False) -> None:
        try:
            with session_scope() as db:
                config = app_settings.runtime_alarm_config(db)
            self._risk_weights = config.get("risk_weights", dict(DEFAULT_RISK_WEIGHTS))
            self._risk_thresholds = config.get("risk_thresholds", dict(RISK_THRESHOLDS))
            self._verification = {
                **DEFAULT_VERIFICATION,
                **(config.get("verification") or {}),
            }
            self._last_settings_load = time.monotonic()
        except Exception as exc:
            log.warning("Could not load runtime settings: %s", exc)

    def _load_gallery(self, force: bool = False) -> None:
        self._last_gallery_load = time.monotonic()
        if self.face_engine is None:
            return
        try:
            gallery: List[tuple[str, np.ndarray]] = []
            with session_scope() as db:
                people = db.scalars(
                    select(AuthorizedPerson).where(
                        AuthorizedPerson.is_active.is_(True),
                        AuthorizedPerson.consent_given.is_(True),
                    )
                ).all()
                for person in people:
                    raw = decrypt_bytes(person.embedding_encrypted)
                    if not raw:
                        continue
                    try:
                        vector = np.asarray(json.loads(raw.decode("utf-8")), dtype=np.float32)
                    except (ValueError, UnicodeDecodeError):
                        continue
                    if vector.size:
                        gallery.append((person.full_name, vector))
            self._gallery = gallery
            if gallery:
                log.info("Loaded %d authorized face embeddings", len(gallery))
        except Exception as exc:
            log.warning("Could not load face gallery: %s", exc)


__all__ = ["CameraRuntime", "CameraWorker"]
