"""Step 7: impact_estimator.py tests -- exact formula arithmetic, missing-
data safety, no invented numbers, confidence incorporation."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.impact_estimator import estimate_impact  # noqa: E402
from decision.models import DataSource, DriverSignal  # noqa: E402


def _driver_signal(**overrides):
    defaults = dict(
        driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS", kpi_id="on_time_delivery_rate",
        period="2017-11", addressable_population=12500, addressable_population_source="HISTORICAL_ESTIMATE",
        historical_estimated_effect=0.06, historical_effect_source="HISTORICAL_ESTIMATE",
        driver_confidence=0.78, business_context={},
    )
    defaults.update(overrides)
    return DriverSignal(**defaults)


def test_calculated_impact_matches_exact_formula():
    signal = _driver_signal()
    impact = estimate_impact(signal)
    assert impact.is_estimable is True
    assert impact.calculated_impact == 0.06 * 12500 * 0.78


def test_missing_historical_effect_marks_not_estimable_and_unknown_source():
    signal = _driver_signal(historical_estimated_effect=None)
    impact = estimate_impact(signal)
    assert impact.is_estimable is False
    assert impact.calculated_impact is None
    assert impact.effect_source == DataSource.UNKNOWN.value


def test_missing_addressable_population_marks_not_estimable():
    signal = _driver_signal(addressable_population=None)
    impact = estimate_impact(signal)
    assert impact.is_estimable is False
    assert impact.calculated_impact is None
    assert impact.population_source == DataSource.UNKNOWN.value


def test_missing_driver_confidence_marks_not_estimable():
    signal = _driver_signal(driver_confidence=None)
    impact = estimate_impact(signal)
    assert impact.is_estimable is False
    assert impact.calculated_impact is None


def test_no_revenue_impact_without_monetary_business_context():
    signal = _driver_signal()  # delivery_delay -> unit "pp", no avg_order_value in business_context
    impact = estimate_impact(signal)
    assert impact.revenue_impact is None


def test_revenue_impact_computed_when_avg_order_value_present():
    signal = _driver_signal(business_context={"avg_order_value": 150.0})
    impact = estimate_impact(signal)
    assert impact.revenue_impact == impact.calculated_impact * 150.0


def test_aov_decline_unit_is_currency_and_revenue_impact_equals_calculated_impact():
    signal = _driver_signal(driver="aov_decline", driver_category="PRICING_PRODUCT_MIX", kpi_id="aov")
    impact = estimate_impact(signal)
    assert impact.effect_unit == "currency"
    assert impact.revenue_impact == impact.calculated_impact


def test_confidence_basis_cites_driver_signal_source():
    signal = _driver_signal(source="STEP6_CAUSAL_RESULT")
    impact = estimate_impact(signal)
    assert "STEP6_CAUSAL_RESULT" in impact.confidence_basis


def test_missing_multiple_inputs_lists_all_in_confidence_basis():
    signal = _driver_signal(historical_estimated_effect=None, addressable_population=None)
    impact = estimate_impact(signal)
    assert "historical_estimated_effect" in impact.confidence_basis
    assert "addressable_population" in impact.confidence_basis


def test_no_fabricated_positive_impact_when_effect_is_zero():
    signal = _driver_signal(historical_estimated_effect=0.0)
    impact = estimate_impact(signal)
    assert impact.is_estimable is True
    assert impact.calculated_impact == 0.0
