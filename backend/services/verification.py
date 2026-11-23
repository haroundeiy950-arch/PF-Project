"""Verification rules and false-alarm reduction (Section 10).

An intrusion alarm is only considered real after consecutive-frame
confirmation, dwell time, schedule and zone checks.  A cooldown prevents the
same (camera, zone, type) from producing repeated alarms, and consecutive
events for the same target are grouped into a single incident.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional, Tuple

from backend.constants import DEFAULT_VERIFICATION, LEVEL_ORDER


@dataclass
class GateDecision:
    """Outcome of the verification gate."""

    action: str  # "new" | "update" | "suppress"
    incident_id: Optional[int] = None
    reason: str = ""
    escalate: bool = False

    @property
    def accepted(self) -> bool:
        return self.action in {"new", "update"}


class IncidentGate:
    """Keeps verification state in memory for the running pipeline.

    The gate is deliberately independent from the database so it can be unit
    tested easily.  The pipeline stores the returned incident ids.
    """

    def __init__(
        self,
        group_window_seconds: float = DEFAULT_VERIFICATION["group_window_seconds"],
        cooldown_seconds: float = DEFAULT_VERIFICATION["cooldown_seconds"],
    ) -> None:
        self.group_window_seconds = group_window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._groups: Dict[Tuple, Tuple[datetime, int, str]] = {}
        self._cooldowns: Dict[Tuple, Tuple[datetime, int, str]] = {}

    # ------------------------------------------------------------------
    def reset(self) -> None:
        self._groups.clear()
        self._cooldowns.clear()

    # ------------------------------------------------------------------
    def check_rules(
        self,
        frames_seen: int,
        dwell_seconds: float,
        min_frames: int,
        min_dwell_seconds: float,
        schedule_ok: bool,
        zone_enabled: bool = True,
    ) -> Optional[str]:
        """Return a suppression reason when the detection is not yet verified."""
        if not zone_enabled:
            return "zone_disabled"
        if not schedule_ok:
            return "outside_schedule"
        if frames_seen < max(1, int(min_frames)):
            return "warming_up"
        if dwell_seconds < max(0.0, float(min_dwell_seconds)):
            return "dwell_pending"
        return None

    # ------------------------------------------------------------------
    def register(
        self,
        now: datetime,
        key: Tuple,
        group_key: Tuple,
        level: str,
        incident_id: int,
        level_rank: Dict[str, int] = LEVEL_ORDER,
    ) -> GateDecision:
        """Register a verified threat and decide whether to create/update."""
        # Group consecutive detections of the same target into one incident.
        grouped = self._groups.get(group_key)
        if grouped:
            last_seen, group_incident_id, group_level = grouped
            if (now - last_seen).total_seconds() <= self.group_window_seconds:
                escalated = level_rank.get(level, 0) > level_rank.get(group_level, 0)
                self._groups[group_key] = (now, group_incident_id, level)
                self._cooldowns[key] = (now, group_incident_id, level)
                return GateDecision(
                    action="update",
                    incident_id=group_incident_id,
                    reason="grouped_with_existing_incident",
                    escalate=escalated,
                )

        cooled = self._cooldowns.get(key)
        if cooled:
            last_alert, cooldown_incident_id, cooldown_level = cooled
            within_cooldown = (now - last_alert).total_seconds() <= self.cooldown_seconds
            escalating = level_rank.get(level, 0) > level_rank.get(cooldown_level, 0)
            if within_cooldown and not escalating:
                self._groups[group_key] = (now, cooldown_incident_id, cooldown_level)
                return GateDecision(
                    action="suppress",
                    incident_id=cooldown_incident_id,
                    reason="cooldown_active",
                    escalate=False,
                )

        self._cooldowns[key] = (now, incident_id, level)
        self._groups[group_key] = (now, incident_id, level)
        return GateDecision(action="new", incident_id=incident_id, reason="verified")

    # ------------------------------------------------------------------
    def bind(
        self,
        now: datetime,
        key: Tuple,
        group_key: Tuple,
        level: str,
        incident_id: int,
    ) -> None:
        """Attach a newly created database incident id to the gate state."""
        self._cooldowns[key] = (now, incident_id, level)
        self._groups[group_key] = (now, incident_id, level)

    # ------------------------------------------------------------------
    def cooldown_remaining(self, now: datetime, key: Tuple) -> float:
        cooled = self._cooldowns.get(key)
        if not cooled:
            return 0.0
        elapsed = (now - cooled[0]).total_seconds()
        return max(0.0, self.cooldown_seconds - elapsed)
