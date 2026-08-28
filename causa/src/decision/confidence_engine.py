"""
confidence_engine.py — Step 7: computes a recommendation's confidence score
as a weighted sum of transparent, configurable factors.

NEVER an LLM's opinion (task's own non-negotiable). Four factors, weights
from config/decision_scoring.yaml:
  driver_confidence     -- DriverSignal.driver_confidence, already 0-1 from
                            upstream Step 5/6 evidence (or a conservative
                            default if the signal carries none)
  data_quality          -- looked up from a business_context label via
                            decision_scoring.yaml's data_quality_scores
  historical_support     -- 1.0 if the ExpectedImpact has a real, non-UNKNOWN
                            effect_source; a low floor otherwise
  action_link_strength   -- the ontology's own action_link_strength tier for
                            this action_type, mapped through
                            action_link_strength_scores

Both the scalar confidence_score and the full factor/weight breakdown are
returned, satisfying the transparency requirement (task: "expose the
underlying factors").
"""

from __future__ import annotations

from typing import Any

from decision.models import DataSource, ExpectedImpact
from decision.ontology import DecisionScoringConfig

_HISTORICAL_SUPPORT_FLOOR = 0.1
_DEFAULT_DRIVER_CONFIDENCE_WHEN_MISSING = 0.0


def compute_confidence(driver_signal: Any, expected_impact: ExpectedImpact, action_type: dict,
                        scoring_config: DecisionScoringConfig) -> tuple[float, dict, dict]:
    """Returns (confidence_score, factors, weights) -- all three retained by
    the caller (ranking.py) for ScoreBreakdown's transparency fields."""
    weights = scoring_config.confidence_weights

    driver_confidence = driver_signal.driver_confidence
    if driver_confidence is None:
        driver_confidence = _DEFAULT_DRIVER_CONFIDENCE_WHEN_MISSING
    driver_confidence = max(0.0, min(1.0, float(driver_confidence)))

    data_quality_label = driver_signal.business_context.get("data_quality", "UNKNOWN")
    data_quality = scoring_config.data_quality_scores.get(data_quality_label, scoring_config.data_quality_scores["UNKNOWN"])

    historical_support = (
        1.0 if expected_impact.effect_source != DataSource.UNKNOWN.value else _HISTORICAL_SUPPORT_FLOOR
    )

    link_strength_tier = action_type.get("action_link_strength", "WEAK")
    action_link_strength = scoring_config.action_link_strength_scores.get(link_strength_tier, 0.0)

    factors = {
        "driver_confidence": driver_confidence,
        "data_quality": data_quality,
        "historical_support": historical_support,
        "action_link_strength": action_link_strength,
    }

    confidence_score = sum(weights[name] * factors[name] for name in factors)
    confidence_score = max(0.0, min(1.0, confidence_score))

    return confidence_score, factors, dict(weights)
