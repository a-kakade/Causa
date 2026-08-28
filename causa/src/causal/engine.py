"""
engine.py — Step 6: the single entry point for the governed causal-analysis
layer.

No LLM import anywhere in this module (or anywhere in src/causal/ --
tests/test_provenance.py::test_no_module_in_causal_package_imports_llm_client
AST-scans every file). run_causal_analysis() never goes through the Step 5
Tool Gateway and needs no new AgentRole -- it calls KPIEngine/SemanticRegistry
and drivers.engine.decompose() directly, the same way Step 4/5's
deterministic pieces already do.

    CausalHypothesis
        |
        v
    eligibility.check_eligibility()            -- 12 checks, always run
        |
        v
    CAUSAL_INELIGIBLE? --yes--> CausalResult(CAUSAL_REJECTED, T1, no method)
        | no
        v
    method_selector.select_method()             -- deterministic, explainable
        |
        v
    dispatch: PVM | DID | ITS | CAUSAL_IMPACT | DESCRIPTIVE_ASSOCIATION | ...
        |
        v
    language_gate.enforce_language_gate()        -- every free-text field
        |
        v
    (optional) _extend_graph()                   -- evidence.graph integration
        |
        v
    CausalResult
"""

from __future__ import annotations

from typing import Any, Optional

import networkx as nx

from drivers.engine import decompose
from drivers.models import DriverDecompositionRequest
from evidence.graph import add_edge, add_kpi_node
from evidence.models import GRAPH_NODE_TYPES, RelationshipType
from evidence.structured_adapter import driver_decomposition_result_to_evidence_bundle
from kpi.engine import KPIEngine
from kpi.models import KPIRequest
from kpi.query_planner import KPIRequestError
from kpi.semantic_registry import SemanticRegistry

from causal import causal_impact, did, interrupted_series, language_gate, method_selector
from causal.diagnostics import compute_abstention_status, detect_known_confounders, report_confounders_never_controlled
from causal.eligibility import check_eligibility
from causal.models import (
    CausalHypothesis,
    CausalMethod,
    CausalResult,
    CausalTier,
    EligibilityReport,
    EligibilityVerdict,
)

# Aspirational tier a method is REACHING for, absent any diagnostic failure --
# used only to decide whether an UPGRADED_TO/DOWNGRADED_TO edge belongs in
# the evidence graph. None means "this method never reaches for more than
# what it always is" (PVM/DESCRIPTIVE_ASSOCIATION/NONE).
_ASPIRATIONAL_TIER: dict[CausalMethod, Optional[CausalTier]] = {
    CausalMethod.DIFFERENCE_IN_DIFFERENCES: CausalTier.T3_QUASI_EXPERIMENTAL,
    CausalMethod.INTERRUPTED_TIME_SERIES: CausalTier.T3_QUASI_EXPERIMENTAL,
    CausalMethod.CAUSAL_IMPACT: CausalTier.T3_QUASI_EXPERIMENTAL,
    CausalMethod.EXPERIMENTAL_RESULT: CausalTier.T4_EXPERIMENTAL,
    CausalMethod.PVM: None,
    CausalMethod.DESCRIPTIVE_ASSOCIATION: None,
    CausalMethod.NONE: None,
}


def _period_bounds(period: dict[str, str]) -> tuple[str, str]:
    if "start" in period and "end" in period:
        return period["start"], period["end"]
    date = period["date"]
    return date, date


# ---------------------------------------------------------------------------
# PVM wrapper (task's §4: reuse Step 3D, never call it causal)
# ---------------------------------------------------------------------------


def run_pvm(hypothesis: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
            eligibility: EligibilityReport, requester_clearance: str = "INTERNAL") -> CausalResult:
    if hypothesis.outcome != "revenue":
        raise ValueError(
            "PVM path only applies when hypothesis.outcome == 'revenue' -- drivers.engine.decompose's own "
            "hard scope restriction."
        )
    t_start, t_end = _period_bounds(hypothesis.treatment_period)
    o_start, o_end = _period_bounds(hypothesis.outcome_period)
    request = DriverDecompositionRequest(
        kpi_id="revenue",
        period_current_start=o_start, period_current_end=o_end, period_current_label=f"{o_start}..{o_end}",
        period_previous_start=t_start, period_previous_end=t_end, period_previous_label=f"{t_start}..{t_end}",
        requester_clearance=requester_clearance,
    )
    result = decompose(kpi_engine, registry, request)  # UNMODIFIED reuse of Step 3D
    evidence_bundle = driver_decomposition_result_to_evidence_bundle(result, registry)
    driver_by_name = {d.driver: d for d in result.drivers}

    confounder_reports = detect_known_confounders(hypothesis)
    confounder_names = report_confounders_never_controlled(confounder_reports)

    status = compute_abstention_status(CausalTier.T2_ARITHMETIC, eligibility.verdict, True, False)

    return CausalResult(
        hypothesis_id=hypothesis.hypothesis_id, method=CausalMethod.PVM,
        evidence_tier=CausalTier.T2_ARITHMETIC,  # ALWAYS, unconditionally
        status=status,
        estimate={
            "volume_effect": driver_by_name["volume"].contribution_value,
            "price_effect": driver_by_name["price"].contribution_value,
            "mix_effect": driver_by_name["mix"].contribution_value,
            "unit": "absolute_revenue",
        },
        uncertainty=None,  # PVM is an exact deterministic decomposition, not a statistical estimate
        assumptions=["mix/price/volume decomposition is exhaustive and reconciles exactly "
                     f"(reconciled={result.reconciliation.reconciled})"],
        diagnostics=[],
        confounders=confounder_names,
        evidence_ids=[e.evidence_id for e in evidence_bundle],
        limitations=["This is a mathematical decomposition of a revenue movement into volume/price/mix "
                     "components. It does not identify why volume, price, or mix changed, and is never a "
                     "causal claim."],
        causal_claim_allowed=False,  # HARD-CODED, never a variable
        eligibility_report=eligibility,
    )


# ---------------------------------------------------------------------------
# Descriptive fallback (DESCRIPTIVE_ASSOCIATION / NONE)
# ---------------------------------------------------------------------------


def _run_descriptive(hypothesis: CausalHypothesis, kpi_engine: KPIEngine, eligibility: EligibilityReport) -> CausalResult:
    o_start, o_end = _period_bounds(hypothesis.outcome_period)
    estimate = None
    try:
        result = kpi_engine.compute(KPIRequest(kpi_id=hypothesis.outcome, start_date=o_start, end_date=o_end))
        if not isinstance(result, list) and result.value is not None:
            estimate = {"value": result.value, "sample_size": result.sample_size, "unit": "observed"}
    except (KPIRequestError, KeyError, ValueError):
        pass

    confounder_reports = detect_known_confounders(hypothesis)
    confounder_names = report_confounders_never_controlled(confounder_reports)
    status = compute_abstention_status(CausalTier.T1_DESCRIPTIVE, eligibility.verdict, True, False)

    return CausalResult(
        hypothesis_id=hypothesis.hypothesis_id, method=CausalMethod.DESCRIPTIVE_ASSOCIATION,
        evidence_tier=CausalTier.T1_DESCRIPTIVE, status=status, estimate=estimate, uncertainty=None,
        assumptions=["association does not imply causation"], diagnostics=[],
        confounders=confounder_names, evidence_ids=[],
        limitations=["No quasi-experimental structure (control group, time-only intervention, or "
                     "randomization) is available for this hypothesis -- only an observed association is "
                     "reported."],
        causal_claim_allowed=False, eligibility_report=eligibility,
    )


def _run_experimental_unimplemented(hypothesis: CausalHypothesis, eligibility: EligibilityReport) -> CausalResult:
    status = compute_abstention_status(CausalTier.T1_DESCRIPTIVE, eligibility.verdict, False, False)
    return CausalResult(
        hypothesis_id=hypothesis.hypothesis_id, method=CausalMethod.EXPERIMENTAL_RESULT,
        evidence_tier=CausalTier.T1_DESCRIPTIVE, status=status, estimate=None, uncertainty=None,
        assumptions=["treatment assignment was genuinely randomized"],
        diagnostics=[], confounders=[], evidence_ids=[],
        limitations=["No experimental-result estimator is implemented in this version -- a hypothesis "
                     "declaring a randomized design defaults to descriptive-only reporting until one exists."],
        causal_claim_allowed=False, eligibility_report=eligibility,
    )


# ---------------------------------------------------------------------------
# DiD / ITS input construction -- real kpi_engine calls only, never fabricated
# ---------------------------------------------------------------------------


def _build_did_inputs(hypothesis: CausalHypothesis, kpi_engine: KPIEngine) -> "did.DiDInputs":
    from causal.eligibility import compute_group_results, group_slice  # reuse, don't duplicate

    t_start, t_end = _period_bounds(hypothesis.treatment_period)
    o_start, o_end = _period_bounds(hypothesis.outcome_period)
    dim = hypothesis.treatment_dimension

    pre_results = compute_group_results(kpi_engine, hypothesis.outcome, dim, t_start, t_end)
    post_results = compute_group_results(kpi_engine, hypothesis.outcome, dim, o_start, o_end)
    treat_pre_val, _ = group_slice(pre_results, dim, hypothesis.treatment_group_value)
    treat_post_val, _ = group_slice(post_results, dim, hypothesis.treatment_group_value)
    ctrl_pre_val, _ = group_slice(pre_results, dim, hypothesis.control_group_value,
                                   exclude_value=hypothesis.treatment_group_value)
    ctrl_post_val, _ = group_slice(post_results, dim, hypothesis.control_group_value,
                                    exclude_value=hypothesis.treatment_group_value)
    return did.DiDInputs(
        treatment_pre=[treat_pre_val or 0.0], treatment_post=[treat_post_val or 0.0],
        control_pre=[ctrl_pre_val or 0.0], control_post=[ctrl_post_val or 0.0],
        pre_period_series=None,  # a real multi-period pre-trend series is a documented future extension;
                                  # never fabricated here -- see docs/CAUSAL_ARCHITECTURE.md §5.
    )


def _build_its_inputs(hypothesis: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry) -> "interrupted_series.ITSInputs":
    contract = registry.get(hypothesis.outcome)
    window = contract["valid_time_window"]
    all_months = list(_month_range(window["default_start"], window["default_end"]))
    t_start, _t_end = _period_bounds(hypothesis.treatment_period)
    intervention_month = t_start[:7]
    intervention_index = all_months.index(intervention_month) if intervention_month in all_months else len(all_months)

    values = []
    for month in all_months:
        start = f"{month}-01"
        end = _month_end(month)
        try:
            result = kpi_engine.compute(KPIRequest(kpi_id=hypothesis.outcome, start_date=start, end_date=end))
            values.append(result.value if not isinstance(result, list) and result.value is not None else 0.0)
        except (KPIRequestError, KeyError, ValueError):
            values.append(0.0)

    return interrupted_series.ITSInputs(period_labels=all_months, values=values, intervention_index=intervention_index)


def _month_range(start: str, end: str) -> list[str]:
    import pandas as pd
    return [str(p) for p in pd.period_range(start=start, end=end, freq="M")]


def _month_end(month: str) -> str:
    import pandas as pd
    period = pd.Period(month, freq="M")
    return str(period.end_time.date())


# ---------------------------------------------------------------------------
# Evidence-graph extension (task §12)
# ---------------------------------------------------------------------------


def _extend_graph(g: nx.MultiDiGraph, hypothesis: CausalHypothesis, method: CausalMethod,
                   result: CausalResult) -> None:
    analysis_node = f"causal_analysis_of_{hypothesis.hypothesis_id}"
    assert "CAUSAL_ANALYSIS" in GRAPH_NODE_TYPES
    g.add_node(analysis_node, node_type="CAUSAL_ANALYSIS", hypothesis_id=hypothesis.hypothesis_id,
               treatment=hypothesis.treatment, outcome=hypothesis.outcome, method=method.value)

    result_node = f"causal_result_of_{hypothesis.hypothesis_id}"
    assert "CAUSAL_RESULT" in GRAPH_NODE_TYPES
    g.add_node(result_node, node_type="CAUSAL_RESULT", evidence_tier=result.evidence_tier.value,
               status=result.status.value, causal_claim_allowed=result.causal_claim_allowed)
    add_edge(g, analysis_node, result_node, RelationshipType.TESTED_BY)

    kpi_node = add_kpi_node(g, hypothesis.outcome)
    add_edge(g, kpi_node, analysis_node, RelationshipType.TESTED_BY)

    for evidence_id in result.evidence_ids:
        if evidence_id in g:
            add_edge(g, evidence_id, result_node, RelationshipType.SUPPORTED_BY)

    for i, assumption in enumerate(result.assumptions):
        node_id = f"assumption_of_{result_node}_{i}"
        assert "ASSUMPTION" in GRAPH_NODE_TYPES
        g.add_node(node_id, node_type="ASSUMPTION", text=assumption)
        add_edge(g, result_node, node_id, RelationshipType.HAS_ASSUMPTION)

    for i, diag in enumerate(result.diagnostics):
        node_id = f"diagnostic_of_{result_node}_{i}"
        assert "DIAGNOSTIC" in GRAPH_NODE_TYPES
        g.add_node(node_id, node_type="DIAGNOSTIC", name=diag.diagnostic_name, passed=diag.passed, detail=diag.detail)
        add_edge(g, result_node, node_id, RelationshipType.HAS_DIAGNOSTIC)
        if not diag.passed:
            add_edge(g, result_node, node_id, RelationshipType.REJECTED_BY)

    aspirational = _ASPIRATIONAL_TIER.get(method)
    if aspirational is not None and aspirational != result.evidence_tier:
        add_edge(g, result_node, kpi_node, RelationshipType.DOWNGRADED_TO,
                 note=f"{aspirational.value} -> {result.evidence_tier.value}")


# ---------------------------------------------------------------------------
# The entry point
# ---------------------------------------------------------------------------


def run_causal_analysis(hypothesis: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                         graph: Optional[nx.MultiDiGraph] = None, requester_clearance: str = "INTERNAL") -> CausalResult:
    eligibility = check_eligibility(hypothesis, kpi_engine, registry, requester_clearance)

    if eligibility.verdict == EligibilityVerdict.CAUSAL_INELIGIBLE:
        result = CausalResult(
            hypothesis_id=hypothesis.hypothesis_id, method=CausalMethod.NONE,
            evidence_tier=CausalTier.T1_DESCRIPTIVE, status=compute_abstention_status(
                CausalTier.T1_DESCRIPTIVE, eligibility.verdict, False, False),
            estimate=None, uncertainty=None, assumptions=[], diagnostics=[], confounders=[], evidence_ids=[],
            limitations=["Temporal ordering between treatment and outcome could not be established -- causal "
                         "interpretation is structurally ineligible; no method was attempted."],
            causal_claim_allowed=False, eligibility_report=eligibility,
        )
        selected_method = CausalMethod.NONE
    else:
        selection = method_selector.select_method(hypothesis, eligibility)
        selected_method = selection.method
        if selection.method == CausalMethod.PVM:
            result = run_pvm(hypothesis, kpi_engine, registry, eligibility, requester_clearance)
        elif selection.method == CausalMethod.DIFFERENCE_IN_DIFFERENCES:
            inputs = _build_did_inputs(hypothesis, kpi_engine)
            result = did.run_did(hypothesis, inputs, eligibility)
        elif selection.method == CausalMethod.INTERRUPTED_TIME_SERIES:
            inputs = _build_its_inputs(hypothesis, kpi_engine, registry)
            result = interrupted_series.run_its(hypothesis, inputs, eligibility)
        elif selection.method == CausalMethod.CAUSAL_IMPACT:
            result = causal_impact.run_causal_impact(hypothesis, eligibility)
        elif selection.method == CausalMethod.EXPERIMENTAL_RESULT:
            result = _run_experimental_unimplemented(hypothesis, eligibility)
        else:  # DESCRIPTIVE_ASSOCIATION, NONE
            result = _run_descriptive(hypothesis, kpi_engine, eligibility)

    for field_name in ("limitations", "assumptions"):
        cleaned = [language_gate.enforce_language_gate(text, f"CausalResult.{field_name}", result.causal_claim_allowed)
                   for text in getattr(result, field_name)]
        setattr(result, field_name, cleaned)

    if graph is not None:
        _extend_graph(graph, hypothesis, selected_method, result)

    return result


# ---------------------------------------------------------------------------
# Optional bridge from a Step 5 Hypothesis -- not load-bearing for the Olist
# validation (docs/CAUSAL_ARCHITECTURE.md §3)
# ---------------------------------------------------------------------------

_DRIVER_TO_TREATMENT = {"volume": "orders", "price": "revenue", "mix": "revenue"}


def causal_hypothesis_from_step5(step5_hypothesis: Any, investigation_state: Any) -> Optional[CausalHypothesis]:
    """Best-effort converter: maps a Step 5 agents.models.Hypothesis into a
    CausalHypothesis using its driver/dimension fields and the parent
    InvestigationState's kpi_id/period. Returns None (never raises) when the
    mapping cannot produce a structurally valid hypothesis -- callers (e.g.
    scripts/step6_causal_validation.py) fall back to a manually-authored
    CausalHypothesis for that slot, which is exactly what happens for the
    real November 2017 investigation today (Step 5's real hypotheses are
    ABSTAINED/INSUFFICIENT_DATA with no usable evidence_ids to build from --
    see STEP5_VALIDATION.md §14)."""
    driver = getattr(step5_hypothesis, "driver", None)
    outcome = getattr(investigation_state, "kpi_id", None)
    period = getattr(investigation_state, "period", None)
    if driver is None or outcome is None or period is None:
        return None
    treatment = _DRIVER_TO_TREATMENT.get(driver)
    if treatment is None:
        return None
    period_dict = {"date": f"{period}-01"}
    try:
        return CausalHypothesis(
            hypothesis_id=f"from_step5_{step5_hypothesis.hypothesis_id}",
            treatment=treatment, outcome=outcome, unit_of_analysis="order",
            treatment_period=period_dict, outcome_period=period_dict,
            proposed_mechanism=f"{treatment} is associated with {outcome} via the {driver} component.",
            required_data=[treatment, outcome], proposed_method=CausalMethod.PVM if outcome == "revenue"
            else CausalMethod.DESCRIPTIVE_ASSOCIATION,
            source="STEP5_HYPOTHESIS",
        )
    except ValueError:
        return None
