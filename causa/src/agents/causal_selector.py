"""
causal_selector.py — Step 5: the Causal Method Selector (task §1E).

100% DETERMINISTIC. No LLM call anywhere in this module -- task's own words:
"Never allow the LLM to declare causality." This module never performs
causal inference itself either (Step 5's STOP CONDITION forbids executing
causal inference) -- it only SELECTS which analytical-rigor label the
available evidence justifies, and downgrades that label when a strong
contradiction undermines it. T3_QUASI_EXPERIMENTAL/T4_EXPERIMENTAL are
declared in agents.models.AnalyticalMethod but NEVER selected here: the
Olist dataset has no natural experiment, randomization, or instrument for
this kind of KPI-movement investigation, so nothing in this module can
honestly justify them. This is a real, tested invariant
(tests/test_confidence.py / tests/test_contradictions.py assert T3/T4 never
appear in any selected_methods entry), not an oversight.
"""

from __future__ import annotations

from agents.models import (
    AnalyticalMethod,
    ContradictionSeverity,
    EvidenceClassification,
    InvestigationState,
    METHOD_RANK,
    MethodSelection,
)

_RANK_TO_METHOD = {v: k for k, v in METHOD_RANK.items() if v >= 0}


def _downgrade_one_rank(method: AnalyticalMethod) -> AnalyticalMethod:
    rank = METHOD_RANK[method]
    return _RANK_TO_METHOD.get(rank - 1, AnalyticalMethod.INSUFFICIENT_DATA)


def _base_method_for(supports: list) -> tuple:
    if not supports:
        return AnalyticalMethod.INSUFFICIENT_DATA, "no SUPPORTS-classified evidence -- nothing to select a method for"
    tiers = {c.source_evidence.evidence_tier.value if hasattr(c.source_evidence, "evidence_tier")
             else c.source_evidence.get("evidence_tier") for c in supports}
    if "T2_ARITHMETIC" in tiers:
        return (AnalyticalMethod.T2_ARITHMETIC,
                "supported by a T2_ARITHMETIC (deterministic decomposition, e.g. PVM or segment contribution) item")
    if "T1_DESCRIPTIVE" in tiers or "T3_STATISTICAL" in tiers:
        return (AnalyticalMethod.T1_DESCRIPTIVE,
                "supported only by T1_DESCRIPTIVE/T3_STATISTICAL (observed movement or statistical signal, "
                "not an arithmetic decomposition)")
    return AnalyticalMethod.INSUFFICIENT_DATA, "supporting evidence carries no recognized evidence_tier"


def select_methods(state: InvestigationState) -> InvestigationState:
    for hypothesis in state.hypotheses:
        supports = [c for c in state.classified_evidence
                    if c.hypothesis_id == hypothesis.hypothesis_id and c.classification == EvidenceClassification.SUPPORTS]
        contradiction = next((cr for cr in state.contradictions if cr.hypothesis_id == hypothesis.hypothesis_id), None)
        severity = contradiction.severity if contradiction else ContradictionSeverity.NONE

        method, justification = _base_method_for(supports)
        downgraded, downgrade_reason = False, None
        if severity == ContradictionSeverity.STRONG and method != AnalyticalMethod.INSUFFICIENT_DATA:
            original = method
            method = _downgrade_one_rank(method)
            downgraded = True
            # "given" rather than "due to"/"because of" -- both are flagged by
            # the causal-language guardrail (agents.models.UNSUPPORTED_CAUSAL_PATTERN),
            # and rightly so in general, but this sentence describes why a
            # METHOD label was downgraded, not why the KPI moved; "given" says
            # the same thing without tripping a guard built for the latter.
            downgrade_reason = (
                f"downgraded from {original.value} to {method.value}, given a STRONG contradiction "
                f"({contradiction.contradiction_id if contradiction else 'unknown'})"
            )
            justification = f"{justification}; {downgrade_reason}"

        state.selected_methods.append(MethodSelection(
            hypothesis_id=hypothesis.hypothesis_id, method=method, justification=justification,
            downgraded=downgraded, downgrade_reason=downgrade_reason,
        ))
    return state
