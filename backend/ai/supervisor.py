"""Camera supervisor and health monitor.

Owns one worker thread per enabled camera, refreshes the zone cache, records
system health and applies storage retention.  A single instance lives for the
process lifetime.
"""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from typing import Dict, List, Optional

import psutil # type: ignore
from sqlalchemy import delete, select # type: ignore

from backend.ai.live import LiveCameraWorker
from backend.ai.pipeline import CameraRuntime, CameraWorker
from backend.config import settings
from backend.database import session_scope
from backend.models import Camera, SystemHealth
from backend.realtime import manager
from backend.services import imaging, storage, zones
from backend.utils.logging import get_logger
from backend.utils.time_utils import now

log = get_logger("ai.supervisor")


def _camera_dict(camera: Camera) -> Dict:
    return {
        "id": camera.id,
        "name": camera.name,
        "code": camera.code,
        "location": camera.location,
        "source_type": camera.source_type,
        "rtsp_url": camera.rtsp_url,
        "fps": camera.fps,
        "resolution": camera.resolution,
        "notes": camera.notes,
    }


class CameraSupervisor:
    def __init__(self) -> None:
        self.runtimes: Dict[int, CameraRuntime] = {}
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._monitor_thread: Optional[threading.Thread] = None
        self._started = False
        self.started_at = now()
        self.last_health: Dict = {}
        self._last_retention = 0.0
        self._last_db_sync = 0.0

    # ------------------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._started or not settings.pipeline_enabled:
                return
            self._started = True
            self._stop_event.clear()
        try:
            with session_scope() as db:
                zones.zone_cache.refresh(db)
                cameras = db.scalars(
                    select(Camera).where(Camera.is_enabled.is_(True))
                ).all()
                for camera in cameras:
                    self.start_camera(camera)
        except Exception as exc:  # pragma: no cover - startup race
            log.error("Camera supervisor failed to start: %s", exc)

        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, name="camera-supervisor", daemon=True
        )
        self._monitor_thread.start()
        log.info("Camera supervisor started with %d camera(s)", len(self.runtimes))

    # ------------------------------------------------------------------
    def start_camera(self, camera: Camera) -> None:
        if not settings.pipeline_enabled:
            return
        with self._lock:
            if camera.id in self.runtimes:
                return
            runtime = CameraRuntime(_camera_dict(camera))
            # Live-only + no evidence = lightweight direct stream.  As soon as
            # evidence is requested we run the real detector/recorder worker;
            # build_source() still forces a physical webcam in live-only mode.
            if settings.live_only and not settings.evidence_enabled:
                worker_class = LiveCameraWorker
            else:
                worker_class = CameraWorker
            worker = worker_class(runtime)
            runtime.worker = worker
            self.runtimes[camera.id] = runtime
            worker.start()
            log.info("Camera %s started", camera.code)

    # ------------------------------------------------------------------
    def stop_camera(self, camera_id: int, join_timeout: float = 2.0) -> None:
        with self._lock:
            runtime = self.runtimes.pop(camera_id, None)
        if runtime and runtime.worker:
            runtime.worker.stop()
            runtime.worker.join(timeout=join_timeout)
            log.info("Camera %s stopped", runtime.camera.get("code"))

    # ------------------------------------------------------------------
    def restart_camera(self, camera_id: int) -> None:
        self.stop_camera(camera_id)
        with session_scope() as db:
            camera = db.get(Camera, camera_id)
            if camera and camera.is_enabled:
                self.start_camera(camera)

    # ------------------------------------------------------------------
    def sync(self) -> None:
        """Start workers for new cameras and stop removed/disabled ones."""
        with session_scope() as db:
            cameras = db.scalars(select(Camera)).all()
            zones.zone_cache.refresh(db)
        if not settings.pipeline_enabled:
            return
        known_ids = {camera.id for camera in cameras if camera.is_enabled}

        with self._lock:
            active_ids = set(self.runtimes.keys())
        for camera_id in active_ids - known_ids:
            self.stop_camera(camera_id)

        for camera in cameras:
            if camera.is_enabled and camera.id not in active_ids:
                self.start_camera(camera)

    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            ids = list(self.runtimes.keys())
        for camera_id in ids:
            self.stop_camera(camera_id)
        self._started = False
        log.info("Camera supervisor stopped")

    # ------------------------------------------------------------------
    def get(self, camera_id: int) -> Optional[CameraRuntime]:
        return self.runtimes.get(camera_id)

    @property
    def running(self) -> bool:
        return self._started

    def all(self) -> List[CameraRuntime]:
        return list(self.runtimes.values())

    def live_status(self) -> Dict[int, Dict]:
        return {
            camera_id: {
                "status": runtime.status,
                **runtime.get_meta(),
            }
            for camera_id, runtime in self.runtimes.items()
        }

    # ------------------------------------------------------------------
    def health_snapshot(self) -> Dict:
        disk = storage.disk_status()
        statuses = self.live_status()
        online = sum(1 for item in statuses.values() if item["status"] == "online")
        total = len(statuses)
        cpu = psutil.cpu_percent(interval=None)
        memory = psutil.virtual_memory().percent
        if disk["percent"] >= 92 or cpu >= 92 or memory >= 95:
            state = "critical"
        elif disk["percent"] >= 80 or cpu >= 80 or memory >= 85 or online < total:
            state = "warning"
        else:
            state = "healthy"

        payload = {
            "status": state,
            "cpu_percent": round(cpu, 1),
            "memory_percent": round(memory, 1),
            "disk_percent": disk["percent"],
            "storage_gb": disk["storage_gb"],
            "disk_free_gb": disk["free_gb"],
            "cameras_online": online,
            "cameras_total": total,
            "uptime_seconds": int((now() - self.started_at).total_seconds()),
            "websocket_clients": manager.client_count,
            "fps_total": round(sum(item.get("fps", 0) for item in statuses.values()), 1),
            "recorded_today_gb": round(self._storage_today_gb(), 2),
            "cameras": statuses,
            "checked_at": now().isoformat(),
        }
        self.last_health = payload
        return payload

    def _storage_today_gb(self) -> float:
        """Bytes written to ``clips/`` since local midnight, in gigabytes."""
        try:
            midnight = now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
            total = 0
            for path in settings.clips_dir.glob("*"):
                if not path.is_file():
                    continue
                stat = path.stat()
                if stat.st_mtime >= midnight:
                    total += stat.st_size
            return total / (1024**3)
        except OSError:
            return 0.0

    # ------------------------------------------------------------------
    def _monitor_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                with session_scope() as db:
                    zones.zone_cache.refresh(db)
                    self._sync_camera_status(db)
                    self._record_health(db)
                    self._maybe_retention(db)
                payload = self.health_snapshot()
                manager.broadcast_threadsafe("health.updated", payload)
            except Exception as exc:  # pragma: no cover - monitor resilience
                log.warning("Health monitor error: %s", exc)
            self._stop_event.wait(10.0)

    # ------------------------------------------------------------------
    def _sync_camera_status(self, db) -> None:
        cameras = db.scalars(select(Camera)).all()
        for camera in cameras:
            runtime = self.runtimes.get(camera.id)
            if runtime is None:
                if camera.is_enabled and settings.pipeline_enabled:
                    camera.status = "offline"
                continue
            previous = camera.status
            camera.status = runtime.status
            if runtime.get_jpeg() is not None:
                camera.last_seen_at = now()
            if previous != camera.status:
                log.info("Camera %s is now %s", camera.code, camera.status)

    # ------------------------------------------------------------------
    def _record_health(self, db) -> None:
        snapshot = self.health_snapshot()
        max_age = now() - timedelta(days=7)
        if int(time.time()) % 3 == 0:  # roughly every 30 s
            db.add(
                SystemHealth(
                    cpu_percent=snapshot["cpu_percent"],
                    memory_percent=snapshot["memory_percent"],
                    disk_percent=snapshot["disk_percent"],
                    storage_gb=snapshot["storage_gb"],
                    status=snapshot["status"],
                    detail=f"{snapshot['cameras_online']}/{snapshot['cameras_total']} cameras online",
                )
            )
            db.execute(delete(SystemHealth).where(SystemHealth.created_at < max_age))

    # ------------------------------------------------------------------
    def _maybe_retention(self, db) -> None:
        if time.monotonic() - self._last_retention < 3600:
            return
        self._last_retention = time.monotonic()
        try:
            result = storage.purge_expired_recordings(db)
            if result["deleted"]:
                log.info("Retention: %s", result)
        except Exception as exc:  # pragma: no cover
            log.warning("Retention cleanup failed: %s", exc)


supervisor = CameraSupervisor()

__all__ = ["CameraSupervisor", "supervisor"]
