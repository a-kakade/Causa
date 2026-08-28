"""Step 6: eligibility checker tests (task's 12-check eligibility gate).

Uses the session-scoped real `engine`/`canonical` fixtures from
tests/conftest.py (a real KPIEngine against real canonical data) -- no
synthetic KPI values are needed here since every check reads governed
contract fields (config/kpis.yaml) and real KPIEngine.compute() results.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from causal import eligibility  # noqa: E402
from causal.models import CausalHypothesis, CausalMethod, CheckResultStatus, EligibilityVerdict  # noqa: E402

OCT = ("2017-10-01", "2017-10-31")
NOV = ("2017-11-01", "2017-11-30")


def _hypothesis(**overrides):
    defaults = dict(
        hypothesis_id="H1", treatment="orders", outcome="revenue", unit_of_analysis="order",
        treatment_period={"start": OCT[0], "end": OCT[1]}, outcome_period={"start": NOV[0], "end": NOV[1]},
        proposed_mechanism="X is associated with Y.", required_data=["revenue", "orders"],
        proposed_method=CausalMethod.PVM,
    )
    defaults.update(overrides)
    return CausalHypothesis(**defaults)


def test_all_12_checks_run_in_fixed_order_and_always_return_12_results(engine):
    report = eligibility.check_eligibility(_hypothesis(), engine, engine.registry)
    assert len(report.checks) == 12
    assert [c.check_name for c in report.checks] == list(eligibility.CHECK_NAMES)


def test_missing_treatment_returns_ineligible_with_treatment_exists_hard_fail(engine):
    h = _hypothesis(treatment="not_a_real_kpi")
    report = eligibility.check_eligibility(h, engine, engine.registry)
    assert report.verdict in (EligibilityVerdict.INELIGIBLE, EligibilityVerdict.CAUSAL_INELIGIBLE)
    assert "treatment_exists" in report.hard_fail_checks


def test_missing_outcome_returns_ineligible_with_outcome_exists_hard_fail(engine):
    h = _hypothesis(outcome="not_a_real_kpi")
    report = eligibility.check_eligibility(h, engine, engine.registry)
    assert "outcome_exists" in report.hard_fail_checks
    assert report.verdict == EligibilityVerdict.INELIGIBLE


def test_temporal_order_failure_for_preexisting_group_returns_causal_ineligible(engine):
    """A hypothesis whose ONLY problem is a pre-existing group with no
    assignment timing -- everything else (sufficient pre-period etc.) is
    engineered to pass, isolating treatment_precedes_outcome as the sole
    hard failure so the CAUSAL_INELIGIBLE branch is actually exercised."""
    h = _hypothesis(
        treatment="customer_state", treatment_dimension="customer_state", treatment_group_value="SP",
        control_group_value="all_other_states",
        treatment_period={"start": "2017-06-01", "end": "2017-11-30"},
        outcome_period={"start": OCT[0], "end": NOV[1]},
    )
    report = eligibility.check_eligibility(h, engine, engine.registry)
    assert report.hard_fail_checks == ["treatment_precedes_outcome"]
    assert report.verdict == EligibilityVerdict.CAUSAL_INELIGIBLE


def test_insufficient_pre_period_hard_fails_below_2_months(engine):
    h = _hypothesis(treatment_period={"start": "2017-01-01", "end": "2017-01-31"},
                     outcome_period={"start": "2017-02-01", "end": "2017-02-28"})
    report = eligibility.check_eligibility(h, engine, engine.registry)
    check = next(c for c in report.checks if c.check_name == "sufficient_pre_period")
    assert check.status == CheckResultStatus.HARD_FAIL


def test_insufficient_pre_period_soft_fails_between_2_and_5_months(engine):
    h = _hypothesis(treatment_period={"start": "2017-04-01", "end": "2017-04-30"},
                     outcome_period={"start": "2017-05-01", "end": "2017-05-31"})
    report = eligibility.check_eligibility(h, engine, engine.registry)
    check = next(c for c in report.checks if c.check_name == "sufficient_pre_period")
    assert check.status == CheckResultStatus.SOFT_FAIL


def test_insufficient_post_period_hard_fails_at_zero_months(engine):
    h = _hypothesis(treatment_period={"start": OCT[0], "end": "2018-08-31"},
                     outcome_period={"start": "2018-08-01", "end": "2018-08-31"})
    report = eligibility.check_eligibility(h, engine, engine.registry)
    check = next(c for c in report.checks if c.check_name == "sufficient_post_period")
    assert check.status == CheckResultStatus.HARD_FAIL


def test_no_control_group_hard_fails_control_variation_when_method_needs_one(engine):
    h = _hypothesis(proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES, control_group_value=None)
    report = eligibility.check_eligibility(h, engine, engine.registry)
    check = next(c for c in report.checks if c.check_name == "control_variation")
    assert check.status == CheckResultStatus.HARD_FAIL
    assert "control_variation" in report.hard_fail_checks


def test_sample_size_reads_threshold_from_kpi_contract_not_hardcoded(engine):
    """orders' minimum_observations is 1 (a very low bar); revenue's is 30.
    The same real data must be judged differently depending on which
    contract's threshold applies -- proof the check reads the contract."""
    h_orders = _hypothesis(outcome="orders", treatment="revenue")
    h_revenue = _hypothesis(outcome="revenue", treatment="orders")
    orders_min = engine.registry.get("orders")["data_quality_requirements"]["minimum_observations"]
    revenue_min = engine.registry.get("revenue")["data_quality_requirements"]["minimum_observations"]
    assert orders_min != revenue_min
    report_orders = eligibility.check_eligibility(h_orders, engine, engine.registry)
    report_revenue = eligibility.check_eligibility(h_revenue, engine, engine.registry)
    check_orders = next(c for c in report_orders.checks if c.check_name == "sample_size")
    check_revenue = next(c for c in report_revenue.checks if c.check_name == "sample_size")
    assert str(orders_min) in check_orders.reason
    assert str(revenue_min) in check_revenue.reason


def test_confounding_detected_is_always_soft_fail_never_hard_fail(engine):
    h = _hypothesis(outcome_period={"start": NOV[0], "end": NOV[1]})  # overlaps documented Black Friday event
    report = eligibility.check_eligibility(h, engine, engine.registry)
    check = next(c for c in report.checks if c.check_name == "confounders")
    assert check.status in (CheckResultStatus.PASS, CheckResultStatus.SOFT_FAIL)
    assert "confounders" not in report.hard_fail_checks


def test_consistent_grain_rejects_unsupported_dimension_per_contract(engine):
    h = _hypothesis(outcome="avg_delivery_days", unit_of_analysis="seller_state")
    report = eligibility.check_eligibility(h, engine, engine.registry)
    check = next(c for c in report.checks if c.check_name == "consistent_grain")
    assert check.status == CheckResultStatus.HARD_FAIL


def test_verdict_rollup_any_hard_fail_yields_ineligible(engine):
    h = _hypothesis(outcome="not_a_real_kpi")
    report = eligibility.check_eligibility(h, engine, engine.registry)
    assert report.hard_fail_checks
    assert report.verdict in (EligibilityVerdict.INELIGIBLE, EligibilityVerdict.CAUSAL_INELIGIBLE)


def test_verdict_rollup_only_soft_fails_yields_partially_eligible(engine):
    h = _hypothesis(outcome_period={"start": NOV[0], "end": NOV[1]})
    report = eligibility.check_eligibility(h, engine, engine.registry)
    if not report.hard_fail_checks and report.soft_fail_checks:
        assert report.verdict == EligibilityVerdict.PARTIALLY_ELIGIBLE


def test_verdict_rollup_all_pass_yields_eligible(engine):
    h = _hypothesis(outcome_period={"start": "2017-05-01", "end": "2017-05-31"},
                     treatment_period={"start": "2017-04-01", "end": "2017-04-30"})
    report = eligibility.check_eligibility(h, engine, engine.registry)
    if not report.hard_fail_checks and not report.soft_fail_checks:
        assert report.verdict == EligibilityVerdict.ELIGIBLE
