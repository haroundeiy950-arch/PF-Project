"""Tests for the transparent, weighted Risk Score engine."""

from __future__ import annotations

from backend.constants import DEFAULT_RISK_WEIGHTS
from backend.services.risk import (
    RiskFactors,
    clean_weights,
    evaluate_risk,
    factor_table,
    level_for_score,
    validate_weights,
)


def test_low_risk_public_zone_is_normal():
    result = evaluate_risk(
        RiskFactors(
            zone_type="public",
            target_type="person",
            hour=13,
            dwell_seconds=0.5,
            face_status="known",
            repetition=1,
            behavior="normal",
        )
    )
    assert result.level == "normal"
    assert 0 <= result.score < 30
    assert "repeated 1 time" in result.explanation
    assert "behavior analysis" not in result.explanation


def test_critical_intrusion_scores_high():
    result = evaluate_risk(
        RiskFactors(
            zone_type="restricted",
            target_type="person",
            hour=2,
            dwell_seconds=12,
            dwell_target=2,
            face_status="unknown",
            repetition=3,
            behavior="running",
        )
    )
    assert result.score >= 85
    assert result.level == "critical"
    assert result.contributions["zone"] == 30
    assert "restricted zone is high sensitivity" in result.explanation
    assert "outside normal hours" in result.explanation
    assert "behavior analysis flagged 'running'" in result.explanation


def test_score_is_always_capped_to_100():
    result = evaluate_risk(
        RiskFactors(
            zone_type="restricted",
            target_type="vehicle",
            hour=23,
            dwell_seconds=999,
            dwell_target=1,
            face_status="unknown",
            repetition=99,
            behavior="erratic",
        ),
        weights={name: 100 for name in DEFAULT_RISK_WEIGHTS},
    )
    assert result.score == 100


def test_face_signal_cannot_trigger_danger_alone():
    result = evaluate_risk(
        RiskFactors(
            zone_type="public",
            target_type="person",
            hour=13,
            dwell_seconds=0,
            face_status="unknown",
            repetition=1,
            behavior="normal",
        ),
        weights={name: 0 for name in DEFAULT_RISK_WEIGHTS} | {"face": 80},
    )
    assert result.contributions["face"] == 5
    assert result.score == 5
    assert result.level == "normal"


def test_normalisation_edge_cases():
    factors = RiskFactors(zone_type="unknown-zone", dwell_target=0, repetition=0)
    normalized = factors.normalized()
    assert set(normalized) == set(DEFAULT_RISK_WEIGHTS)
    assert all(0.0 <= value <= 1.0 for value in normalized.values())
    assert normalized["dwell"] == 0.0
    assert normalized["repetition"] == 0.0


def test_outside_zone_reduces_zone_weight():
    inside = RiskFactors(zone_type="restricted", inside_zone=True).normalized()["zone"]
    outside = RiskFactors(zone_type="restricted", inside_zone=False).normalized()["zone"]
    assert outside == round(inside * 0.25, 10)


def test_threshold_boundaries():
    assert level_for_score(0) == "normal"
    assert level_for_score(29) == "normal"
    assert level_for_score(30) == "medium"
    assert level_for_score(59) == "medium"
    assert level_for_score(60) == "high"
    assert level_for_score(84) == "high"
    assert level_for_score(85) == "critical"
    assert level_for_score(500) == "critical"
    assert level_for_score(90, {"critical": 99}) == "high"


def test_weights_validation_and_cleaning():
    ok, error = validate_weights({"zone": 30})
    assert ok and error == ""
    ok, error = validate_weights({"bogus": 10})
    assert not ok and "Unknown risk factors" in error
    ok, error = validate_weights({name: 0 for name in DEFAULT_RISK_WEIGHTS})
    assert not ok
    ok, error = validate_weights({name: 40 for name in DEFAULT_RISK_WEIGHTS})
    assert not ok and "200" in error

    cleaned = clean_weights({"zone": 999, "target": -5})
    assert cleaned["zone"] == 100
    assert cleaned["target"] == 0
    assert cleaned["dwell"] == DEFAULT_RISK_WEIGHTS["dwell"]


def test_factor_table_is_ui_ready():
    result = evaluate_risk(
        RiskFactors(zone_type="restricted", hour=2, dwell_seconds=5, face_status="unknown")
    )
    table = factor_table(result)
    assert set(table) == set(DEFAULT_RISK_WEIGHTS)
    assert table["zone"]["label"] == "Zone sensitivity"
    assert table["zone"]["contribution"] == result.contributions["zone"]
    assert table["face"]["contribution"] <= 5
