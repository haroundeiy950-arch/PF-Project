"""Bilingual voice warning engine (English + Arabic).

The backend builds the exact warning text stored with every alarm; the browser
performs speech synthesis with the Web Speech API (see the frontend
``VoiceAlertProvider``).  Keeping the text server-side guarantees both
languages always say the same thing and makes the messages auditable.
"""

from __future__ import annotations

from typing import Dict, List

from backend.constants import THREAT_TYPE_LABELS, VOICE_TEMPLATES


def camera_number(code: str) -> str:
    digits = "".join(character for character in (code or "") if character.isdigit())
    if not digits:
        return (code or "1").strip() or "1"
    try:
        return f"{int(digits):02d}"
    except ValueError:
        return digits


def build_voice_text(
    threat_type: str,
    camera_name: str,
    camera_code: str,
    language: str = "en",
) -> str:
    template_set = VOICE_TEMPLATES.get(threat_type) or VOICE_TEMPLATES["abnormal_activity"]
    template = template_set.get("ar" if language.startswith("ar") else "en")
    return template.format(
        camera_name=camera_name,
        camera_number=camera_number(camera_code),
        threat_type=THREAT_TYPE_LABELS.get(threat_type, threat_type),
    )


def build_voice_messages(
    threat_type: str,
    camera_name: str,
    camera_code: str,
    languages: List[str] | None = None,
) -> List[Dict[str, str]]:
    """Return one message per language, English first then Arabic."""
    languages = languages or ["en", "ar"]
    messages: List[Dict[str, str]] = []
    for language in languages:
        messages.append(
            {
                "language": language,
                "text": build_voice_text(threat_type, camera_name, camera_code, language),
                "voice": "ar-SA" if language.startswith("ar") else "en-US",
            }
        )
    return messages


def incident_title(threat_type: str, camera_name: str) -> str:
    label = THREAT_TYPE_LABELS.get(threat_type, "Security event")
    return f"{label} — {camera_name}"
