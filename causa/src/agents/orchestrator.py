"""
orchestrator.py — Step 5: the Orchestrator Agent (task §1A).

100% DETERMINISTIC. No LLM call anywhere in this module. Responsibilities
(task's own list): receive the investigation request, construct the plan
(here: the fixed 9-stage pipeline the state machine already encodes),
delegate to each specialist agent in order, maintain InvestigationState,
enforce budgets, decide when to stop, trigger confidence evaluation,
terminate. "The Orchestrator must NOT independently generate business
conclusions" is a STRUCTURAL property of this module, not just a
description: it never imports evidence.schema and never constructs a
Hypothesis/ClassifiedEvidence/MethodSelection/HypothesisResult itself
(tests/test_orchestrator.py's AST scan enforces this) -- it only calls the
five specialist agent modules and reads their outputs off InvestigationState.

The one exception, explicit and attributed: before hypotheses can be
generated, SOMETHING has to make the first `compare_kpi` call to know the
KPI's movement at all. That one call is made here directly (not via an LLM
loop -- it's a fixed, read-only, non-conclusory lookup) but is attributed to
AgentRole.EVIDENCE in the audit trail, through the exact same
tools/gateway.call_tool() chokepoint every other tool call uses -- never
AgentRole.ORCHESTRATOR, which has an empty tool allowlist by design
(tools/policy.ALLOWED_TOOLS_PER_AGENT[ORCHESTRATOR] == frozenset()).
"""

from __future__ import annotations

import time
from typing import Optional

from agents import causal_selector, confidence_judge, counter_evidence_agent, evidence_agent, hypothesis_agent
from agents.llm_client import LLMClient
from agents.models import (
    AgentRole,
    Budgets,
    BudgetExceeded,
    ConfidenceLevel,
    InvestigationState,
    InvestigationStatus,
    RequesterRole,
)
from agents.state_machine import transition
from agents.telemetry import record_deterministic_call
from tools import gateway, policy
from tools.context import ToolContext

_S = InvestigationStatus


def _stage(state: InvestigationState, fn, *args) -> None:
    """Runs one deterministic-orchestration-level pipeline stage, charging
    it against the iteration budget. `fn` is one of the specialist agent
    module functions -- this wrapper never inspects or constructs their
    output types, only calls them and lets BudgetExceeded propagate."""
    t0 = time.perf_counter()
    state.budgets.increment("iterations")
    fn(state, *args)
    record_deterministic_call(state, AgentRole.ORCHESTRATOR, (time.perf_counter() - t0) * 1000)


def run_investigation(*, investigation_id: str, requester_role: RequesterRole, kpi_id: str,
                       period_current_start: str, period_current_end: str, period_current_label: str,
                       period_previous_start: str, period_previous_end: str, period_previous_label: str,
                       ctx: ToolContext, llm_client: LLMClient, budgets: Optional[Budgets] = None) -> InvestigationState:
    state = InvestigationState(
        investigation_id=investigation_id, requester_role=requester_role, kpi_id=kpi_id, period=period_current_label,
        budgets=budgets or Budgets(),
    )

    # PLANNED -> validate the request is even answerable before spending
    # any budget on it.
    if kpi_id not in ctx.registry.list_kpi_ids() or requester_role not in policy.RBAC_CLEARANCE_FOR_ROLE:
        transition(state, _S.NEEDS_CLARIFICATION, reason="unknown kpi_id or requester_role")
        return state

    transition(state, _S.SECURITY_VALIDATED)

    # The one Orchestrator-triggered tool call: attributed to EVIDENCE, per
    # module docstring above.
    try:
        state.budgets.increment("iterations")
        call_result = gateway.call_tool(state, AgentRole.EVIDENCE, "compare_kpi", dict(
            kpi_id=kpi_id, current_start=period_current_start, current_end=period_current_end,
            previous_start=period_previous_start, previous_end=period_previous_end,
        ), ctx)
    except BudgetExceeded as exc:
        transition(state, _S.BUDGET_EXCEEDED, reason=str(exc))
        return state
    if not call_result.ok or not call_result.result_ids:
        transition(state, _S.NEEDS_CLARIFICATION, reason=f"could not establish {kpi_id} movement: {call_result.error}")
        return state
    movement_ev = ctx.evidence_store[call_result.result_ids[0]]
    state.movement = {
        "absolute": movement_ev.value.value,
        "percentage": movement_ev.metadata.get("percentage_change"),
        "current_value": movement_ev.metadata.get("current_value"),
        "previous_value": movement_ev.metadata.get("previous_value"),
    }

    stages = [
        (_S.HYPOTHESES_GENERATED, hypothesis_agent.generate_hypotheses, (llm_client, ctx)),
        (_S.EVIDENCE_COLLECTION, evidence_agent.collect_evidence, (llm_client, ctx)),
        (_S.COUNTER_EVIDENCE, counter_evidence_agent.collect_counter_evidence, (llm_client, ctx)),
        (_S.CONTRADICTION_ANALYSIS, counter_evidence_agent.build_contradiction_records, (ctx,)),
        (_S.METHOD_SELECTION, causal_selector.select_methods, ()),
        (_S.CONFIDENCE_EVALUATION, confidence_judge.evaluate, ()),
    ]
    for target_status, fn, extra_args in stages:
        try:
            _stage(state, fn, *extra_args)
        except BudgetExceeded as exc:
            transition(state, _S.BUDGET_EXCEEDED, reason=str(exc))
            return state
        transition(state, target_status)
        if target_status == _S.HYPOTHESES_GENERATED and not state.hypotheses:
            transition(state, _S.ABSTAINED, reason="no hypothesis cleared its evidence-gated trigger condition")
            return state

    if state.confidence == ConfidenceLevel.ABSTAIN:
        transition(state, _S.ABSTAINED, reason="confidence judge abstained on every hypothesis")
    elif state.confidence == ConfidenceLevel.NEEDS_CLARIFICATION:
        transition(state, _S.NEEDS_CLARIFICATION, reason="confidence judge requested clarification")
    else:
        transition(state, _S.COMPLETED)
    return state
