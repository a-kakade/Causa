"""Step 7: confidence_engine.py tests -- weighted-sum arithmetic correctness,
weight-config swap changes score, transparency of factors/weights."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.confidence_engine import compute_confidence  # noqa: E402
from decision.impact_estimator import estimate_impact  # noqa: E402
from decision.models import DriverSignal  # noqa: E402
from decision.ontology import DecisionScoringConfig  # noqa: E402


def _driver_signal(**overrides):
    defaults = dict(
        driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS", kpi_id="on_time_delivery_rate",
        period="2017-11", addressable_population=12500, addressable_population_source="HISTORICAL_ESTIMATE",
        historical_estimated_effect=0.06, historical_effect_source="HISTORICAL_ESTIMATE",
        driver_confidence=0.78, business_context={},
    )
    defaults.update(overrides)
    return DriverSignal(**defaults)


def _action_type(link_strength="STRONG"):
    return {"action_link_strength": link_strength}


def test_confidence_weighted_sum_matches_hand_computed_value():
    scoring = DecisionScoringConfig.load()
    signal = _driver_signal()
    impact = estimate_impact(signal)
    score, factors, weights = compute_confidence(signal, impact, _action_type("STRONG"), scoring)

    expected = (
        weights["driver_confidence"] * factors["driver_confidence"]
        + weights["data_quality"] * factors["data_quality"]
        + weights["historical_support"] * factors["historical_support"]
        + weights["action_link_strength"] * factors["action_link_strength"]
    )
    assert abs(score - expected) < 1e-9


def test_confidence_score_clamped_to_zero_one():
    scoring = DecisionScoringConfig.load()
    signal = _driver_signal(driver_confidence=5.0)  # deliberately out of range
    impact = estimate_impact(signal)
    score, _, _ = compute_confidence(signal, impact, _action_type(), scoring)
    assert 0.0 <= score <= 1.0


def test_missing_driver_confidence_treated_as_zero_not_fabricated():
    scoring = DecisionScoringConfig.load()
    signal = _driver_signal(driver_confidence=None)
    impact = estimate_impact(signal)
    score, factors, _ = compute_confidence(signal, impact, _action_type(), scoring)
    assert factors["driver_confidence"] == 0.0


def test_historical_support_high_when_effect_source_known():
    scoring = DecisionScoringConfig.load()
    signal = _driver_signal()
    impact = estimate_impact(signal)
    _, factors, _ = compute_confidence(signal, impact, _action_type(), scoring)
    assert factors["historical_support"] == 1.0


def test_historical_support_low_when_effect_source_unknown():
    scoring = DecisionScoringConfig.load()
    signal = _driver_signal(historical_estimated_effect=None)
    impact = estimate_impact(signal)
    _, factors, _ = compute_confidence(signal, impact, _action_type(), scoring)
    assert factors["historical_support"] < 1.0


def test_action_link_strength_factor_reflects_ontology_tier():
    scoring = DecisionScoringConfig.load()
    signal = _driver_signal()
    impact = estimate_impact(signal)
    _, factors_strong, _ = compute_confidence(signal, impact, _action_type("STRONG"), scoring)
    _, factors_weak, _ = compute_confidence(signal, impact, _action_type("WEAK"), scoring)
    assert factors_strong["action_link_strength"] > factors_weak["action_link_strength"]


def test_data_quality_label_from_business_context_changes_factor():
    scoring = DecisionScoringConfig.load()
    signal_high = _driver_signal(business_context={"data_quality": "HIGH"})
    signal_low = _driver_signal(business_context={"data_quality": "LOW"})
    impact = estimate_impact(signal_high)
    _, factors_high, _ = compute_confidence(signal_high, impact, _action_type(), scoring)
    _, factors_low, _ = compute_confidence(signal_low, impact, _action_type(), scoring)
    assert factors_high["data_quality"] > factors_low["data_quality"]


def test_factors_and_weights_both_returned_for_transparency():
    scoring = DecisionScoringConfig.load()
    signal = _driver_signal()
    impact = estimate_impact(signal)
    _, factors, weights = compute_confidence(signal, impact, _action_type(), scoring)
    assert set(factors) == {"driver_confidence", "data_quality", "historical_support", "action_link_strength"}
    assert set(weights) == set(factors)
