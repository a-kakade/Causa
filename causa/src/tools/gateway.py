"""
gateway.py — Step 5: the Agent Tool Gateway (task §2/§4).

    Agent -> Tool Gateway -> Authentication -> Authorization -> Input
        Validation -> Tool Execution -> Output Validation -> Evidence Object

This is the ONE chokepoint every tool call passes through, whether it was
requested by deterministic code (orchestrator.py's one initial KPI lookup) or
by a real LLM's tool_use/tool_call block (hypothesis_agent.py,
evidence_agent.py, counter_evidence_agent.py). An LLM can propose ANYTHING in
a tool call's arguments -- this module is what turns "propose" into
"actually happens" only when every stage below passes, regardless of how
persuasive, confused, or adversarial the proposing content was (task §5:
prompt injection through a review must produce NO policy change, NO tool
execution, NO data exfiltration).
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from agents.models import AgentRole, AuditTraceEntry, BudgetExceeded, InvestigationState, now_iso
from drivers.engine import DriverRequestError
from evidence.access_control import clearance_sufficient, redact_error_message
from evidence.retrieval import UnauthorizedFilterError, UnsupportedFilterError
from kpi.query_planner import KPIRequestError

from tools import analytics_tools, evidence_tools, policy
from tools.context import ToolContext
from tools.schemas import ToolCallResult, ToolDefinition, ToolParam

# Argument names that would let a caller (LLM or not) attempt to escalate its
# own privilege or reach into investigation control state directly. NEVER a
# declared ToolParam on any tool below -- caught by name here for a specific,
# loggable security_event distinct from a generic "unrecognized argument"
# (task §21 scenarios: "malicious tool arguments", "state manipulation
# attempt", "evidence-filter bypass").
_FORBIDDEN_ARGUMENT_NAMES = frozenset({
    "requester_clearance", "clearance", "state", "status", "investigation_state", "ctx", "context",
})


def _agents_for(tool_name: str) -> frozenset:
    return frozenset(role for role, tools in policy.ALLOWED_TOOLS_PER_AGENT.items() if tool_name in tools)


TOOL_REGISTRY: dict[str, ToolDefinition] = {
    "get_kpi": ToolDefinition(
        tool_name="get_kpi", allowed_agents=_agents_for("get_kpi"),
        input_schema=(
            ToolParam("kpi_id", "str"), ToolParam("start_date", "str"), ToolParam("end_date", "str"),
            ToolParam("dimensions", "list[str]", required=False),
        ),
        output_schema="list[str] evidence_ids (KPI_OBSERVATION)", security_classification="PUBLIC_ANALYTICAL",
        estimated_cost=0.0, estimated_latency_ms=20.0, fn=analytics_tools.get_kpi,
        description="Compute a governed KPI's value over an explicit date range (YYYY-MM-DD), optionally "
                     "grouped by governed dimensions (e.g. product_category, customer_state). Returns "
                     "evidence_ids -- fetch full detail with get_evidence.",
    ),
    "compare_kpi": ToolDefinition(
        tool_name="compare_kpi", allowed_agents=_agents_for("compare_kpi"),
        input_schema=(
            ToolParam("kpi_id", "str"), ToolParam("current_start", "str"), ToolParam("current_end", "str"),
            ToolParam("previous_start", "str"), ToolParam("previous_end", "str"),
        ),
        output_schema="list[str] evidence_ids (KPI_MOVEMENT)", security_classification="PUBLIC_ANALYTICAL",
        estimated_cost=0.0, estimated_latency_ms=30.0, fn=analytics_tools.compare_kpi,
        description="Compute a KPI's period-over-period movement (a FACT, not a materiality/anomaly judgement "
                     "and never a causal claim). Returns one evidence_id.",
    ),
    "get_materiality": ToolDefinition(
        tool_name="get_materiality", allowed_agents=_agents_for("get_materiality"),
        input_schema=(
            ToolParam("kpi_id", "str"), ToolParam("period", "str"), ToolParam("history_months", "list[str]"),
        ),
        output_schema="list[str] evidence_ids (ANOMALY_SIGNAL, STATISTICAL_RESULT)",
        security_classification="PUBLIC_ANALYTICAL", estimated_cost=0.0, estimated_latency_ms=80.0,
        fn=analytics_tools.get_materiality,
        description="Assess whether a KPI's movement in `period` is materially/statistically unusual against "
                     "an explicit list of baseline months (e.g. the prior 10 months). Returns 2 evidence_ids.",
    ),
    "get_driver_decomposition": ToolDefinition(
        tool_name="get_driver_decomposition", allowed_agents=_agents_for("get_driver_decomposition"),
        input_schema=(
            ToolParam("kpi_id", "str"), ToolParam("period_current_start", "str"),
            ToolParam("period_current_end", "str"), ToolParam("period_current_label", "str"),
            ToolParam("period_previous_start", "str"), ToolParam("period_previous_end", "str"),
            ToolParam("period_previous_label", "str"), ToolParam("segment_dimensions", "list[str]", required=False),
            ToolParam("top_n", "int", required=False),
        ),
        output_schema="list[str] evidence_ids (DRIVER_CONTRIBUTION, SEGMENT_CONTRIBUTION)",
        security_classification="INTERNAL", estimated_cost=0.0, estimated_latency_ms=300.0,
        fn=analytics_tools.get_driver_decomposition,
        description="Mathematically decompose a KPI's movement (Price x Volume x Mix) and rank segment "
                     "contributions (e.g. by product_category, customer_state, seller_state, seller). If you omit "
                     "segment_dimensions, only dimensions your clearance can reach are used; explicitly requesting "
                     "a dimension above your clearance is rejected (call fails cleanly) rather than silently "
                     "dropped. Returns evidence_ids.",
    ),
    "get_concurrent_kpis": ToolDefinition(
        tool_name="get_concurrent_kpis", allowed_agents=_agents_for("get_concurrent_kpis"),
        input_schema=(
            ToolParam("kpi_ids", "list[str]"), ToolParam("period_current_start", "str"),
            ToolParam("period_current_end", "str"), ToolParam("period_current_label", "str"),
            ToolParam("period_previous_start", "str"), ToolParam("period_previous_end", "str"),
            ToolParam("period_previous_label", "str"),
        ),
        output_schema="list[str] evidence_ids (CONCURRENT_KPI)", security_classification="PUBLIC_ANALYTICAL",
        estimated_cost=0.0, estimated_latency_ms=60.0, fn=analytics_tools.get_concurrent_kpis,
        description="Report same-period movements in OTHER KPIs as context only -- NEVER combine these into a "
                     "conclusion about the KPI under investigation. Returns one evidence_id per kpi_id.",
    ),
    "search_evidence": ToolDefinition(
        tool_name="search_evidence", allowed_agents=_agents_for("search_evidence"),
        input_schema=(
            ToolParam("semantic_query", "str", required=False), ToolParam("structured_filters", "dict[str,str]", required=False),
            ToolParam("top_k", "int", required=False), ToolParam("time_range_start", "str", required=False),
            ToolParam("time_range_end", "str", required=False), ToolParam("allow_dense_fallback", "bool", required=False),
        ),
        output_schema='{"sufficient": bool, "evidence_ids": [...]} or RetrievalInsufficient fields',
        security_classification="PUBLIC_ANALYTICAL", estimated_cost=0.0, estimated_latency_ms=10.0,
        fn=evidence_tools.search_evidence,
        description="Search governed customer-review evidence (BM25 primary, per Step 4A's own benchmark). "
                     "structured_filters keys: month, category, customer_state, seller_state, seller, "
                     "review_score_min, review_score_max, language, security_status -- an unsupported or "
                     "under-clearance key is rejected outright. If insufficient evidence is found, returns "
                     "sufficient=false with a reason; NEVER pads results with low-confidence matches.",
    ),
    "get_evidence": ToolDefinition(
        tool_name="get_evidence", allowed_agents=_agents_for("get_evidence"),
        input_schema=(ToolParam("evidence_id", "str"),),
        output_schema="dict (full EvidenceObject/EvidenceResult)", security_classification="PUBLIC_ANALYTICAL",
        estimated_cost=0.0, estimated_latency_ms=1.0, fn=evidence_tools.get_evidence,
        description="Fetch the full detail of a previously-returned evidence_id.",
    ),
    "get_graph_neighbors": ToolDefinition(
        tool_name="get_graph_neighbors", allowed_agents=_agents_for("get_graph_neighbors"),
        input_schema=(ToolParam("node_id", "str"),),
        output_schema="list[dict] neighbor nodes/edges", security_classification="PUBLIC_ANALYTICAL",
        estimated_cost=0.0, estimated_latency_ms=2.0, fn=evidence_tools.get_graph_neighbors,
        description="List graph neighbors (both directions) of an evidence/KPI/movement node -- e.g. to find "
                     "CONTRADICTS edges attached to a movement, or the DRIVER nodes a movement is EXPLAINED_BY.",
    ),
}


# ---------------------------------------------------------------------------
# Input validation (task §2's "Input Validation" stage)
# ---------------------------------------------------------------------------

_TYPE_CHECKS = {
    "str": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "list[str]": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "dict[str,str]": lambda v: isinstance(v, dict) and all(isinstance(k, str) and isinstance(x, str) for k, x in v.items()),
}


class InputValidationError(ValueError):
    pass


def validate_input(tool_def: ToolDefinition, arguments: dict) -> dict:
    declared = {p.name: p for p in tool_def.input_schema}
    unknown = set(arguments) - set(declared)
    if unknown:
        raise InputValidationError(f"UNRECOGNIZED_ARGUMENT: {sorted(unknown)} not declared for {tool_def.tool_name!r}.")
    for name, param in declared.items():
        if param.name not in arguments:
            if param.required:
                raise InputValidationError(f"MISSING_REQUIRED_ARGUMENT: {param.name!r} for {tool_def.tool_name!r}.")
            continue
        value = arguments[param.name]
        checker = _TYPE_CHECKS.get(param.type)
        if checker is not None and not checker(value):
            raise InputValidationError(
                f"TYPE_MISMATCH: {param.name!r} expected {param.type!r}, got {type(value).__name__!r}."
            )
        if param.allowed_values is not None and value not in param.allowed_values:
            raise InputValidationError(f"VALUE_NOT_ALLOWED: {param.name!r}={value!r} not in {param.allowed_values!r}.")
    return arguments


def _extract_result_ids(tool_name: str, result: Any) -> list:
    if tool_name == "get_evidence":
        return [result["evidence_id"]] if isinstance(result, dict) and result.get("evidence_id") else []
    if tool_name == "get_graph_neighbors":
        return [n["node_id"] for n in result if isinstance(n, dict) and n.get("node_id")] if isinstance(result, list) else []
    if tool_name == "search_evidence":
        if isinstance(result, dict) and result.get("sufficient"):
            return list(result.get("evidence_ids", []))
        return []
    if isinstance(result, list):
        return list(result)
    return []


def _hash_arguments(arguments: dict) -> str:
    canonical = json.dumps(arguments, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def call_tool(state: InvestigationState, agent_role: AgentRole, tool_name: str, arguments: dict,
              ctx: ToolContext) -> ToolCallResult:
    """The single chokepoint. Six stages, in order; the first failing stage
    short-circuits the rest. Every call (success or failure) appends exactly
    one AuditTraceEntry (task §19) and increments state.budgets."""
    t_start = time.perf_counter()
    arguments = dict(arguments or {})

    # Stage 1: Authentication -- agent_role must be a real AgentRole. Nothing
    # in this codebase exposes call_tool to agent modules with a
    # caller-controlled agent_role (only orchestrator.py and the three
    # LLM-agent modules call it, each hardcoding its OWN role) -- this check
    # is defense-in-depth against a future caller getting it wrong, not the
    # primary defense.
    if not isinstance(agent_role, AgentRole):
        return _deny(state, "UNKNOWN_AGENT_ROLE", agent_role, tool_name, arguments, t_start)

    # Stage 1b (unknown tool): before authorization, since "no such tool"
    # must be indistinguishable from "not authorized for this tool" to a
    # caller probing for a raw-SQL/raw-Python tool that was never registered.
    tool_def = TOOL_REGISTRY.get(tool_name)
    if tool_def is None:
        return _deny(state, "UNKNOWN_TOOL", agent_role, tool_name, arguments, t_start)

    # Stage 2: Authorization -- agent_role must be in this tool's allowlist.
    if not policy.is_tool_allowed(agent_role, tool_name):
        return _deny(state, "UNAUTHORIZED_AGENT_TOOL_PAIR", agent_role, tool_name, arguments, t_start)

    # Stage 3: Clearance derivation -- NEVER trust an agent-supplied
    # clearance/state/status argument. Strip and log, then continue.
    forbidden_present = _FORBIDDEN_ARGUMENT_NAMES & set(arguments)
    if forbidden_present:
        state.security_events.append({
            "type": "clearance_or_state_argument_attempt", "agent_role": agent_role.value, "tool_name": tool_name,
            "rejected_keys": sorted(forbidden_present), "timestamp": now_iso(),
        })
        arguments = {k: v for k, v in arguments.items() if k not in _FORBIDDEN_ARGUMENT_NAMES}
    requester_clearance = policy.clearance_for_role(state.requester_role)

    # Stage 4: Input validation.
    try:
        arguments = validate_input(tool_def, arguments)
    except InputValidationError as exc:
        return _deny(state, str(exc), agent_role, tool_name, arguments, t_start)

    # Budget check (tool_calls always; retrieval_calls additionally for search_evidence).
    try:
        state.budgets.increment("tool_calls")
        if tool_name == "search_evidence":
            state.budgets.increment("retrieval_calls")
    except BudgetExceeded as exc:
        return _deny(state, f"BUDGET_EXCEEDED: {exc}", agent_role, tool_name, arguments, t_start)

    # Stage 5: Tool execution. Every governed "you asked for something your
    # clearance/contract doesn't support" exception the underlying Step
    # 3B/3C/3D/4 engines can raise is caught here and converted into a
    # graceful ok=False denial -- never an uncaught crash of the whole
    # investigation just because an agent (LLM-proposed or not) asked for an
    # explicit dimension/filter it wasn't entitled to.
    try:
        result = tool_def.fn(ctx, requester_clearance, **arguments)
    except (UnsupportedFilterError, UnauthorizedFilterError, KeyError, PermissionError, ValueError,
            DriverRequestError, KPIRequestError) as exc:
        message = redact_error_message(str(exc), requester_clearance)
        return _deny(state, message, agent_role, tool_name, arguments, t_start, security_decision="DENIED")

    # Stage 6: Output validation -- re-check clearance on every returned
    # evidence_id, defense-in-depth even though the tool functions already
    # enforce this internally.
    result_ids = _extract_result_ids(tool_name, result)
    validated_ids = []
    for eid in result_ids:
        ev = ctx.evidence_store.get(eid)
        if ev is None or clearance_sufficient(ev.security.classification.value, requester_clearance):
            validated_ids.append(eid)
        else:
            state.security_events.append({
                "type": "output_filtered", "agent_role": agent_role.value, "tool_name": tool_name,
                "evidence_id": eid, "timestamp": now_iso(),
            })
    if len(validated_ids) != len(result_ids) and isinstance(result, list):
        result = validated_ids

    latency_ms = (time.perf_counter() - t_start) * 1000
    state.audit_trace.append(AuditTraceEntry(
        agent_id=agent_role.value, agent_role=agent_role.value, timestamp=now_iso(),
        input_state_hash=state.state_hash(), tool_call=tool_name, tool_arguments_hash=_hash_arguments(arguments),
        tool_result_ids=validated_ids, output=f"{len(validated_ids)} result item(s)", token_usage=0,
        latency_ms=round(latency_ms, 3), security_decision="ALLOWED",
    ))
    return ToolCallResult(tool_name=tool_name, ok=True, result=result, result_ids=validated_ids)


def _deny(state: InvestigationState, message: str, agent_role: Any, tool_name: str, arguments: dict,
          t_start: float, security_decision: str = "DENIED") -> ToolCallResult:
    latency_ms = (time.perf_counter() - t_start) * 1000
    role_value = agent_role.value if isinstance(agent_role, AgentRole) else str(agent_role)
    state.audit_trace.append(AuditTraceEntry(
        agent_id=role_value, agent_role=role_value, timestamp=now_iso(), input_state_hash=state.state_hash(),
        tool_call=tool_name, tool_arguments_hash=_hash_arguments(arguments), tool_result_ids=[], output=message,
        token_usage=0, latency_ms=round(latency_ms, 3), security_decision=security_decision,
    ))
    return ToolCallResult(tool_name=tool_name, ok=False, error=message)
