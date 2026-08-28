"""Step 6: Difference-in-Differences tests -- synthetic fixtures only (no
canonical-data dependency), matching tests/test_pvm.py's style: the math and
diagnostics are exercised directly against constructed panel data where a
genuine natural experiment (or a genuine violation of one) can be built by
hand. Real-data eligibility/routing is covered by tests/test_eligibility.py
and tests/test_abstention.py's integration test."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from causal import did  # noqa: E402
from causal.models import (  # noqa: E402
    CausalHypothesis,
    CausalMethod,
    CausalTier,
    CheckResult,
    CheckResultStatus,
    EligibilityReport,
    EligibilityVerdict,
)


def _hypothesis(**overrides):
    defaults = dict(
        hypothesis_id="H1", treatment="customer_state", outcome="revenue", unit_of_analysis="customer_state",
        treatment_period={"start": "2017-01-01", "end": "2017-10-31"},
        outcome_period={"start": "2017-11-01", "end": "2017-11-30"},
        proposed_mechanism="X is associated with Y.", required_data=["revenue"],
        proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        treatment_dimension="customer_state", treatment_group_value="SP", control_group_value="all_other_states",
    )
    defaults.update(overrides)
    return CausalHypothesis(**defaults)


def _eligible_report(verdict=EligibilityVerdict.ELIGIBLE):
    return EligibilityReport(hypothesis_id="H1", verdict=verdict, checks=[CheckResult("x", CheckResultStatus.PASS, "ok")])


def test_valid_did_with_parallel_pretrends_produces_causal_supported_at_t3():
    # Identical linear pre-trend slope (10/period) for both groups, then the
    # treatment group jumps by an extra +50 post-treatment -- a genuine,
    # constructed natural experiment.
    series = [("m0", 100.0, 200.0), ("m1", 110.0, 210.0), ("m2", 120.0, 220.0), ("m3", 130.0, 230.0)]
    inputs = did.DiDInputs(treatment_pre=[130.0], treatment_post=[190.0], control_pre=[230.0],
                            control_post=[240.0], pre_period_series=series)
    result = did.run_did(_hypothesis(), inputs, _eligible_report())
    assert result.causal_claim_allowed is True
    assert result.evidence_tier == CausalTier.T3_QUASI_EXPERIMENTAL
    assert result.estimate["point_estimate"] == (190.0 - 130.0) - (240.0 - 230.0)


def test_failed_parallel_trends_forces_causal_claim_not_allowed_but_estimate_still_computed():
    # Divergent pre-trend slopes: treatment flat, control rising sharply.
    series = [("m0", 100.0, 100.0), ("m1", 100.0, 150.0), ("m2", 100.0, 200.0), ("m3", 100.0, 250.0)]
    inputs = did.DiDInputs(treatment_pre=[100.0], treatment_post=[160.0], control_pre=[250.0],
                            control_post=[400.0], pre_period_series=series)
    result = did.run_did(_hypothesis(), inputs, _eligible_report())
    assert result.estimate is not None
    assert result.causal_claim_allowed is False
    assert result.evidence_tier == CausalTier.T1_DESCRIPTIVE
    assert any("parallel-trends" in limitation for limitation in result.limitations)


def test_single_pre_period_treated_as_failed_not_skipped():
    inputs = did.DiDInputs(treatment_pre=[100.0], treatment_post=[150.0], control_pre=[100.0],
                            control_post=[110.0], pre_period_series=[("m0", 100.0, 100.0)])
    diag = did.check_parallel_trends(inputs)
    assert diag.passed is False
    assert "fewer than 2" in diag.detail


def test_did_point_estimate_formula_matches_hand_computed_4_cell_arithmetic():
    inputs = did.DiDInputs(treatment_pre=[10.0, 20.0], treatment_post=[40.0], control_pre=[5.0], control_post=[15.0])
    estimate = did.estimate_did(inputs)
    expected = (40.0 - 15.0) - (15.0 - 5.0)
    assert estimate["point_estimate"] == expected
    assert estimate["treatment_delta"] == 40.0 - 15.0
    assert estimate["control_delta"] == 15.0 - 5.0


def test_partially_eligible_with_passing_diagnostics_caps_at_t2_not_t3():
    series = [("m0", 100.0, 200.0), ("m1", 110.0, 210.0), ("m2", 120.0, 220.0)]
    inputs = did.DiDInputs(treatment_pre=[120.0], treatment_post=[180.0], control_pre=[220.0],
                            control_post=[230.0], pre_period_series=series)
    result = did.run_did(_hypothesis(), inputs, _eligible_report(verdict=EligibilityVerdict.PARTIALLY_ELIGIBLE))
    assert result.causal_claim_allowed is False
    assert result.evidence_tier == CausalTier.T2_ARITHMETIC
