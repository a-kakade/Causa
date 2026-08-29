"""
routes/investigations.py — POST/GET /api/investigations, the investigation
lifecycle (§2 of docs/API_INTEGRATION_PLAN.md).

Trigger policy (never silently spends money, never fabricates a result):
  - default + kpi_id=="revenue" + period pair == Nov/Oct 2017 -> replay the
    already-validated causa/reports/step5_validation.json (source="replay").
  - default, any other kpi_id/period -> a real, synchronous
    agents.orchestrator.run_investigation() call with FakeLLMClient (free,
    deterministic, still runs the REAL Steps 3B/3C/3D/4/5 pipeline end to
    end -- only the LLM-authored hypothesis text is scripted/non-live).
  - mode=live -> a real Groq call via agents.orchestrator.run_investigation(),
    only if agents.llm_client.has_groq_credentials() is true.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.bootstrap import REPO_ROOT, EngineBundle
from api.dependencies import get_engine_bundle, get_investigation_store, get_requester_clearance, get_requester_role
from api.serializers import audit_entry_dict, investigation_state_dict, telemetry_record_dict
from api.store import InvestigationRecord, InvestigationStore

router = APIRouter(prefix="/api/investigations", tags=["investigations"])

REVENUE_NOV_2017 = ("revenue", "2017-11", "2017-10")


class CreateInvestigationRequest(BaseModel):
    kpi_id: str
    period_current: str = "2017-11"
    period_previous: str = "2017-10"
    mode: str = "auto"   # "auto" | "live"


def _month_bounds(month: str) -> tuple[str, str]:
    from calendar import monthrange
    year, mon = (int(x) for x in month.split("-"))
    return f"{month}-01", f"{month}-{monthrange(year, mon)[1]:02d}"


def _replay_state(role_value: str):
    """Reconstructs an InvestigationState from the last real validated run in
    reports/step5_validation.json. Never re-runs the orchestrator -- reuses
    the exact, already-audited output the file already holds."""
    from agents.models import (
        AnalyticalMethod, AuditTraceEntry, Budgets, ClassifiedEvidence, ConfidenceLevel, ContradictionRecord,
        ContradictionSeverity, CounterEvidenceReport, EvidenceClassification, Hypothesis, HypothesisResult,
        InvestigationState, InvestigationStatus, MethodSelection, RequesterRole, TelemetryRecord,
    )

    path = REPO_ROOT / "reports" / "step5_validation.json"
    if not path.exists():
        return None
    report = json.loads(path.read_text())
    key = "analyst_investigation" if role_value == "ANALYST" else "executive_investigation"
    d = report.get(key)
    if d is None:
        return None

    state = InvestigationState(
        investigation_id=d["investigation_id"], requester_role=RequesterRole(d["requester_role"]),
        kpi_id=d["kpi_id"], period=d["period"], movement=d.get("movement") or {},
        hypotheses=[Hypothesis(**{k: v for k, v in h.items() if k != "status"}, status=h.get("status", "PROPOSED"))
                    for h in d.get("hypotheses", [])],
        evidence_ids=list(d.get("evidence_ids", [])),
        classified_evidence=[ClassifiedEvidence(
            evidence_id=c["evidence_id"], hypothesis_id=c["hypothesis_id"],
            classification=EvidenceClassification(c["classification"]), rationale=c["rationale"], source_evidence=None,
        ) for c in d.get("classified_evidence", [])],
        counter_evidence_reports=[CounterEvidenceReport(
            hypothesis_id=c["hypothesis_id"], supporting_evidence=c.get("supporting_evidence", []),
            contradicting_evidence=c.get("contradicting_evidence", []),
            unresolved_questions=c.get("unresolved_questions", []),
            contradiction_level=ContradictionSeverity(c.get("contradiction_level", "NONE")),
        ) for c in d.get("counter_evidence_reports", [])],
        contradictions=[ContradictionRecord(
            contradiction_id=c["contradiction_id"], hypothesis_id=c["hypothesis_id"],
            supporting_evidence=c.get("supporting_evidence", []), contradicting_evidence=c.get("contradicting_evidence", []),
            severity=ContradictionSeverity(c.get("severity", "NONE")), unresolved=c.get("unresolved", True),
        ) for c in d.get("contradictions", [])],
        selected_methods=[MethodSelection(
            hypothesis_id=m["hypothesis_id"], method=AnalyticalMethod(m["method"]), justification=m["justification"],
            downgraded=m.get("downgraded", False), downgrade_reason=m.get("downgrade_reason"),
        ) for m in d.get("selected_methods", [])],
        hypothesis_results=[HypothesisResult(
            hypothesis_id=h["hypothesis_id"], status=h["status"], confidence=ConfidenceLevel(h["confidence"]),
            evidence_ids=h.get("evidence_ids", []), reasons=h.get("reasons", []),
            method=AnalyticalMethod(h["method"]) if h.get("method") else None,
            contradiction_severity=ContradictionSeverity(h.get("contradiction_severity", "NONE")),
        ) for h in d.get("hypothesis_results", [])],
        confidence=ConfidenceLevel(d["confidence"]) if d.get("confidence") else None,
        status=InvestigationStatus(d["status"]),
        budgets=Budgets(**{k: v for k, v in (d.get("budgets") or {}).items()}),
        audit_trace=[AuditTraceEntry(**{k: v for k, v in a.items()}) for a in d.get("audit_trace", [])],
        telemetry=[TelemetryRecord(**{k: v for k, v in t.items()}) for t in d.get("telemetry", [])],
        retrieval_insufficiency_events=list(d.get("retrieval_insufficiency_events", [])),
        security_events=list(d.get("security_events", [])),
        status_history=list(d.get("status_history", [])),
    )
    return state


def _tool_call(call_id: str, name: str, arguments: dict):
    from agents.llm_client import LLMResponse
    return LLMResponse(
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": arguments}],
        stop_reason="tool_use", input_tokens=0, output_tokens=0, model="api_scripted_fallback",
        raw_message={"role": "assistant", "content": None,
                     "tool_calls": [{"id": call_id, "type": "function",
                                     "function": {"name": name, "arguments": __import__("json").dumps(arguments)}}]},
    )


def _last_tool_result(messages: list) -> str:
    last = messages[-1]
    return last.get("content", "") if last.get("role") == "tool" else ""


def _extract_ids(content: str) -> list:
    import re
    return re.findall(r'"(ev_[a-zA-Z0-9_]+)"', content)


class _ApiScriptedClient:
    """A real, honest scripted client for the fake_llm investigation path
    (used for any kpi_id other than the canonical Revenue/Nov-2017 scenario,
    which instead replays the already-validated real report). Mirrors
    scripts/step5_investigate_november_2017.py::DryRunScriptedClient's own
    pattern -- only the model's TEXT/decisions are scripted, every tool call
    it makes goes through the REAL Tool Gateway against REAL data for the
    caller's actual kpi_id, never a fabricated result. Generalized (unlike
    the November-2017-specific script version) to work for any governed
    kpi_id, since the API accepts any KPI the frontend investigates."""

    def __init__(self, kpi_id: str):
        self.kpi_id = kpi_id

    def build_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def build_tool_result_messages(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": i, "content": c} for i, c in results]

    def create(self, *, system: str, messages: list, tools: list, max_tokens: int = 4096):
        if "Hypothesis Agent" in system:
            hyps = [{
                "driver": "volume", "dimension": "orders", "mechanism": "order-count expansion",
                "statement": f"{self.kpi_id} movement may be associated with a change in order volume.",
                "expected_evidence": ["DRIVER_CONTRIBUTION:volume"], "falsification_evidence": [],
            }, {
                "driver": "geography", "dimension": "customer_state", "mechanism": "regional concentration",
                "statement": f"The {self.kpi_id} movement may be concentrated in a small number of customer states.",
                "expected_evidence": ["SEGMENT_CONTRIBUTION:customer_state"], "falsification_evidence": [],
            }]
            return _tool_call("h1", "submit_hypotheses", {"hypotheses": hyps})

        if "Evidence Agent" in system:
            content = _last_tool_result(messages)
            if content:
                ids = _extract_ids(content)
                classifications = [{"evidence_id": i, "classification": "SUPPORTS", "rationale": "consistent direction"}
                                    for i in ids[:3]]
                return _tool_call("e2", "submit_evidence_classification", {"classifications": classifications})
            user_text = next((m["content"] for m in messages if m.get("role") == "user"), "")
            if "geograph" in user_text.lower() or "customer_state" in user_text:
                return _tool_call("e1", "get_driver_decomposition", dict(
                    kpi_id=self.kpi_id, period_current_start="2017-11-01", period_current_end="2017-11-30",
                    period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
                    period_previous_label="2017-10", segment_dimensions=["customer_state"], top_n=10))
            return _tool_call("e1", "get_concurrent_kpis", dict(
                kpi_ids=[self.kpi_id], period_current_start="2017-11-01", period_current_end="2017-11-30",
                period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
                period_previous_label="2017-10"))

        content = _last_tool_result(messages)
        if content:
            return _tool_call("c2", "submit_counter_evidence_report", {
                "supporting_evidence": [], "contradicting_evidence": [],
                "unresolved_questions": ["Is the sample size sufficient across every affected segment?"],
                "contradiction_level": "WEAK",
            })
        return _tool_call("c1", "get_concurrent_kpis", dict(
            kpi_ids=[self.kpi_id], period_current_start="2017-11-01", period_current_end="2017-11-30",
            period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
            period_previous_label="2017-10"))


def _fresh_run(bundle: EngineBundle, investigation_id: str, role_value: str, kpi_id: str,
               period_current: str, period_previous: str, live: bool):
    from agents import orchestrator
    from agents.llm_client import GroqLLMClient, has_groq_credentials
    from agents.models import RequesterRole

    if live:
        if not has_groq_credentials():
            raise HTTPException(status_code=400, detail="mode=live requested but no GROQ_API_KEYS are configured "
                                                          "on this server (causa/.env).")
        llm_client = GroqLLMClient()
    else:
        llm_client = _ApiScriptedClient(kpi_id)

    cur_start, cur_end = _month_bounds(period_current)
    prev_start, prev_end = _month_bounds(period_previous)
    state = orchestrator.run_investigation(
        investigation_id=investigation_id, requester_role=RequesterRole(role_value), kpi_id=kpi_id,
        period_current_start=cur_start, period_current_end=cur_end, period_current_label=period_current,
        period_previous_start=prev_start, period_previous_end=prev_end, period_previous_label=period_previous,
        ctx=bundle.ctx, llm_client=llm_client,
    )
    return state


@router.post("")
def create_investigation(
    body: CreateInvestigationRequest,
    bundle: EngineBundle = Depends(get_engine_bundle),
    store: InvestigationStore = Depends(get_investigation_store),
    requester_role: str = Depends(get_requester_role),
):
    if body.kpi_id not in bundle.registry.list_kpi_ids():
        raise HTTPException(status_code=400, detail=f"Unknown kpi_id {body.kpi_id!r}")

    is_canonical_scenario = (body.kpi_id, body.period_current, body.period_previous) == REVENUE_NOV_2017

    if body.mode == "live":
        state = _fresh_run(bundle, f"api_{uuid.uuid4().hex[:12]}", requester_role, body.kpi_id,
                            body.period_current, body.period_previous, live=True)
        source = "live_llm"
    elif body.mode == "auto" and is_canonical_scenario:
        state = _replay_state(requester_role)
        source = "replay"
        if state is None:
            # No validated report on disk yet (e.g. fresh checkout before any
            # scripts/step5_investigate_november_2017.py run) -- fall back to
            # a real FakeLLMClient run rather than fabricating a result.
            state = _fresh_run(bundle, f"api_{uuid.uuid4().hex[:12]}", requester_role, body.kpi_id,
                                body.period_current, body.period_previous, live=False)
            source = "fake_llm"
    else:
        state = _fresh_run(bundle, f"api_{uuid.uuid4().hex[:12]}", requester_role, body.kpi_id,
                            body.period_current, body.period_previous, live=False)
        source = "fake_llm"

    record = InvestigationRecord(
        investigation_id=state.investigation_id, requester_role=requester_role, kpi_id=body.kpi_id,
        period_current=body.period_current, period_previous=body.period_previous, source=source, state=state,
    )
    store.create(record)
    return {**record.to_summary_dict(), "state": investigation_state_dict(state)}


@router.get("")
def list_investigations(
    role: Optional[str] = None, latest: bool = False,
    store: InvestigationStore = Depends(get_investigation_store),
):
    if latest and role:
        record = store.latest_for_role(role)
        return [record.to_summary_dict()] if record else []
    return [r.to_summary_dict() for r in store.list(role_filter=role)]


@router.get("/{investigation_id}")
def get_investigation(investigation_id: str, store: InvestigationStore = Depends(get_investigation_store)):
    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    return {**record.to_summary_dict(), "state": investigation_state_dict(record.state)}


@router.get("/{investigation_id}/hypotheses")
def get_hypotheses(investigation_id: str, store: InvestigationStore = Depends(get_investigation_store)):
    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    results_by_id = {r.hypothesis_id: r for r in record.state.hypothesis_results}
    return {
        "investigation_id": investigation_id,
        "hypotheses": [
            {
                **h.to_dict(),
                "result": results_by_id[h.hypothesis_id].to_dict() if h.hypothesis_id in results_by_id else None,
            }
            for h in record.state.hypotheses
        ],
    }


@router.get("/{investigation_id}/process")
def get_process(investigation_id: str, store: InvestigationStore = Depends(get_investigation_store)):
    """Derived from the completed run's status_history + audit_trace -- the
    orchestrator runs atomically (run_investigation is not steppable), so
    this is a reconstruction of the process trace, not live polling."""
    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    return {
        "investigation_id": investigation_id,
        "status": record.state.status.value,
        "status_history": list(record.state.status_history),
        "audit_trace": [audit_entry_dict(a) for a in record.state.audit_trace],
        "security_events": list(record.state.security_events),
        "retrieval_insufficiency_events": list(record.state.retrieval_insufficiency_events),
    }
