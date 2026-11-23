"""Optional local siren.

On Windows the siren uses ``winsound``; elsewhere it writes an alert tone to the
terminal.  The siren is always optional (Section 14) and never performs a
dangerous action — it only produces sound.
"""

from __future__ import annotations

import sys
import threading
import time

from backend.config import settings
from backend.utils.logging import get_logger

log = get_logger("siren")
_lock = threading.Lock()
_last_trigger = 0.0


def _beep_windows(frequency: int, duration_ms: int) -> None:
    try:
        import winsound

        winsound.Beep(frequency, duration_ms)
    except Exception:  # pragma: no cover - no audio device
        time.sleep(duration_ms / 1000)


def _siren_loop(duration_seconds: float) -> None:
    end = time.time() + duration_seconds
    while time.time() < end:
        if sys.platform.startswith("win"):
            _beep_windows(880, 220)
            _beep_windows(660, 220)
        else:  # pragma: no cover - non-Windows
            print("\a", end="", flush=True)
            time.sleep(0.45)


def trigger_siren(duration_seconds: float = 3.0, force: bool = False) -> str:
    """Trigger the optional local siren and return a status description."""
    global _last_trigger
    if not settings.siren_enabled and not force:
        return "disabled"
    with _lock:
        if time.time() - _last_trigger < 2.0:
            return "throttled"
        _last_trigger = time.time()
    log.warning("Local siren triggered for %.1fs", duration_seconds)
    threading.Thread(target=_siren_loop, args=(duration_seconds,), daemon=True).start()
    return "playing"
