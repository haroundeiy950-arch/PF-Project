"""Tests for the false-alarm verification gate."""

from __future__ import annotations

from datetime import timedelta

from backend.services.verification import IncidentGate
from backend.utils.time_utils import now


def test_warming_up_and_dwell_rules():
    gate = IncidentGate()
    assert gate.check_rules(0, 0, 6, 2.0, True) == "warming_up"
    assert gate.check_rules(6, 0.5, 6, 2.0, True) == "dwell_pending"
    assert gate.check_rules(6, 2.0, 6, 2.0, True) is None
    assert gate.check_rules(6, 2.0, 6, 2.0, False) == "outside_schedule"
    assert gate.check_rules(6, 2.0, 6, 2.0, True, zone_enabled=False) == "zone_disabled"


def test_new_incident_after_verification():
    gate = IncidentGate()
    decision = gate.register(now(), ("cam", "zone", "type"), ("cam", "track"), "high", 10)
    assert decision.action == "new"
    assert decision.incident_id == 10
    assert decision.accepted
    assert decision.reason == "verified"


def test_grouping_within_window_updates_existing_incident():
    gate = IncidentGate(group_window_seconds=120, cooldown_seconds=45)
    current = now()
    gate.register(current, ("cam", "zone", "type"), ("cam", "track"), "high", 10)
    later = current + timedelta(seconds=30)
    decision = gate.register(later, ("cam", "zone", "type"), ("cam", "track"), "high", 999)
    assert decision.action == "update"
    assert decision.incident_id == 10
    assert not decision.escalate


def test_grouping_escalates_when_level_increases():
    gate = IncidentGate(group_window_seconds=120, cooldown_seconds=45)
    current = now()
    gate.register(current, ("cam", "zone", "type"), ("cam", "track"), "high", 10)
    decision = gate.register(
        current + timedelta(seconds=10), ("cam", "zone", "type"), ("cam", "track"), "critical", 11
    )
    assert decision.action == "update"
    assert decision.incident_id == 10
    assert decision.escalate


def test_cooldown_suppresses_same_key_for_new_target():
    gate = IncidentGate(group_window_seconds=5, cooldown_seconds=90)
    current = now()
    gate.register(current, ("cam", "zone", "type"), ("cam", "track-1"), "high", 10)
    decision = gate.register(
        current + timedelta(seconds=10), ("cam", "zone", "type"), ("cam", "track-2"), "high", 11
    )
    assert decision.action == "suppress"
    assert decision.incident_id == 10
    assert decision.reason == "cooldown_active"
    assert gate.cooldown_remaining(now(), ("cam", "zone", "type")) > 0


def test_cooldown_escalation_allowed():
    gate = IncidentGate(group_window_seconds=5, cooldown_seconds=90)
    current = now()
    gate.register(current, ("cam", "zone", "type"), ("cam", "track-1"), "medium", 10)
    decision = gate.register(
        current + timedelta(seconds=6), ("cam", "zone", "type"), ("cam", "track-2"), "critical", 11
    )
    assert decision.action == "new"
    assert decision.incident_id == 11


def test_cooldown_expires():
    gate = IncidentGate(group_window_seconds=5, cooldown_seconds=10)
    current = now()
    gate.register(current, ("cam", "zone", "type"), ("cam", "track-1"), "high", 10)
    decision = gate.register(
        current + timedelta(seconds=11), ("cam", "zone", "type"), ("cam", "track-2"), "high", 11
    )
    assert decision.action == "new"


def test_bind_and_reset():
    gate = IncidentGate()
    current = now()
    gate.bind(current, ("cam", "zone", "type"), ("cam", "track"), "critical", 42)
    assert gate.cooldown_remaining(current, ("cam", "zone", "type")) > 0
    decision = gate.register(
        current + timedelta(seconds=1), ("cam", "zone", "type"), ("cam", "track"), "critical", 43
    )
    assert decision.action == "update"
    assert decision.incident_id == 42

    gate.reset()
    decision = gate.register(current, ("cam", "zone", "type"), ("cam", "track"), "critical", 44)
    assert decision.action == "new"
