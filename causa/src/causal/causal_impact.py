"""
causal_impact.py — Step 6: optional CausalImpact-style method integration.

Task's own words: "Optional. Do not make it a hard dependency. If unavailable
or unsuitable: return METHOD_UNAVAILABLE and downgrade the evidence tier."

No package providing a CausalImpact-style Bayesian structural time-series
estimator is in requirements.txt today, and this module never adds one --
`is_causal_impact_available()` only PROBES for one via
importlib.util.find_spec, never a top-level hard import, so this file always
imports cleanly whether or not such a package is installed. Since no such
package exists in this environment, `run_causal_impact()` always takes the
METHOD_UNAVAILABLE branch on the real Olist run -- documented explicitly as
the expected, honest state of this repo today (docs/CAUSAL_METHOD_SELECTION.md
§CausalImpact).
"""

from __future__ import annotations

import importlib.util
from typing import Optional

from causal import diagnostics
from causal.diagnostics import compute_abstention_status
from causal.models import (
    CausalHypothesis,
    CausalMethod,
    CausalResult,
    CausalTier,
    DiagnosticResult,
    EligibilityReport,
)

_CANDIDATE_PACKAGE_NAMES = ("causalimpact", "tfcausalimpact")

METHOD_UNAVAILABLE_DIAGNOSTIC_NAME = "dependency_availability"


def is_causal_impact_available() -> bool:
    for name in _CANDIDATE_PACKAGE_NAMES:
        if importlib.util.find_spec(name) is not None:
            return True
    return False


def is_suitable(hypothesis: CausalHypothesis, eligibility: EligibilityReport,
                 inputs: Optional[object] = None) -> tuple[bool, str]:
    """Suitability beyond mere availability: a CausalImpact-style estimator
    needs at least one control/donor series correlated with the outcome
    pre-intervention."""
    if hypothesis.control_group_value is None:
        return False, "no control_group_value set -- CausalImpact needs a donor/control series."
    if "sufficient_pre_period" in eligibility.hard_fail_checks:
        return False, "insufficient pre-period data for a donor-series fit."
    return True, "control group and pre-period data are present."


def _method_unavailable_result(hypothesis: CausalHypothesis, eligibility: EligibilityReport,
                                reason: str) -> CausalResult:
    confounder_reports = diagnostics.detect_known_confounders(hypothesis)
    confounder_names = diagnostics.report_confounders_never_controlled(confounder_reports)
    status = compute_abstention_status(CausalTier.T1_DESCRIPTIVE, eligibility.verdict, False, False)
    return CausalResult(
        hypothesis_id=hypothesis.hypothesis_id, method=CausalMethod.CAUSAL_IMPACT,
        evidence_tier=CausalTier.T1_DESCRIPTIVE,  # hard downgrade, never left at an "aspirational" tier
        status=status, estimate=None, uncertainty=None,
        assumptions=["CausalImpact-style package not usable in this environment/hypothesis."],
        diagnostics=[DiagnosticResult(METHOD_UNAVAILABLE_DIAGNOSTIC_NAME, False, None, None,
                                       f"METHOD_UNAVAILABLE: {reason}")],
        confounders=confounder_names, evidence_ids=[],
        limitations=["Method selection fell back to METHOD_UNAVAILABLE -- tier downgraded to T1_DESCRIPTIVE; "
                     "re-run with a suitable optional dependency installed if a Bayesian structural "
                     "time-series estimate is needed."],
        causal_claim_allowed=False, eligibility_report=eligibility,
    )


def run_causal_impact(hypothesis: CausalHypothesis, eligibility: EligibilityReport,
                       inputs: Optional[object] = None) -> CausalResult:
    if not is_causal_impact_available():
        return _method_unavailable_result(hypothesis, eligibility, "optional causal-impact dependency not importable")
    suitable, reason = is_suitable(hypothesis, eligibility, inputs)
    if not suitable:
        return _method_unavailable_result(hypothesis, eligibility, reason)
    # No installed implementation exists in this environment to call into --
    # by construction this line is unreachable on the real Olist run and is
    # exercised only by a test that monkeypatches is_causal_impact_available
    # AND is_suitable to True, at which point a real integration would be
    # implemented here.
    raise NotImplementedError(
        "A CausalImpact-style package was detected as available and suitable, but no concrete integration "
        "is implemented in this version of causal_impact.py."
    )
