"""
interrupted_series.py — Step 6: Interrupted Time Series (segmented
regression).

Only ever invoked by engine.py after eligibility has already run. Uses a
4-column OLS design matrix (intercept, time, post, time_since_intervention)
solved via diagnostics.ols_fit -- no scipy/statsmodels dependency.

`_MIN_PRE_PERIODS = 12` is chosen deliberately strict against Olist's own
~20-month governed window (config/kpis.yaml's shared_valid_time_window:
default_start=2017-01, default_end=2018-08): a November-2017-anchored ITS has
only 10 governed pre-period months (Jan-Oct 2017) and will genuinely fail
this check -- not a contrived example, the honest consequence of applying a
defensible threshold to this dataset (docs/CAUSAL_METHOD_SELECTION.md has the
full justification).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from causal import diagnostics
from causal.diagnostics import KNOWN_CONCURRENT_EVENTS, compute_abstention_status
from causal.models import (
    CausalHypothesis,
    CausalMethod,
    CausalResult,
    CausalTier,
    DiagnosticResult,
    EligibilityReport,
    EligibilityVerdict,
)

MIN_PRE_PERIODS = 12
MIN_POST_PERIODS = 3
AUTOCORRELATION_THRESHOLD = 0.5

REQUIRED_ASSUMPTIONS = (
    "no concurrent intervention at the same date",
    "stable KPI definition across the full window",
    "residual autocorrelation does not invalidate inference",
)


@dataclass
class ITSInputs:
    period_labels: list[str]  # chronological "YYYY-MM" labels
    values: list[float]
    intervention_index: int  # index into period_labels/values where the post-period begins
    known_concurrent_events: list[str] = field(default_factory=list)


def fit_segmented_regression(inputs: ITSInputs) -> dict[str, float]:
    """Design matrix per period t: [1, time, post, time_since_intervention].
    Coefficients: [intercept, pre_slope, level_shift, slope_change]."""
    n = len(inputs.values)
    t_idx = inputs.intervention_index
    time = np.arange(n, dtype=float)
    post = (time >= t_idx).astype(float)
    time_since = np.maximum(0.0, time - t_idx)
    design = np.column_stack([np.ones(n), time, post, time_since])
    y = np.asarray(inputs.values, dtype=float)
    coeffs = diagnostics.ols_fit(design, y)
    residuals = (y - design @ coeffs).tolist()
    return {
        "intercept": float(coeffs[0]), "pre_slope": float(coeffs[1]),
        "level_shift": float(coeffs[2]), "slope_change": float(coeffs[3]),
        "residuals": residuals,
    }


def check_sufficient_history(inputs: ITSInputs, min_pre_periods: int = MIN_PRE_PERIODS,
                              min_post_periods: int = MIN_POST_PERIODS) -> DiagnosticResult:
    n_pre = inputs.intervention_index
    n_post = len(inputs.values) - inputs.intervention_index
    if n_pre < min_pre_periods:
        return DiagnosticResult(
            "sufficient_history", False, float(n_pre), float(min_pre_periods),
            f"only {n_pre} pre-intervention months available (< {min_pre_periods} required for a "
            "segmented-regression trend to be distinguishable from noise on monthly, moderately volatile "
            "e-commerce data).",
        )
    if n_post < min_post_periods:
        return DiagnosticResult(
            "sufficient_history", False, float(n_post), float(min_post_periods),
            f"only {n_post} post-intervention months available (< {min_post_periods} required).",
        )
    return DiagnosticResult("sufficient_history", True, float(n_pre), float(min_pre_periods),
                             f"{n_pre} pre-intervention and {n_post} post-intervention months available.")


def check_autocorrelation(residuals: list[float], threshold: float = AUTOCORRELATION_THRESHOLD) -> DiagnosticResult:
    r1 = diagnostics.lag1_autocorrelation(residuals)
    if r1 is None:
        return DiagnosticResult("autocorrelation", False, None, threshold,
                                 "too few residuals to compute a lag-1 autocorrelation -- treated as failed.")
    passed = abs(r1) <= threshold
    return DiagnosticResult(
        "autocorrelation", passed, r1, threshold,
        f"residuals show lag-1 autocorrelation of {r1:.2f}" +
        ("." if passed else f", exceeding {threshold} -- standard errors from this regression would be "
                             "unreliable without a correction this module does not implement; treated as a "
                             "diagnostic failure, not silently ignored."),
    )


def check_concurrent_intervention(inputs: ITSInputs) -> DiagnosticResult:
    intervention_period = inputs.period_labels[inputs.intervention_index]
    matches = [name for name, event in KNOWN_CONCURRENT_EVENTS.items() if event["period"] == intervention_period]
    if not matches:
        return DiagnosticResult("concurrent_intervention", True, None, None,
                                 f"no known concurrent event overlaps intervention period {intervention_period}.")
    names = ", ".join(matches)
    return DiagnosticResult(
        "concurrent_intervention", False, None, None,
        f"known concurrent event(s) overlap the intervention window: {names}. A concurrent event confounds "
        "the level-shift/slope-change estimate -- it cannot be attributed to the hypothesized treatment alone.",
    )


def run_its(hypothesis: CausalHypothesis, inputs: ITSInputs, eligibility: EligibilityReport) -> CausalResult:
    fit = fit_segmented_regression(inputs)
    history_diag = check_sufficient_history(inputs)
    autocorr_diag = check_autocorrelation(fit["residuals"])
    concurrent_diag = check_concurrent_intervention(inputs)
    diags = [history_diag, autocorr_diag, concurrent_diag]
    diagnostics_all_passed = all(d.passed for d in diags)

    causal_claim_allowed = diagnostics_all_passed and eligibility.verdict == EligibilityVerdict.ELIGIBLE
    if causal_claim_allowed:
        tier = CausalTier.T3_QUASI_EXPERIMENTAL
    elif diagnostics_all_passed:
        tier = CausalTier.T2_ARITHMETIC
    else:
        tier = CausalTier.T1_DESCRIPTIVE

    limitations = []
    if not history_diag.passed:
        limitations.append("insufficient pre/post history for a defensible segmented-regression trend estimate.")
    if not autocorr_diag.passed:
        limitations.append("residual autocorrelation invalidates standard inference for this regression.")
    if not concurrent_diag.passed:
        limitations.append("a concurrent event confounds the intervention window; the level-shift/slope-change "
                            "estimate cannot be attributed to the hypothesized treatment alone.")

    confounder_reports = diagnostics.detect_known_confounders(hypothesis)
    confounder_names = diagnostics.report_confounders_never_controlled(confounder_reports)
    for match in [name for name, event in KNOWN_CONCURRENT_EVENTS.items()
                  if event["period"] == inputs.period_labels[inputs.intervention_index]]:
        if match not in confounder_names:
            confounder_names.append(match)

    status = compute_abstention_status(tier, eligibility.verdict, diagnostics_all_passed, causal_claim_allowed)

    return CausalResult(
        hypothesis_id=hypothesis.hypothesis_id, method=CausalMethod.INTERRUPTED_TIME_SERIES,
        evidence_tier=tier, status=status,
        estimate={"level_shift": fit["level_shift"], "slope_change": fit["slope_change"],
                  "pre_slope": fit["pre_slope"], "unit": "absolute"},
        uncertainty=None, assumptions=list(REQUIRED_ASSUMPTIONS), diagnostics=diags,
        confounders=confounder_names, evidence_ids=[], limitations=limitations,
        causal_claim_allowed=causal_claim_allowed, eligibility_report=eligibility,
    )
