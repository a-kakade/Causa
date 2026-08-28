"""
did.py — Step 6: Difference-in-Differences.

Only ever invoked by engine.py after eligibility.check_eligibility() has
already run (this module never re-checks eligibility itself -- it trusts the
EligibilityReport it is handed). Implements a plain 2x2 arithmetic estimator
(no regression library, matching the repo's no-scipy/statsmodels convention)
and a hand-rolled parallel-trends diagnostic.

The point estimate is ALWAYS computed, even when diagnostics fail -- the
task's own words: "If diagnostics fail: reject causal interpretation," not
"withhold the number." Rejecting the causal INTERPRETATION while still
reporting the arithmetic is the whole point of a governed evidence-tier
engine: the number is real, what it's allowed to mean is what's gated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from causal import diagnostics
from causal.diagnostics import compute_abstention_status
from causal.models import (
    CausalMethod,
    CausalResult,
    CausalTier,
    CausalHypothesis,
    DiagnosticResult,
    EligibilityReport,
    EligibilityVerdict,
)

PARALLEL_TRENDS_SLOPE_RATIO_TOLERANCE = 0.5

REQUIRED_ASSUMPTIONS = (
    "parallel pre-treatment trends",
    "no concurrent confounding intervention",
    "stable unit composition across periods",
)


@dataclass
class DiDInputs:
    treatment_pre: list[float]
    treatment_post: list[float]
    control_pre: list[float]
    control_post: list[float]
    # Chronological (period_label, treatment_group_value, control_group_value)
    # across ALL pre-periods, for the parallel-trends check only. None (or a
    # single entry) is legal -- the diagnostic then reports a failure, not a
    # skip (see check_parallel_trends).
    pre_period_series: Optional[list[tuple[str, float, float]]] = field(default=None)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def estimate_did(inputs: DiDInputs) -> dict[str, object]:
    """(treat_post - treat_pre) - (control_post - control_pre). Pure
    arithmetic, always computable given non-empty groups."""
    treatment_delta = _mean(inputs.treatment_post) - _mean(inputs.treatment_pre)
    control_delta = _mean(inputs.control_post) - _mean(inputs.control_pre)
    point_estimate = treatment_delta - control_delta
    return {
        "point_estimate": point_estimate,
        "treatment_delta": treatment_delta,
        "control_delta": control_delta,
        "unit": "absolute",
    }


def check_parallel_trends(inputs: DiDInputs,
                           slope_ratio_tolerance: float = PARALLEL_TRENDS_SLOPE_RATIO_TOLERANCE) -> DiagnosticResult:
    """Fits treatment/control pre-period slopes via diagnostics.simple_slope
    and compares them. A single pre-period (k<2) is treated as FAILED, not
    skipped/NOT_APPLICABLE -- absence of evidence for parallel trends is not
    evidence of parallel trends."""
    series = inputs.pre_period_series or []
    k = len(series)
    if k < 2:
        return DiagnosticResult(
            "parallel_trends", False, None, slope_ratio_tolerance,
            f"fewer than 2 pre-treatment periods (k={k}) -- parallel trends cannot be assessed; treated as "
            "FAILED, not skipped, for causal-claim purposes.",
        )
    x = list(range(k))
    treatment_series = [row[1] for row in series]
    control_series = [row[2] for row in series]
    slope_treat, _ = diagnostics.simple_slope(x, treatment_series)
    slope_control, _ = diagnostics.simple_slope(x, control_series)
    slope_diff = abs(slope_treat - slope_control)
    reference_scale = max(abs(slope_treat), abs(slope_control), 1e-9)
    ratio = slope_diff / reference_scale
    passed = ratio <= slope_ratio_tolerance
    detail = (
        f"pre-treatment slopes: treatment={slope_treat:.4f}, control={slope_control:.4f}, "
        f"|diff|/max(|slope|)={ratio:.4f} (tolerance={slope_ratio_tolerance}) over {k} pre-periods."
    )
    return DiagnosticResult("parallel_trends", passed, ratio, slope_ratio_tolerance, detail)


def run_did(hypothesis: CausalHypothesis, inputs: DiDInputs, eligibility: EligibilityReport) -> CausalResult:
    estimate = estimate_did(inputs)
    diag = check_parallel_trends(inputs)
    diagnostics_all_passed = diag.passed

    causal_claim_allowed = diagnostics_all_passed and eligibility.verdict == EligibilityVerdict.ELIGIBLE
    if causal_claim_allowed:
        tier = CausalTier.T3_QUASI_EXPERIMENTAL
    elif diagnostics_all_passed:
        # diagnostics fine, just soft eligibility concerns (e.g. low sample size)
        tier = CausalTier.T2_ARITHMETIC
    else:
        tier = CausalTier.T1_DESCRIPTIVE

    limitations = []
    if not diagnostics_all_passed:
        limitations.append(
            "parallel-trends assumption failed -- this estimate is a naive difference-in-means only, not a "
            "causal effect."
        )
    elif eligibility.verdict != EligibilityVerdict.ELIGIBLE:
        limitations.append(
            "diagnostics passed but eligibility was only partially met -- the causal claim is withheld "
            "pending better data, though the arithmetic estimate is reported."
        )

    confounder_reports = diagnostics.detect_known_confounders(hypothesis)
    confounder_names = diagnostics.report_confounders_never_controlled(confounder_reports)

    status = compute_abstention_status(tier, eligibility.verdict, diagnostics_all_passed, causal_claim_allowed)

    return CausalResult(
        hypothesis_id=hypothesis.hypothesis_id, method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        evidence_tier=tier, status=status, estimate=estimate,
        uncertainty=None,  # no regression library -- no standard error is fabricated for a 2x2 estimate
        assumptions=list(REQUIRED_ASSUMPTIONS), diagnostics=[diag],
        confounders=confounder_names, evidence_ids=[], limitations=limitations,
        causal_claim_allowed=causal_claim_allowed, eligibility_report=eligibility,
    )
