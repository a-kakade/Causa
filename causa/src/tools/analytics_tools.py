"""
analytics_tools.py — Step 5: governed structured-analytics tools (task §1C,
§3): get_kpi, compare_kpi, get_materiality, get_driver_decomposition,
get_concurrent_kpis.

STRICT RULE: every function here calls a REAL Step 3B/3C/3D engine
(kpi.engine.KPIEngine, anomaly.engine.detect, drivers.engine.decompose) and
converts the result via evidence.structured_adapter.py -- never recomputes a
KPI itself, never touches data/processed/*.parquet directly, never imports
pandas for its own calculations. Every function's signature is exactly what
its ToolDefinition.input_schema (tools/gateway.py) declares -- `ctx` and
`requester_clearance` are supplied by the Tool Gateway, NEVER by the calling
agent's arguments, so no agent (LLM-driven or not) can request its own
clearance (task §4: "Security must be enforced at tool level, not only in
prompts.").

Every function returns a list[str] (or str) of evidence_ids, storing the
actual EvidenceObject in ctx.evidence_store -- never a bare dataclass, so the
Tool Gateway's output-validation stage (tools/gateway.py) can always re-check
clearance on exactly what gets handed back.
"""

from __future__ import annotations

from typing import Optional

from anomaly import engine as anomaly_engine
from anomaly.models import AnomalyRequest, BaselineLevel, PeriodObservation
from drivers import engine as driver_engine
from drivers.models import ConcurrentKPIMovement, DriverDecompositionRequest
from kpi.models import KPIRequest

from evidence import structured_adapter as adapter

from tools.context import ToolContext


def get_kpi(ctx: ToolContext, requester_clearance: str, kpi_id: str, start_date: str, end_date: str,
            dimensions: Optional[list] = None) -> list[str]:
    """Deterministic KPI observation over one period, optionally grouped by
    governed dimensions. Wraps kpi.engine.KPIEngine.compute -- no recomputation."""
    request = KPIRequest(kpi_id=kpi_id, start_date=start_date, end_date=end_date,
                         dimensions=list(dimensions or []), requester_clearance=requester_clearance)
    result = ctx.kpi_engine.compute(request)
    results = result if isinstance(result, list) else [result]
    ids = []
    for r in results:
        ev = adapter.kpi_result_to_evidence(r, ctx.registry)
        ctx.evidence_store[ev.evidence_id] = ev
        ids.append(ev.evidence_id)
    return ids


def compare_kpi(ctx: ToolContext, requester_clearance: str, kpi_id: str, current_start: str, current_end: str,
                 previous_start: str, previous_end: str) -> list[str]:
    """Deterministic period-over-period movement. Wraps
    kpi.engine.KPIEngine.compare_periods -- a FACT (task §18), never a
    materiality/anomaly judgement and never a causal claim."""
    cmp = ctx.kpi_engine.compare_periods(kpi_id, current_start, current_end, previous_start, previous_end,
                                         requester_clearance=requester_clearance)
    ev = adapter.comparison_result_to_evidence(cmp, ctx.registry)
    ctx.evidence_store[ev.evidence_id] = ev
    return [ev.evidence_id]


def get_materiality(ctx: ToolContext, requester_clearance: str, kpi_id: str, period: str,
                     history_months: list) -> list[str]:
    """Deterministic materiality/anomaly assessment. `history_months` is a
    caller-supplied, explicit list of "YYYY-MM" baseline periods -- kept
    visible in the audit trail rather than a silent default, mirroring
    evidence.engine._build_anomaly_evidence's own BASELINE_HISTORY_MONTHS
    convention but generalized to any kpi_id/period. Wraps
    anomaly.engine.detect -- never invents a verdict."""
    from calendar import monthrange

    def _month_bounds(month: str) -> tuple:
        year, mon = (int(x) for x in month.split("-"))
        return f"{month}-01", f"{month}-{monthrange(year, mon)[1]:02d}"

    history = []
    for month in history_months:
        start, end = _month_bounds(month)
        r = ctx.kpi_engine.compute(KPIRequest(kpi_id=kpi_id, start_date=start, end_date=end,
                                              requester_clearance=requester_clearance))
        history.append(PeriodObservation(period=month, value=r.value, sample_size=r.sample_size,
                                          coverage=r.coverage))

    period_start, period_end = _month_bounds(period)
    observed = ctx.kpi_engine.compute(KPIRequest(kpi_id=kpi_id, start_date=period_start, end_date=period_end,
                                                 requester_clearance=requester_clearance))
    request = AnomalyRequest(
        kpi_id=kpi_id, period=period, observed_value=observed.value, observed_sample_size=observed.sample_size,
        observed_coverage=observed.coverage,
        levels=[BaselineLevel(level="global", label=f"all_{kpi_id}", history=history)],
    )
    result = anomaly_engine.detect(ctx.registry, request)
    evidence_objs = adapter.anomaly_result_to_evidence(result, ctx.registry)   # [signal, statistical]
    ids = []
    for ev in evidence_objs:
        ctx.evidence_store[ev.evidence_id] = ev
        ids.append(ev.evidence_id)
    return ids


def get_driver_decomposition(ctx: ToolContext, requester_clearance: str, kpi_id: str,
                              period_current_start: str, period_current_end: str, period_current_label: str,
                              period_previous_start: str, period_previous_end: str, period_previous_label: str,
                              segment_dimensions: Optional[list] = None, top_n: int = 10) -> list[str]:
    """Deterministic PVM + segment-contribution decomposition. Wraps
    drivers.engine.decompose -- `requester_clearance` is threaded into
    DriverDecompositionRequest here, from the GATEWAY-derived value, never
    from an agent-supplied argument (this tool's public schema has no
    requester_clearance parameter at all -- see tools/gateway.py's
    TOOL_REGISTRY construction)."""
    request = DriverDecompositionRequest(
        kpi_id=kpi_id, period_current_start=period_current_start, period_current_end=period_current_end,
        period_current_label=period_current_label, period_previous_start=period_previous_start,
        period_previous_end=period_previous_end, period_previous_label=period_previous_label,
        segment_dimensions=segment_dimensions, requester_clearance=requester_clearance,
        override_analytical_window=True, top_n=top_n,
    )
    result = driver_engine.decompose(ctx.kpi_engine, ctx.registry, request)
    bundle = adapter.driver_decomposition_result_to_evidence_bundle(result, ctx.registry)
    ids = []
    for ev in bundle:
        ctx.evidence_store[ev.evidence_id] = ev
        ids.append(ev.evidence_id)
    return ids


def get_concurrent_kpis(ctx: ToolContext, requester_clearance: str, kpi_ids: list,
                         period_current_start: str, period_current_end: str, period_current_label: str,
                         period_previous_start: str, period_previous_end: str, period_previous_label: str) -> list[str]:
    """Concurrent-period movements in OTHER KPIs, reported as context only
    (task §15 of Step 3D: never combined into a causal conclusion here or
    anywhere downstream -- evidence_agent.py/counter_evidence_agent.py must
    classify every CONCURRENT_KPI result as CONTEXT, never SUPPORTS/CONTRADICTS,
    see agents/evidence_agent.py's deterministic floor)."""
    ids = []
    for kpi_id in kpi_ids:
        cmp = ctx.kpi_engine.compare_periods(kpi_id, period_current_start, period_current_end,
                                             period_previous_start, period_previous_end,
                                             requester_clearance=requester_clearance)
        movement = ConcurrentKPIMovement(
            kpi_id=kpi_id, previous_value=cmp.previous_value, current_value=cmp.current_value,
            absolute_change=cmp.absolute_change, percentage_change=cmp.percentage_change, warnings=cmp.warnings,
        )
        ev = adapter.concurrent_kpi_to_evidence(kpi_id, movement, period_current_label, period_previous_label,
                                                ctx.registry)
        ctx.evidence_store[ev.evidence_id] = ev
        ids.append(ev.evidence_id)
    return ids
