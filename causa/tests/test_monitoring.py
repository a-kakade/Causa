"""Step 7: monitoring.py tests -- correct KPI mapping, no fabricated
targets."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.impact_estimator import estimate_impact  # noqa: E402
from decision.models import DriverSignal  # noqa: E402
from decision.monitoring import build_monitoring_plan  # noqa: E402
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


def test_monitoring_kpis_match_requested_list():
    scoring = DecisionScoringConfig.load()
    impact = estimate_impact(_driver_signal())
    targets = build_monitoring_plan(["on_time_delivery_rate", "avg_delivery_days"], impact, scoring)
    assert [t.kpi for t in targets] == ["on_time_delivery_rate", "avg_delivery_days"]


def test_direction_known_for_declared_kpis():
    scoring = DecisionScoringConfig.load()
    impact = estimate_impact(_driver_signal())
    targets = build_monitoring_plan(["on_time_delivery_rate", "avg_delivery_days"], impact, scoring)
    directions = {t.kpi: t.direction for t in targets}
    assert directions["on_time_delivery_rate"] == "increase"
    assert directions["avg_delivery_days"] == "decrease"


def test_target_is_unknown_sentinel_when_kpi_is_not_the_estimated_metric():
    scoring = DecisionScoringConfig.load()
    impact = estimate_impact(_driver_signal())  # metric == "on_time_delivery_rate"
    targets = build_monitoring_plan(["avg_delivery_days"], impact, scoring)
    assert targets[0].target == "unknown"
    assert targets[0].expected_effect is None
    assert targets[0].warning_threshold is None


def test_target_is_computed_when_kpi_matches_estimated_metric():
    scoring = DecisionScoringConfig.load()
    impact = estimate_impact(_driver_signal())
    targets = build_monitoring_plan(["on_time_delivery_rate"], impact, scoring)
    assert targets[0].target != "unknown"
    assert targets[0].expected_effect == impact.estimated_effect
    assert targets[0].warning_threshold is not None


def test_target_unknown_when_impact_not_estimable():
    scoring = DecisionScoringConfig.load()
    impact = estimate_impact(_driver_signal(historical_estimated_effect=None))
    targets = build_monitoring_plan(["on_time_delivery_rate"], impact, scoring)
    assert targets[0].target == "unknown"
    assert targets[0].expected_effect is None


def test_stop_condition_present_and_references_kpi():
    scoring = DecisionScoringConfig.load()
    impact = estimate_impact(_driver_signal())
    targets = build_monitoring_plan(["on_time_delivery_rate"], impact, scoring)
    assert "on_time_delivery_rate" in targets[0].stop_condition


def test_window_uses_config_default():
    scoring = DecisionScoringConfig.load()
    impact = estimate_impact(_driver_signal())
    targets = build_monitoring_plan(["on_time_delivery_rate"], impact, scoring)
    assert targets[0].window == scoring.default_monitoring_window()
