"""Step 5: Tool Gateway tests (task §2/§4/§21).

Exercises the real gateway against the real ToolContext (agent_ctx fixture,
tests/conftest.py) -- no mocked business logic anywhere in this file.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.models import AgentRole, InvestigationState, RequesterRole  # noqa: E402
from tools import gateway, policy  # noqa: E402


def _fresh_state() -> InvestigationState:
    return InvestigationState(investigation_id="t", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                               period="2017-11")


# ---------------------------------------------------------------------------
# No raw-SQL/raw-Python/state-shaped parameter exists anywhere (task §21:
# "unrestricted SQL attempt", "state manipulation attempt")
# ---------------------------------------------------------------------------

_SUSPICIOUS_SUBSTRINGS = ("sql", "raw_query", "raw_filter", "where", "exec", "python", "code", "command",
                          "state", "status", "clearance")


def test_no_tool_accepts_a_raw_query_sql_or_state_shaped_parameter():
    offenders = []
    for name, td in gateway.TOOL_REGISTRY.items():
        for p in td.input_schema:
            if any(s in p.name.lower() for s in _SUSPICIOUS_SUBSTRINGS):
                offenders.append((name, p.name))
    assert not offenders, f"Suspicious tool parameter names found: {offenders}"


def test_sql_attempt_against_every_registered_tool_is_rejected(agent_ctx):
    state = _fresh_state()
    for tool_name, td in gateway.TOOL_REGISTRY.items():
        agent_role = next(iter(td.allowed_agents))
        result = gateway.call_tool(state, agent_role, tool_name, {"sql": "DROP TABLE fact_orders"}, agent_ctx)
        assert not result.ok
        assert "UNRECOGNIZED_ARGUMENT" in result.error


def test_unknown_tool_name_is_rejected_like_unauthorized(agent_ctx):
    state = _fresh_state()
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "execute_sql", {"sql": "SELECT *"}, agent_ctx)
    assert not result.ok and result.error == "UNKNOWN_TOOL"


def test_no_tool_function_accepts_a_state_or_ctx_parameter_directly():
    """Structural: no governed tool fn signature has a parameter literally
    named state/status/investigation_state -- gateway.call_tool never passes
    one, and this proves there's no accidental seam for it to accept one."""
    for name, td in gateway.TOOL_REGISTRY.items():
        params = set(inspect.signature(td.fn).parameters)
        assert not (params & {"state", "status", "investigation_state"}), name


# ---------------------------------------------------------------------------
# Authorization: every (AgentRole, tool_name) pair NOT in the allowlist is denied
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("agent_role", list(AgentRole))
def test_unauthorized_agent_tool_pairs_denied(agent_ctx, agent_role):
    state = _fresh_state()
    for tool_name in gateway.TOOL_REGISTRY:
        if policy.is_tool_allowed(agent_role, tool_name):
            continue
        result = gateway.call_tool(state, agent_role, tool_name, {}, agent_ctx)
        assert not result.ok
        assert result.error == "UNAUTHORIZED_AGENT_TOOL_PAIR"


def test_orchestrator_has_no_allowed_tools_at_all(agent_ctx):
    state = _fresh_state()
    for tool_name in gateway.TOOL_REGISTRY:
        result = gateway.call_tool(state, AgentRole.ORCHESTRATOR, tool_name, {}, agent_ctx)
        assert not result.ok


# ---------------------------------------------------------------------------
# Clearance derivation: an agent-supplied clearance is stripped and logged,
# never honored (task §21: "unauthorized seller query", "evidence-filter bypass")
# ---------------------------------------------------------------------------

def test_agent_supplied_requester_clearance_is_stripped_and_logged(agent_ctx):
    state = _fresh_state()   # ANALYST -> INTERNAL clearance
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "get_kpi", {
        "kpi_id": "revenue", "start_date": "2017-11-01", "end_date": "2017-11-30", "requester_clearance": "RESTRICTED",
    }, agent_ctx)
    assert result.ok
    assert any(e["type"] == "clearance_or_state_argument_attempt" for e in state.security_events)


def test_unauthorized_seller_query_from_executive_role_is_rejected_not_leaked(agent_ctx):
    """EXECUTIVE -> PUBLIC_ANALYTICAL. Explicitly requesting the
    INTERNAL-classified `seller` segment dimension is REJECTED outright
    (drivers.engine.UnauthorizedSegmentError, caught by the gateway and
    turned into ok=False) -- never silently dropped and never leaked."""
    state = InvestigationState(investigation_id="t2", requester_role=RequesterRole.EXECUTIVE, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "get_driver_decomposition", dict(
        kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
        period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
        period_previous_label="2017-10", segment_dimensions=["seller"], top_n=5,
    ), agent_ctx)
    assert not result.ok
    assert "seller" in result.error and "INTERNAL" in result.error


def test_omitted_segment_dimensions_never_surfaces_internal_evidence_to_executive(agent_ctx):
    """When segment_dimensions is omitted (the model didn't ask for
    anything specific), only clearance-reachable dimensions are used at
    all -- no INTERNAL-classified segment evidence appears for an
    EXECUTIVE-role investigation."""
    state = InvestigationState(investigation_id="t2b", requester_role=RequesterRole.EXECUTIVE, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "get_driver_decomposition", dict(
        kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
        period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
        period_previous_label="2017-10", top_n=5,
    ), agent_ctx)
    assert result.ok
    for eid in result.result_ids:
        ev = agent_ctx.evidence_store[eid]
        assert ev.security.classification.value != "INTERNAL", "seller-level evidence leaked to EXECUTIVE role"


# ---------------------------------------------------------------------------
# Evidence-filter bypass (task §21): an unsupported/unauthorized filter key
# is rejected before any search runs.
# ---------------------------------------------------------------------------

def test_evidence_filter_bypass_with_unsupported_key_rejected(agent_ctx):
    state = _fresh_state()
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "search_evidence", dict(
        semantic_query="x", structured_filters={"customer_id": "abc123"},
    ), agent_ctx)
    assert not result.ok


def test_evidence_filter_bypass_seller_filter_below_clearance_rejected(agent_ctx):
    state = InvestigationState(investigation_id="t3", requester_role=RequesterRole.EXECUTIVE, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "search_evidence", dict(
        semantic_query="x", structured_filters={"seller": "some_seller_id"},
    ), agent_ctx)
    assert not result.ok


# ---------------------------------------------------------------------------
# Budgets surface as ok=False, never a crash (task §9/§21)
# ---------------------------------------------------------------------------

def test_budget_exceeded_surfaces_as_ok_false_not_a_crash(agent_ctx):
    from agents.models import Budgets
    state = _fresh_state()
    state.budgets = Budgets(max_tool_calls=1)
    r1 = gateway.call_tool(state, AgentRole.EVIDENCE, "get_kpi",
                            dict(kpi_id="revenue", start_date="2017-11-01", end_date="2017-11-30"), agent_ctx)
    assert r1.ok
    r2 = gateway.call_tool(state, AgentRole.EVIDENCE, "get_kpi",
                            dict(kpi_id="revenue", start_date="2017-10-01", end_date="2017-10-31"), agent_ctx)
    assert not r2.ok
    assert "BUDGET_EXCEEDED" in r2.error


# ---------------------------------------------------------------------------
# PII extraction attempt (task §21 #6)
# ---------------------------------------------------------------------------

def test_pii_extraction_attempt_via_get_evidence_is_redacted(agent_ctx, monkeypatch):
    """A raw CUSTOMER_REVIEW EvidenceObject's own metadata['text'] is
    unredacted AT THE SOURCE by Step 4's own design (redaction happens only
    at the retrieval layer) -- get_evidence must apply the SAME redaction
    itself, or it becomes a PII-extraction bypass alongside search_evidence.
    Splices one real review evidence_id's underlying object with a synthetic
    PII-bearing text (never mutating the shared corpus) to force a
    detectable case regardless of what PII happens to exist in this corpus
    snapshot."""
    import dataclasses as dc
    from evidence.models import SecurityStatus, TrustLevel
    from evidence.pii import detect_pii

    real_review = next(ev for ev in agent_ctx.evidence_store.values()
                        if getattr(ev, "evidence_type", None) is not None
                        and ev.evidence_type.value == "CUSTOMER_REVIEW")
    pii_text = "meu email e joao@exemplo.com, telefone (11) 91234-5678"
    pii_result = detect_pii(pii_text)
    assert pii_result.pii_detected

    poisoned = real_review.model_copy(update={
        "metadata": {**real_review.metadata, "text": pii_text},
        "security": real_review.security.model_copy(update={
            "trust_level": TrustLevel.UNTRUSTED_DATA, "pii_detected": True, "pii_types": pii_result.pii_types,
        }),
    })
    store = dict(agent_ctx.evidence_store)
    store[poisoned.evidence_id] = poisoned
    poisoned_ctx = dc.replace(agent_ctx, evidence_store=store)

    state = _fresh_state()
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "get_evidence", {"evidence_id": poisoned.evidence_id},
                                poisoned_ctx)
    assert result.ok
    returned_text = result.result["metadata"]["text"]
    assert "joao@exemplo.com" not in returned_text
    assert result.result["security"]["redaction_status"] == "REDACTED_AT_RETRIEVAL"


# ---------------------------------------------------------------------------
# KPI-definition modification attempt (task §21 #7)
# ---------------------------------------------------------------------------

def test_kpi_definition_modification_attempt_rejected(agent_ctx):
    """No tool anywhere accepts a KPI-definition-shaped argument -- an
    attempt to pass one alongside a legitimate get_kpi call is rejected the
    same way any unrecognized argument is."""
    state = _fresh_state()
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "get_kpi", {
        "kpi_id": "revenue", "start_date": "2017-11-01", "end_date": "2017-11-30",
        "definition": {"aggregation": "COUNT", "source_table": "fake_table"},
    }, agent_ctx)
    assert not result.ok and "UNRECOGNIZED_ARGUMENT" in result.error


def test_no_tool_parameter_is_shaped_like_a_kpi_definition_or_config_write():
    offenders = []
    for name, td in gateway.TOOL_REGISTRY.items():
        for p in td.input_schema:
            if any(s in p.name.lower() for s in ("definition", "config", "contract", "yaml", "schema_write")):
                offenders.append((name, p.name))
    assert not offenders, f"Suspicious KPI-definition-shaped parameter names found: {offenders}"


def test_config_kpis_yaml_is_never_opened_for_writing_by_any_tool_module():
    import ast
    for module_name in ("analytics_tools.py", "evidence_tools.py", "context.py", "gateway.py"):
        tree = ast.parse((REPO_ROOT / "src" / "tools" / module_name).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
                mode = node.args[1].value if len(node.args) > 1 and isinstance(node.args[1], ast.Constant) else "r"
                assert "w" not in mode and "a" not in mode, f"{module_name} opens a file for writing: {ast.dump(node)}"


# ---------------------------------------------------------------------------
# Error message redaction (task §21)
# ---------------------------------------------------------------------------

def test_gateway_redacts_raw_id_looking_tokens_below_internal_clearance(agent_ctx, monkeypatch):
    """Direct test of the actual wiring: gateway.call_tool's exception
    handler passes every caught exception's message through
    access_control.redact_error_message before it can reach the caller.
    Uses a realistic raw-hex-shaped id (the exact shape every seller_id/
    customer_id/order_id in this dataset has) rather than depending on
    today's error paths happening to embed one."""
    import dataclasses
    raw_id = "3442f8959a84dea7ee197c632cb2fd6e"   # 32 lowercase hex chars, same shape as a real dataset id
    original = gateway.TOOL_REGISTRY["get_evidence"]

    def _boom(ctx, requester_clearance, **kwargs):
        raise ValueError(f"lookup failed for seller_id {raw_id}")

    monkeypatch.setitem(gateway.TOOL_REGISTRY, "get_evidence", dataclasses.replace(original, fn=_boom))

    low = InvestigationState(investigation_id="t4a", requester_role=RequesterRole.EXECUTIVE, kpi_id="revenue",
                              period="2017-11")
    result_low = gateway.call_tool(low, AgentRole.EVIDENCE, "get_evidence", {"evidence_id": "x"}, agent_ctx)
    assert not result_low.ok and raw_id not in result_low.error

    high = InvestigationState(investigation_id="t4b", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                               period="2017-11")
    result_high = gateway.call_tool(high, AgentRole.EVIDENCE, "get_evidence", {"evidence_id": "x"}, agent_ctx)
    assert not result_high.ok and raw_id in result_high.error   # INTERNAL+ sees the full message


# ---------------------------------------------------------------------------
# Every call, success or failure, produces exactly one audit trace entry (task §19)
# ---------------------------------------------------------------------------

def test_every_call_produces_exactly_one_audit_trace_entry(agent_ctx):
    state = _fresh_state()
    assert len(state.audit_trace) == 0
    gateway.call_tool(state, AgentRole.EVIDENCE, "get_kpi",
                       dict(kpi_id="revenue", start_date="2017-11-01", end_date="2017-11-30"), agent_ctx)
    assert len(state.audit_trace) == 1
    entry = state.audit_trace[0]
    assert entry.agent_role == "EVIDENCE" and entry.tool_call == "get_kpi" and entry.security_decision == "ALLOWED"
    gateway.call_tool(state, AgentRole.CAUSAL_SELECTOR, "search_evidence", {}, agent_ctx)
    assert len(state.audit_trace) == 2
    assert state.audit_trace[1].security_decision == "DENIED"
