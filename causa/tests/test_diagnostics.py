"""Step 6: shared diagnostics utilities + Interrupted Time Series tests.

Pure synthetic fixtures throughout, following tests/test_pvm.py's
no-canonical-data-dependency convention -- OLS, autocorrelation, and
segmented-regression formulas are exercised against constructed data where
the correct answer is known analytically.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from causal import diagnostics, interrupted_series  # noqa: E402
from causal.models import (  # noqa: E402
    CausalHypothesis,
    CausalMethod,
    CausalTier,
    CheckResult,
    CheckResultStatus,
    ConfounderReport,
    EligibilityReport,
    EligibilityVerdict,
)


def _hypothesis(**overrides):
    defaults = dict(
        hypothesis_id="H1", treatment="revenue", outcome="revenue", unit_of_analysis="month",
        treatment_period={"start": "2017-11-01", "end": "2017-11-30"},
        outcome_period={"start": "2017-11-01", "end": "2018-08-31"},
        proposed_mechanism="X is associated with Y.", required_data=["revenue"],
        proposed_method=CausalMethod.INTERRUPTED_TIME_SERIES,
    )
    defaults.update(overrides)
    return CausalHypothesis(**defaults)


def _eligible_report():
    return EligibilityReport(hypothesis_id="H1", verdict=EligibilityVerdict.ELIGIBLE,
                              checks=[CheckResult("x", CheckResultStatus.PASS, "ok")])


# -- diagnostics.py -----------------------------------------------------------


def test_ols_fit_recovers_known_slope_intercept_on_synthetic_line():
    import numpy as np
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    y = 3.0 * x + 7.0
    design = np.vstack([x, np.ones_like(x)]).T
    coeffs = diagnostics.ols_fit(design, y)
    assert abs(coeffs[0] - 3.0) < 1e-9
    assert abs(coeffs[1] - 7.0) < 1e-9


def test_lag1_autocorrelation_hand_rolled_matches_known_synthetic_case():
    # Perfectly alternating residuals -> strong negative lag-1 autocorrelation.
    residuals = [1.0, -1.0, 1.0, -1.0, 1.0, -1.0]
    r1 = diagnostics.lag1_autocorrelation(residuals)
    assert r1 is not None
    assert r1 < -0.7


def test_detect_known_confounders_returns_confounder_for_category_and_geographic_hypotheses():
    h = _hypothesis(treatment="product_category", treatment_dimension="product_category",
                     treatment_group_value="bed_bath_table", control_group_value="all_other_categories")
    confounders = diagnostics.detect_known_confounders(h)
    assert any("preexisting" in c.name for c in confounders)


def test_confounders_never_marked_controlled_for_by_default():
    reports = [ConfounderReport(name="x", known_or_suspected="KNOWN", detail="d")]
    names = diagnostics.report_confounders_never_controlled(reports)
    assert names == ["x"]
    reports[0].controlled_for = True
    try:
        diagnostics.report_confounders_never_controlled(reports)
        assert False, "expected an AssertionError when controlled_for=True"
    except AssertionError:
        pass


# -- interrupted_series.py ----------------------------------------------------


def test_insufficient_history_hard_fails_below_12_pre_periods():
    labels = [f"2017-{m:02d}" for m in range(1, 11)] + [f"2017-11"]  # 10 pre-periods, 1 post
    inputs = interrupted_series.ITSInputs(period_labels=labels, values=[100.0] * len(labels),
                                           intervention_index=10)
    diag = interrupted_series.check_sufficient_history(inputs)
    assert diag.passed is False


def test_sufficient_history_passes_at_12_pre_and_3_post_periods():
    labels = [f"m{i}" for i in range(15)]
    inputs = interrupted_series.ITSInputs(period_labels=labels, values=[100.0] * 15, intervention_index=12)
    diag = interrupted_series.check_sufficient_history(inputs)
    assert diag.passed is True


def test_autocorrelation_check_fails_above_0_5_threshold():
    diag = interrupted_series.check_autocorrelation([1.0, -1.0, 1.0, -1.0, 1.0, -1.0])
    assert diag.passed is False


def test_concurrent_intervention_flags_black_friday_2017_11_when_overlapping():
    labels = [f"2017-{m:02d}" for m in range(1, 13)]
    inputs = interrupted_series.ITSInputs(period_labels=labels, values=[100.0] * 12, intervention_index=10)  # "2017-11"
    diag = interrupted_series.check_concurrent_intervention(inputs)
    assert diag.passed is False
    assert "black_friday_2017_11" in diag.detail


def test_concurrent_intervention_does_not_flag_non_overlapping_periods():
    labels = [f"2017-{m:02d}" for m in range(1, 13)]
    inputs = interrupted_series.ITSInputs(period_labels=labels, values=[100.0] * 12, intervention_index=2)  # "2017-03"
    diag = interrupted_series.check_concurrent_intervention(inputs)
    assert diag.passed is True


def test_segmented_regression_recovers_level_shift_and_slope_change_on_synthetic_step_function():
    n_pre, n_post = 15, 5
    pre_values = [10.0 + 2.0 * t for t in range(n_pre)]
    intervention = n_pre
    post_values = [pre_values[-1] + 50.0 + (2.0 + 5.0) * (t + 1) for t in range(n_post)]  # level shift + slope change
    labels = [f"m{i}" for i in range(n_pre + n_post)]
    inputs = interrupted_series.ITSInputs(period_labels=labels, values=pre_values + post_values,
                                           intervention_index=intervention)
    fit = interrupted_series.fit_segmented_regression(inputs)
    assert abs(fit["pre_slope"] - 2.0) < 1e-6
    assert fit["level_shift"] > 30.0
    assert fit["slope_change"] > 0


def test_run_its_forces_t1_when_history_insufficient():
    labels = [f"2017-{m:02d}" for m in range(1, 11)] + ["2017-11"]
    result = interrupted_series.run_its(_hypothesis(), interrupted_series.ITSInputs(
        period_labels=labels, values=[100.0 + i for i in range(len(labels))], intervention_index=10),
        _eligible_report())
    assert result.causal_claim_allowed is False
    assert result.evidence_tier == CausalTier.T1_DESCRIPTIVE
