"""
diagnostics.py — Step 6: method-agnostic statistical utilities and the
confounder registry, shared by did.py and interrupted_series.py.

No new dependency: every formula here is hand-rolled with numpy/math, the
same convention already established by src/anomaly/statistics.py
(z_score/mad/robust_z_score/percentile_rank) and
src/evidence/graph.py::_two_proportion_z -- this repo does not carry scipy or
statsmodels in requirements.txt, and this module does not add them.

KNOWN_CONCURRENT_EVENTS is the single source of truth both
eligibility.py's confounders check and interrupted_series.py's
check_concurrent_intervention consult -- kept here (not duplicated in
interrupted_series.py) so every method reports identically for the same
hypothesis rather than drifting.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from causal.models import CausalHypothesis, CausalStatus, CausalTier, ConfounderReport, EligibilityVerdict

# Documented, real, already-established finding (STEP4_VALIDATION.md §12,
# docs/EVIDENCE_FABRIC.md) -- not invented for this module. November 2017 saw
# a marketplace-wide order-volume surge with STRONG anomaly z-scores across
# nearly every top revenue-mover category, concurrent with the delivery
# slowdown documented in the same period.
KNOWN_CONCURRENT_EVENTS: dict[str, dict[str, str]] = {
    "black_friday_2017_11": {
        "period": "2017-11",
        "description": "Documented marketplace-wide order-volume surge in November 2017, with STRONG "
                        "anomaly z-scores across categories (STEP4_VALIDATION.md §12, docs/EVIDENCE_FABRIC.md).",
    },
}

# Structural (non-calendar) confounders: not tied to a specific date, but to
# the shape of the hypothesis itself (a pre-existing group is never randomly
# assigned).
_STRUCTURAL_CONFOUNDER_DIMENSIONS = {"product_category", "customer_state", "seller_state", "seller"}


def ols_fit(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Thin wrapper over numpy's least squares solver. `x` is already the
    full design matrix (including an intercept column if one is wanted) --
    this function performs no feature engineering of its own."""
    coeffs, _residuals, _rank, _sv = np.linalg.lstsq(x, y, rcond=None)
    return coeffs


def simple_slope(x: list[float], y: list[float]) -> tuple[float, float]:
    """(slope, intercept) of the best-fit line through (x, y) via ols_fit."""
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    design = np.vstack([x_arr, np.ones_like(x_arr)]).T
    intercept_coeffs = ols_fit(design, y_arr)
    slope, intercept = float(intercept_coeffs[0]), float(intercept_coeffs[1])
    return slope, intercept


def lag1_autocorrelation(residuals: list[float]) -> Optional[float]:
    """Hand-rolled lag-1 Pearson correlation of a residual series. None if
    there are fewer than 2 lag pairs to correlate (never fabricates a
    coefficient from insufficient data)."""
    e = np.asarray(residuals, dtype=float)
    if len(e) < 3:
        return None
    mean_e = e.mean()
    numerator = float(np.sum((e[1:] - mean_e) * (e[:-1] - mean_e)))
    denominator = float(np.sum((e - mean_e) ** 2))
    if denominator == 0:
        return None
    return numerator / denominator


def detect_known_confounders(hypothesis: CausalHypothesis) -> list[ConfounderReport]:
    """Single source of truth for "what do we know is confounded here" --
    consulted by eligibility.py's confounders check AND by every method
    wrapper's CausalResult.confounders field, so they never drift for the
    same hypothesis."""
    reports: list[ConfounderReport] = []

    for event_name, event in KNOWN_CONCURRENT_EVENTS.items():
        event_month = event["period"]
        for period in (hypothesis.treatment_period, hypothesis.outcome_period):
            for key in ("start", "end", "date"):
                value = period.get(key)
                if value and value[:7] == event_month:
                    reports.append(ConfounderReport(
                        name=event_name, known_or_suspected="KNOWN",
                        detail=f"{event['description']} Overlaps this hypothesis's {key}={value}.",
                    ))
                    break
            else:
                continue
            break

    if hypothesis.treatment_dimension in _STRUCTURAL_CONFOUNDER_DIMENSIONS:
        reports.append(ConfounderReport(
            name=f"{hypothesis.treatment_dimension}_membership_is_preexisting",
            known_or_suspected="SUSPECTED",
            detail=f"'{hypothesis.treatment_dimension}={hypothesis.treatment_group_value}' is a pre-existing "
                   "group characteristic, not an assigned treatment -- any comparison against a control group "
                   "is confounded by whatever else differs between the groups besides this characteristic.",
        ))

    return reports


def report_confounders_never_controlled(confounders: list[ConfounderReport]) -> list[str]:
    """The literal enforcement of the task's own words: 'Do not claim they
    were controlled merely because they exist in the data.' No caller in
    this package (did.py/interrupted_series.py/causal_impact.py/PVM's
    wrapper in engine.py) implements covariate adjustment in this version,
    so this function always returns every confounder's name with
    `controlled_for` forced False -- an assertion, not a data check, since
    flipping it True would be a code change, not a data outcome."""
    names = []
    for c in confounders:
        assert c.controlled_for is False, (
            f"confounder {c.name!r} was marked controlled_for=True -- no method in src/causal/ implements "
            "covariate adjustment; this would be a false governance claim."
        )
        names.append(c.name)
    return names


def compute_abstention_status(tier: CausalTier, verdict: EligibilityVerdict, diagnostics_all_passed: bool,
                               causal_claim_allowed: bool) -> CausalStatus:
    """The single, shared abstention-status policy every method wrapper
    (did.run_did, interrupted_series.run_its, causal_impact.run_causal_impact,
    engine.py's PVM/descriptive paths) calls into -- kept here rather than
    reimplemented per-method, so the same (tier, verdict, diagnostics,
    causal_claim_allowed) combination always yields the same status
    everywhere. Never raises; never defaults to a forced causal conclusion --
    CAUSAL_SUPPORTED is reachable only via the single explicit branch below."""
    if verdict == EligibilityVerdict.CAUSAL_INELIGIBLE:
        return CausalStatus.CAUSAL_REJECTED
    if tier == CausalTier.T2_ARITHMETIC:
        return CausalStatus.ARITHMETIC_ONLY
    if tier == CausalTier.T1_DESCRIPTIVE:
        return CausalStatus.DESCRIPTIVE_ONLY
    # tier is T3/T4 aspirational territory from here down
    if causal_claim_allowed and diagnostics_all_passed and verdict == EligibilityVerdict.ELIGIBLE:
        return CausalStatus.CAUSAL_SUPPORTED
    if verdict == EligibilityVerdict.PARTIALLY_ELIGIBLE or not diagnostics_all_passed:
        return CausalStatus.CAUSAL_INSUFFICIENT
    return CausalStatus.CAUSAL_REJECTED
