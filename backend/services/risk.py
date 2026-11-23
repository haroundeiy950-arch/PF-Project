"""Risk Score engine (Section 11 of the requirements document).

The score is a transparent weighted sum from 0 to 100.  Every factor is
normalised to 0..1, multiplied by an adjustable weight and then explained in
plain language so the operator can understand *why* an event was classified as
a threat.  Face recognition is capped at a small weight and can therefore never
trigger a danger alarm on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from backend.constants import (
    DEFAULT_RISK_WEIGHTS,
    FACTOR_LABELS,
    RISK_THRESHOLDS,
    TARGET_RISK_BASE,
    ZONE_RISK_BASE,
)
from backend.utils.geometry import clamp01


@dataclass
class RiskFactors:
    zone_type: str = "public"
    target_type: str = "person"
    hour: int = 12
    dwell_seconds: float = 0.0
    dwell_target: float = 2.0
    face_status: str = "none"  # known | unknown | none
    repetition: int = 1
    behavior: str = "normal"  # normal | approaching | loitering | erratic | running
    inside_zone: bool = True

    def normalized(self) -> Dict[str, float]:
        zone = ZONE_RISK_BASE.get(self.zone_type, 0.12)
        if not self.inside_zone:
            zone *= 0.25

        target = TARGET_RISK_BASE.get(self.target_type, 0.5)

        if self.hour >= 22 or self.hour < 6:
            time_factor = 1.0
        elif 18 <= self.hour < 22 or 6 <= self.hour < 8:
            time_factor = 0.65
        else:
            time_factor = 0.15

        target_dwell = max(float(self.dwell_target or 1.0), 1.0)
        dwell = clamp01(self.dwell_seconds / target_dwell)

        face = {"unknown": 1.0, "none": 0.35}.get(self.face_status, 0.0)
        repetition = clamp01(self.repetition / 3.0)
        behavior = {
            "running": 1.0,
            "erratic": 0.9,
            "loitering": 0.8,
            "approaching": 0.55,
            "normal": 0.0,
        }.get(self.behavior, 0.1)

        return {
            "zone": zone,
            "target": target,
            "time": time_factor,
            "dwell": dwell,
            "face": face,
            "repetition": repetition,
            "behavior": behavior,
        }


@dataclass
class RiskResult:
    score: int
    level: str
    explanation: str
    breakdown: Dict[str, float] = field(default_factory=dict)
    contributions: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "score": self.score,
            "level": self.level,
            "explanation": self.explanation,
            "breakdown": self.breakdown,
            "contributions": self.contributions,
        }


def clean_weights(weights: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Merge user-provided weights with defaults, keeping them sane."""
    merged: Dict[str, int] = {}
    for name, default in DEFAULT_RISK_WEIGHTS.items():
        raw = None if weights is None else weights.get(name)
        try:
            value = int(raw) if raw is not None else default
        except (TypeError, ValueError):
            value = default
        merged[name] = max(0, min(100, value))
    return merged


def validate_weights(weights: Dict[str, Any]) -> Tuple[bool, str]:
    if not isinstance(weights, dict):
        return False, "Weights must be an object keyed by factor name"
    unknown = [key for key in weights if key not in DEFAULT_RISK_WEIGHTS]
    if unknown:
        return False, f"Unknown risk factors: {', '.join(unknown)}"
    merged = clean_weights(weights)
    total = sum(merged.values())
    if total <= 0:
        return False, "At least one weight must be greater than zero"
    if total > 200:
        return False, "The sum of weights must not exceed 200"
    return True, ""


def level_for_score(score: int, thresholds: Optional[Dict[str, int]] = None) -> str:
    thresholds = thresholds or RISK_THRESHOLDS
    score = int(max(0, min(100, score)))
    if score >= thresholds.get("critical", 85):
        return "critical"
    if score >= thresholds.get("high", 60):
        return "high"
    if score >= thresholds.get("medium", 30):
        return "medium"
    return "normal"


_LEVEL_PHRASES = {
    "critical": "severe danger",
    "high": "high danger",
    "medium": "medium danger",
    "normal": "normal monitoring",
}


def evaluate_risk(
    factors: RiskFactors,
    weights: Optional[Dict[str, Any]] = None,
    thresholds: Optional[Dict[str, int]] = None,
) -> RiskResult:
    """Calculate the 0..100 risk score and produce a plain-language reason."""
    cleaned = clean_weights(weights)
    normalized = factors.normalized()

    contributions: Dict[str, int] = {}
    breakdown: Dict[str, float] = {}
    for name, value in normalized.items():
        contribution = int(round(cleaned[name] * value))
        contributions[name] = contribution
        breakdown[name] = round(value, 3)

    score = int(max(0, min(100, sum(contributions.values()))))

    # Safety rule: face recognition alone is never a danger reason.  Even with
    # a manipulated weight the face channel is capped at 5 points of the score.
    # The cap is applied before the overall 0..100 clamp so that an extreme
    # weight can never *reduce* an otherwise valid score.
    if contributions["face"] > 5:
        contributions["face"] = 5
        score = int(max(0, min(100, sum(contributions.values()))))

    level = level_for_score(score, thresholds)

    reasons = []
    if normalized["zone"] >= 0.5:
        reasons.append(f"the {factors.zone_type} zone is high sensitivity")
    if normalized["time"] >= 0.65:
        reasons.append("the event happened outside normal hours")
    if normalized["dwell"] >= 0.5:
        reasons.append(f"the target stayed {factors.dwell_seconds:.1f}s inside the zone")
    if factors.face_status == "unknown":
        reasons.append("the face is not in the authorized list")
    if normalized["repetition"] > 0:
        reasons.append(f"the event repeated {factors.repetition} time(s)")
    if normalized["behavior"] >= 0.5:
        reasons.append(f"behavior analysis flagged '{factors.behavior}'")
    if factors.target_type == "vehicle":
        reasons.append("a vehicle was involved")

    if not reasons:
        reasons.append("only low-risk signals were detected")

    explanation = (
        f"Risk score {score}/100 ({_LEVEL_PHRASES[level]}). "
        f"The system verified {len([1 for value in normalized.values() if value > 0])} active factors: "
        + "; ".join(reasons)
        + "."
    )

    return RiskResult(
        score=score,
        level=level,
        explanation=explanation,
        breakdown=breakdown,
        contributions=contributions,
    )


def factor_table(result: RiskResult, weights: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a UI-friendly factor breakdown for the threat screen."""
    cleaned = clean_weights(weights)
    return {
        name: {
            "label": FACTOR_LABELS[name],
            "weight": cleaned[name],
            "normalized": result.breakdown.get(name, 0.0),
            "contribution": result.contributions.get(name, 0),
        }
        for name in DEFAULT_RISK_WEIGHTS
    }
