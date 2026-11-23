"""Consistent logging for API, workers and services."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from backend.config import settings

_CONFIGURED = False
_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s"


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    root = logging.getLogger("sentinel")
    root.setLevel(logging.INFO)
    root.propagate = False

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FORMAT, datefmt="%H:%M:%S"))
    root.addHandler(console)

    try:
        log_dir = Path(settings.storage_dir) / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "sentinel.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT, datefmt="%Y-%m-%d %H:%M:%S"))
        root.addHandler(file_handler)
    except OSError:  # pragma: no cover - read-only filesystems
        pass

    _CONFIGURED = True


def get_logger(name: Optional[str] = None) -> logging.Logger:
    _configure_root()
    suffix = name or "app"
    return logging.getLogger(f"sentinel.{suffix}")
