"""
method_selector.py — Step 6: deterministic method selection.

No LLM import anywhere in this file (verified by
tests/test_provenance.py::test_engine_never_imports_llm_client_ast_scan,
which scans every file in src/causal/, not just this one). Selection is a
fixed-order decision table, evaluated top-to-bottom -- first match wins.
Nothing here iterates a dict/set whose order is not fixed, so calling
select_method twice with identical inputs always yields an identical
MethodSelectionResult (tests/test_method_selector.py::
test_method_selection_is_deterministic_given_identical_inputs`).
"""

from __future__ import annotations

from causal import causal_impact
from causal.models import CausalHypothesis, CausalMethod, EligibilityReport, EligibilityVerdict, MethodSelectionResult

# Static per-method assumption lists (task's "required_assumptions").
_REQUIRED_ASSUMPTIONS: dict[CausalMethod, tuple[str, ...]] = {
    CausalMethod.DESCRIPTIVE_ASSOCIATION: ("association does not imply causation",),
    CausalMethod.PVM: ("mix/price/volume decomposition is exhaustive and reconciles exactly",),
    CausalMethod.DIFFERENCE_IN_DIFFERENCES: (
        "parallel pre-treatment trends", "no concurrent confounding intervention",
        "stable unit composition across periods",
    ),
    CausalMethod.INTERRUPTED_TIME_SERIES: (
        "no concurrent intervention at the same date", "stable KPI definition across the full window",
        "residual autocorrelation does not invalidate inference",
    ),
    CausalMethod.CAUSAL_IMPACT: ("a suitable control/donor series exists and is available",),
    CausalMethod.EXPERIMENTAL_RESULT: ("treatment assignment was genuinely randomized",),
    CausalMethod.NONE: (),
}

# Every non-selected method's rejection reason is generated from this fixed
# template map, filled with the concrete failing condition -- never free text.
_REJECTION_TEMPLATES: dict[CausalMethod, str] = {
    CausalMethod.PVM: "PVM rejected: outcome is not 'revenue' or the hypothesis is not a volume/price/mix "
                      "decomposition question.",
    CausalMethod.DESCRIPTIVE_ASSOCIATION: "DESCRIPTIVE_ASSOCIATION rejected: a more specific method was already "
                                          "selected.",
    CausalMethod.DIFFERENCE_IN_DIFFERENCES: "DIFFERENCE_IN_DIFFERENCES rejected: {did_reason}",
    CausalMethod.INTERRUPTED_TIME_SERIES: "INTERRUPTED_TIME_SERIES rejected: {its_reason}",
    CausalMethod.CAUSAL_IMPACT: "CAUSAL_IMPACT rejected: {ci_reason}",
    CausalMethod.EXPERIMENTAL_RESULT: "EXPERIMENTAL_RESULT rejected: no randomization/treatment-assignment "
                                      "field exists in required_data.",
    CausalMethod.NONE: "NONE rejected: a usable method was found.",
}

_PVM_TREATMENTS = {"volume", "price", "mix", "orders", "quantity_sold"}


def _did_eligible(hypothesis: CausalHypothesis, eligibility: EligibilityReport) -> tuple[bool, str]:
    if hypothesis.treatment_group_value is None or hypothesis.control_group_value is None:
        return False, "control_group_value and/or treatment_group_value is not set on this hypothesis."
    if "sufficient_pre_period" in eligibility.hard_fail_checks:
        return False, "sufficient_pre_period hard-failed."
    if "treatment_precedes_outcome" in eligibility.hard_fail_checks:
        return False, "treatment_precedes_outcome hard-failed."
    return True, "treatment/control groups and sufficient pre-period data are present."


def _its_eligible(hypothesis: CausalHypothesis, eligibility: EligibilityReport) -> tuple[bool, str]:
    if hypothesis.treatment_dimension is not None:
        return False, "hypothesis has a treatment_dimension (a group-based comparison), not a time-only " \
                       "intervention."
    if "sufficient_pre_period" in eligibility.hard_fail_checks or \
       "sufficient_post_period" in eligibility.hard_fail_checks:
        return False, "sufficient_pre_period and/or sufficient_post_period hard-failed."
    return True, "a time-only intervention with sufficient pre/post period data is present."


def select_method(hypothesis: CausalHypothesis, eligibility: EligibilityReport,
                   diagnostics_probe: object = None) -> MethodSelectionResult:
    did_ok, did_reason = _did_eligible(hypothesis, eligibility)
    its_ok, its_reason = _its_eligible(hypothesis, eligibility)
    ci_available, ci_reason = causal_impact.is_causal_impact_available(), (
        "optional dependency not installed" if not causal_impact.is_causal_impact_available() else "available"
    )
    ci_ok = ci_available and hypothesis.control_group_value is not None

    is_pvm_hypothesis = hypothesis.outcome == "revenue" and (
        hypothesis.proposed_method == CausalMethod.PVM or hypothesis.treatment in _PVM_TREATMENTS
    )
    is_experimental = (
        hypothesis.proposed_method == CausalMethod.EXPERIMENTAL_RESULT
        and any("randomiz" in item.lower() for item in hypothesis.assumptions)
        and any("randomiz" in item.lower() for item in hypothesis.required_data)
    )

    if eligibility.verdict == EligibilityVerdict.CAUSAL_INELIGIBLE:
        selected = CausalMethod.NONE
        why_selected = "eligibility verdict is CAUSAL_INELIGIBLE -- temporal ordering between treatment and " \
                       "outcome could not be established, so no method can license a claim."
    elif is_pvm_hypothesis:
        selected = CausalMethod.PVM
        why_selected = "outcome is 'revenue' and the hypothesis targets a volume/price/mix component -- PVM " \
                       "is a reused, exact, deterministic decomposition (Step 3D)."
    elif eligibility.verdict == EligibilityVerdict.INELIGIBLE:
        selected = CausalMethod.NONE
        why_selected = "eligibility verdict is INELIGIBLE -- no quasi-experimental method is defensible; " \
                       "falls back to a plain descriptive association where the underlying data still exists."
    elif did_ok:
        selected = CausalMethod.DIFFERENCE_IN_DIFFERENCES
        why_selected = f"treatment/control groups and sufficient pre-period data are present: {did_reason}"
    elif its_ok:
        selected = CausalMethod.INTERRUPTED_TIME_SERIES
        why_selected = f"a time-only intervention with a known date is present: {its_reason}"
    elif ci_ok:
        selected = CausalMethod.CAUSAL_IMPACT
        why_selected = "an optional CausalImpact-style dependency is available and a control/donor series exists."
    elif is_experimental:
        selected = CausalMethod.EXPERIMENTAL_RESULT
        why_selected = "the hypothesis explicitly declares a randomization/RCT-style design with a real " \
                       "randomization field in required_data."
    else:
        selected = CausalMethod.DESCRIPTIVE_ASSOCIATION
        why_selected = "treatment and outcome both resolve, but no quasi-experimental structure (control " \
                       "group, time-only intervention, or randomization) is present."

    why_other_methods_rejected: dict[str, str] = {}
    for method in CausalMethod:
        if method == selected:
            continue
        template = _REJECTION_TEMPLATES[method]
        if method == CausalMethod.DIFFERENCE_IN_DIFFERENCES:
            why_other_methods_rejected[method.value] = template.format(
                did_reason=did_reason if not did_ok else "a higher-priority method was already selected.")
        elif method == CausalMethod.INTERRUPTED_TIME_SERIES:
            why_other_methods_rejected[method.value] = template.format(
                its_reason=its_reason if not its_ok else "a higher-priority method was already selected.")
        elif method == CausalMethod.CAUSAL_IMPACT:
            why_other_methods_rejected[method.value] = template.format(
                ci_reason=ci_reason if not ci_available else
                ("no control_group_value set." if not ci_ok else "a higher-priority method was already selected."))
        else:
            why_other_methods_rejected[method.value] = template

    return MethodSelectionResult(
        hypothesis_id=hypothesis.hypothesis_id, method=selected, why_selected=why_selected,
        why_other_methods_rejected=why_other_methods_rejected,
        required_assumptions=list(_REQUIRED_ASSUMPTIONS[selected]), eligibility_verdict=eligibility.verdict,
    )
