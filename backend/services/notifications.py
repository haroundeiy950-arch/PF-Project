"""Remote notification service.

Alerts are always stored in the database; when ``WEBHOOK_URL`` is configured a
JSON payload is also forwarded to the administrator's phone or to a remote
monitoring center.  Failures never block the alarm chain.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict

import requests

from backend.config import settings
from backend.utils.logging import get_logger

log = get_logger("notifications")


def _post_webhook(payload: Dict[str, Any]) -> None:
    try:
        response = requests.post(settings.webhook_url, json=payload, timeout=6)
        log.info("Webhook delivered (%s): %s", response.status_code, payload.get("title"))
    except Exception as exc:  # pragma: no cover - network dependent
        log.warning("Webhook delivery failed: %s", exc)


def send_notification(
    title: str,
    message: str,
    level: str = "medium",
    incident_id: int | None = None,
    extra: Dict[str, Any] | None = None,
) -> str:
    """Send a notification asynchronously and return a delivery description."""
    payload = {
        "title": title,
        "message": message,
        "level": level,
        "incident_id": incident_id,
        **(extra or {}),
    }
    log.info("NOTIFICATION [%s] %s — %s", level.upper(), title, message)

    if settings.webhook_url:
        threading.Thread(target=_post_webhook, args=(payload,), daemon=True).start()
        return f"webhook:{settings.webhook_url}"

    print(json.dumps(payload, ensure_ascii=False))
    return "console"


def notification_target() -> str:
    return settings.webhook_url or "local-console"
