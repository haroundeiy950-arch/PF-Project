"""Domain constants shared by the API, services and the frontend contract.

Keeping these values in one place makes the permission matrix, risk levels and
voice templates auditable against the requirements document.
"""

from __future__ import annotations

from typing import Dict, List

# ---------------------------------------------------------------------------
# Permissions & roles (Section 13 of the requirements document)
# ---------------------------------------------------------------------------
PERMISSIONS: List[str] = [
    "view_live",
    "view_recordings",
    "view_reports",
    "acknowledge_alarms",
    "manage_cameras",
    "manage_zones",
    "manage_faces",
    "manage_users",
    "manage_settings",
    "view_audit",
    "delete_recordings",
    "export_data",
]

ROLE_DEFINITIONS: Dict[str, Dict[str, object]] = {
    "admin": {
        "label": "Administrator",
        "description": "Full control over cameras, zones, people, users and settings.",
        "permissions": list(PERMISSIONS),
    },
    "operator": {
        "label": "Security Operator",
        "description": "Monitors live feeds, acknowledges alarms and reviews incidents.",
        "permissions": [
            "view_live",
            "view_recordings",
            "view_reports",
            "acknowledge_alarms",
            "export_data",
        ],
    },
    "viewer": {
        "label": "Viewer",
        "description": "Read-only access to live streams and limited recordings.",
        "permissions": ["view_live", "view_recordings"],
    },
}

# ---------------------------------------------------------------------------
# Zones, detection types and risk levels
# ---------------------------------------------------------------------------
ZONE_TYPES = ("restricted", "limited", "public")

ZONE_TYPE_LABELS = {
    "restricted": "Restricted area",
    "limited": "Limited access",
    "public": "Public area",
}

THREAT_TYPES = (
    "restricted_intrusion",
    "unknown_face",
    "abnormal_activity",
    "loitering",
    "vehicle_intrusion",
    "door_open",
    "motion",
)

THREAT_TYPE_LABELS = {
    "restricted_intrusion": "Restricted area intrusion",
    "unknown_face": "Unknown face detected",
    "abnormal_activity": "Abnormal activity",
    "loitering": "Loitering",
    "vehicle_intrusion": "Vehicle in restricted area",
    "door_open": "Door opened",
    "motion": "Motion detected",
}

LEVELS = ("normal", "medium", "high", "critical")

LEVEL_LABELS = {
    "normal": "Normal",
    "medium": "Medium danger",
    "high": "High danger",
    "critical": "Severe danger",
}

LEVEL_ORDER = {level: index for index, level in enumerate(LEVELS)}

LEVEL_COLORS = {
    "normal": "#22c55e",
    "medium": "#f59e0b",
    "high": "#fb7185",
    "critical": "#ef4444",
}

# ---------------------------------------------------------------------------
# Risk model (Section 11).  Weights sum to 100 points.
# ---------------------------------------------------------------------------
DEFAULT_RISK_WEIGHTS: Dict[str, int] = {
    "zone": 30,
    "target": 15,
    "time": 15,
    "dwell": 15,
    "face": 5,
    "repetition": 10,
    "behavior": 10,
}

RISK_THRESHOLDS: Dict[str, int] = {
    "medium": 30,
    "high": 60,
    "critical": 85,
}

FACTOR_LABELS = {
    "zone": "Zone sensitivity",
    "target": "Target type",
    "time": "Time of day",
    "dwell": "Dwell time",
    "face": "Face status",
    "repetition": "Event repetition",
    "behavior": "Behavior analysis",
}

ZONE_RISK_BASE = {"restricted": 1.0, "limited": 0.55, "public": 0.12}
TARGET_RISK_BASE = {"person": 0.75, "vehicle": 1.0, "animal": 0.35, "unknown": 0.5}

# ---------------------------------------------------------------------------
# Default verification rules (Section 10)
# ---------------------------------------------------------------------------
DEFAULT_VERIFICATION = {
    "min_frames": 6,
    "min_dwell_seconds": 2.0,
    "cooldown_seconds": 90,
    "group_window_seconds": 120,
    "escalation_only": True,
}

# ---------------------------------------------------------------------------
# Voice warning templates (Section 5.2) — English + Arabic.
# ---------------------------------------------------------------------------
VOICE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "restricted_intrusion": {
        "en": (
            "WARNING! WARNING! Intrusion detected. Unauthorized person in restricted "
            "area. Camera {camera_number}, {camera_name}. Immediate attention required!"
        ),
        "ar": (
            "تحذير! تحذير! تم رصد تسلل. شخص غير مصرح به في منطقة محظورة. "
            "الكاميرا {camera_number}، {camera_name}. مطلوب تدخل فوري!"
        ),
    },
    "unknown_face": {
        "en": (
            "WARNING! Unknown face detected near {camera_name}. Camera {camera_number}. "
            "Please verify the identity of the person."
        ),
        "ar": (
            "تحذير! تم رصد وجه غير معروف قرب {camera_name}. الكاميرا {camera_number}. "
            "يرجى التحقق من هوية الشخص."
        ),
    },
    "abnormal_activity": {
        "en": (
            "WARNING! Abnormal activity detected at {camera_name}. Camera {camera_number}. "
            "Immediate attention required!"
        ),
        "ar": (
            "تحذير! تم رصد نشاط غير طبيعي في {camera_name}. الكاميرا {camera_number}. "
            "مطلوب تدخل فوري!"
        ),
    },
    "loitering": {
        "en": (
            "WARNING! Loitering detected in a restricted area at {camera_name}. "
            "Camera {camera_number}. Please respond."
        ),
        "ar": (
            "تحذير! تم رصد تجول في منطقة محظورة في {camera_name}. "
            "الكاميرا {camera_number}. يرجى الاستجابة."
        ),
    },
    "vehicle_intrusion": {
        "en": (
            "WARNING! Unauthorized vehicle in restricted area at {camera_name}. "
            "Camera {camera_number}. Immediate attention required!"
        ),
        "ar": (
            "تحذير! مركبة غير مصرح بها في منطقة محظورة في {camera_name}. "
            "الكاميرا {camera_number}. مطلوب تدخل فوري!"
        ),
    },
    "door_open": {
        "en": (
            "WARNING! Door opened unexpectedly at {camera_name}. Camera {camera_number}. "
            "Please verify immediately."
        ),
        "ar": (
            "تحذير! تم فتح باب بشكل غير متوقع في {camera_name}. الكاميرا {camera_number}. "
            "يرجى التحقق فورا."
        ),
    },
    "motion": {
        "en": "Motion detected at {camera_name}. Camera {camera_number}.",
        "ar": "تم رصد حركة في {camera_name}. الكاميرا {camera_number}.",
    },
}

ALERT_STATUSES = ("not_started", "playing", "stopped", "acknowledged", "sent", "failed")
INCIDENT_STATUSES = ("open", "acknowledged", "resolved", "false_alarm")
