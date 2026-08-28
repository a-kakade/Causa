"""
bridge.py — Step 7: best-effort converters from a Step 5 HypothesisResult or
a Step 6 CausalResult into this package's own DriverSignal input contract.

Same posture as causal/engine.py::causal_hypothesis_from_step5: best-effort,
NEVER raises, returns None (never a fabricated DriverSignal) when the
mapping cannot produce a structurally valid signal. Callers fall back to a
manually-authored DriverSignal in that case, exactly as
scripts/step6_causal_validation.py already does for its own bridge.

business_context is ALWAYS an explicit caller-supplied argument, never
inferred by either bridge function here -- no upstream Step 5/6 object
carries real-world budget/inventory/capacity facts, so this package never
invents them.
"""

from __future__ import annotations

from typing import Any, Optional

from decision.models import DriverSignal
from decision.ontology import DecisionOntology

# Conservative, deliberately conservative, config-movable mapping from a
# CausalResult's own (status, evidence_tier) to a 0-1 driver_confidence.
# Never an LLM guess -- a small fixed lookup table, same posture as
# monitoring.py's _KPI_DIRECTION.
_CAUSAL_STATUS_TIER_TO_CONFIDENCE: dict[tuple[str, str], float] = {
    ("CAUSAL_SUPPORTED", "T4_EXPERIMENTAL"): 0.9,
    ("CAUSAL_SUPPORTED", "T3_QUASI_EXPERIMENTAL"): 0.8,
    ("ARITHMETIC_ONLY", "T2_ARITHMETIC"): 0.35,
    ("DESCRIPTIVE_ONLY", "T1_DESCRIPTIVE"): 0.25,
    ("CAUSAL_INSUFFICIENT", "T1_DESCRIPTIVE"): 0.1,
    ("CAUSAL_REJECTED", "T1_DESCRIPTIVE"): 0.1,
}
_DEFAULT_CAUSAL_CONFIDENCE = 0.1

_HYPOTHESIS_CONFIDENCE_LEVEL_TO_SCORE: dict[str, float] = {
    "HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.3, "ABSTAIN": 0.05, "NEEDS_CLARIFICATION": 0.05,
}

# Step 5's driver vocabulary ("volume"/"price"/"mix"/"delivery"/"geography")
# does not line up 1:1 with this package's ontology driver names -- best-
# effort mapping only, matching causal/engine.py's own honest caveat that
# this bridge is not load-bearing for the real Olist validation.
_HYPOTHESIS_DRIVER_TO_DECISION_DRIVER: dict[str, str] = {
    "delivery": "delivery_delay",
}


def driver_signal_from_causal_result(causal_result: Any, hypothesis: Any, ontology: DecisionOntology,
                                      business_context: dict[str, Any]) -> Optional[DriverSignal]:
    """Maps a Step 6 CausalResult + its originating CausalHypothesis into a
    DriverSignal. Returns None when method==NONE or when the hypothesis's
    treatment/outcome cannot be mapped to a known ontology driver."""
    if causal_result is None or hypothesis is None:
        return None
    if getattr(causal_result, "method", None) is None or causal_result.method.value == "NONE":
        return None

    driver_candidate = getattr(hypothesis, "treatment", None)
    if driver_candidate is None or not ontology.is_supported(driver_candidate):
        return None
    entry = ontology.get_driver(driver_candidate)

    status_value = causal_result.status.value if hasattr(causal_result.status, "value") else str(causal_result.status)
    tier_value = causal_result.evidence_tier.value if hasattr(causal_result.evidence_tier, "value") else str(causal_result.evidence_tier)
    driver_confidence = _CAUSAL_STATUS_TIER_TO_CONFIDENCE.get((status_value, tier_value), _DEFAULT_CAUSAL_CONFIDENCE)

    estimate = causal_result.estimate or {}
    historical_effect = None
    for key in ("volume_effect", "price_effect", "mix_effect", "value"):
        if key in estimate and isinstance(estimate[key], (int, float)):
            historical_effect = estimate[key]
            break

    outcome_period = getattr(hypothesis, "outcome_period", {}) or {}
    period = outcome_period.get("start", outcome_period.get("date", ""))[:7] if outcome_period else ""

    try:
        return DriverSignal(
            driver=entry["driver"], driver_category=entry["driver_category"],
            kpi_id=getattr(hypothesis, "outcome", ""), period=period,
            historical_estimated_effect=historical_effect,
            historical_effect_source="STEP6_CAUSAL_RESULT" if historical_effect is not None else "UNKNOWN",
            driver_confidence=driver_confidence,
            causal_claim_allowed=bool(causal_result.causal_claim_allowed),
            causal_result_id=getattr(causal_result, "hypothesis_id", None),
            source="STEP6_CAUSAL_RESULT", business_context=dict(business_context),
        )
    except (ValueError, KeyError, AttributeError):
        return None


def driver_signal_from_hypothesis_result(hypothesis_result: Any, hypothesis: Any, investigation_state: Any,
                                          ontology: DecisionOntology, business_context: dict[str, Any]
                                          ) -> Optional[DriverSignal]:
    """Maps a Step 5 HypothesisResult + its Hypothesis + parent
    InvestigationState into a DriverSignal. Returns None when the
    hypothesis's driver cannot be mapped to a known ontology driver, or the
    result status is not SUPPORTED."""
    if hypothesis_result is None or hypothesis is None or investigation_state is None:
        return None
    status = getattr(hypothesis_result, "status", None)
    if status != "SUPPORTED":
        return None

    raw_driver = getattr(hypothesis, "driver", None)
    decision_driver = _HYPOTHESIS_DRIVER_TO_DECISION_DRIVER.get(raw_driver, raw_driver)
    if decision_driver is None or not ontology.is_supported(decision_driver):
        return None
    entry = ontology.get_driver(decision_driver)

    confidence_level = hypothesis_result.confidence
    confidence_value = confidence_level.value if hasattr(confidence_level, "value") else str(confidence_level)
    driver_confidence = _HYPOTHESIS_CONFIDENCE_LEVEL_TO_SCORE.get(confidence_value, 0.05)

    kpi_id = getattr(investigation_state, "kpi_id", "")
    period = getattr(investigation_state, "period", "")

    try:
        return DriverSignal(
            driver=entry["driver"], driver_category=entry["driver_category"], kpi_id=kpi_id, period=period,
            driver_confidence=driver_confidence, source="STEP5_HYPOTHESIS_RESULT",
            business_context=dict(business_context),
        )
    except (ValueError, KeyError, AttributeError):
        return None
