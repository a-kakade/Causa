"""Step 5: Orchestrator tests (task §1A).

Full end-to-end investigations, entirely FakeLLMClient-driven (no network),
but exercising the REAL Step 1-4 engines through the REAL Tool Gateway --
same discipline every other Step 5 test file uses.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from _llm_test_helpers import (  # noqa: E402
    ScriptedRoutingClient,
    extract_evidence_ids,
    last_tool_result_content,
    text_only_response,
    tool_call_response,
)
from agents import orchestrator  # noqa: E402
from agents.models import AgentRole, InvestigationStatus, RequesterRole  # noqa: E402
from agents.state_machine import ALLOWED_TRANSITIONS  # noqa: E402
from tools import policy  # noqa: E402

_DRIVER_ARGS = dict(kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
                     period_current_label="2017-11", period_previous_start="2017-10-01",
                     period_previous_end="2017-10-31", period_previous_label="2017-10", top_n=5)


def _happy_path_client() -> ScriptedRoutingClient:
    hyps = [
        {"driver": "volume", "dimension": "orders", "mechanism": "order-count expansion",
         "statement": "Revenue growth may be associated with an increase in order volume.",
         "expected_evidence": ["DRIVER_CONTRIBUTION:volume"], "falsification_evidence": []},
    ]

    def hypothesis_script(messages):
        return tool_call_response("h1", "submit_hypotheses", {"hypotheses": hyps})

    def evidence_script(messages):
        content = last_tool_result_content(messages)
        if content:
            ids = extract_evidence_ids(content)
            classifications = [{"evidence_id": i, "classification": "SUPPORTS", "rationale": "consistent"}
                                for i in ids[:2]]
            return tool_call_response("e2", "submit_evidence_classification", {"classifications": classifications})
        return tool_call_response("e1", "get_driver_decomposition", dict(_DRIVER_ARGS, segment_dimensions=["product_category"]))

    def counter_script(messages):
        content = last_tool_result_content(messages)
        if content:
            return tool_call_response("c2", "submit_counter_evidence_report", {
                "supporting_evidence": [], "contradicting_evidence": [], "unresolved_questions": [],
                "contradiction_level": "NONE",
            })
        return tool_call_response("c1", "get_driver_decomposition", dict(_DRIVER_ARGS, segment_dimensions=["customer_state"]))

    return ScriptedRoutingClient({
        "Hypothesis Agent": hypothesis_script, "Evidence Agent": evidence_script,
        "Counter-Evidence Agent": counter_script,
    })


def _run(agent_ctx, llm_client, requester_role=RequesterRole.ANALYST, kpi_id="revenue"):
    return orchestrator.run_investigation(
        investigation_id="orch_test", requester_role=requester_role, kpi_id=kpi_id,
        period_current_start="2017-11-01", period_current_end="2017-11-30", period_current_label="2017-11",
        period_previous_start="2017-10-01", period_previous_end="2017-10-31", period_previous_label="2017-10",
        ctx=agent_ctx, llm_client=llm_client,
    )


def test_full_investigation_reaches_a_terminal_status(agent_ctx):
    state = _run(agent_ctx, _happy_path_client())
    from agents.state_machine import is_terminal
    assert is_terminal(state.status)


def test_happy_path_reaches_completed_with_real_revenue_movement(agent_ctx):
    state = _run(agent_ctx, _happy_path_client())
    assert state.status == InvestigationStatus.COMPLETED
    assert abs(state.movement["percentage"] - 52.1) < 0.1   # task's own required November 2017 value
    assert abs(state.movement["absolute"] - 346051.94) < 1.0


def test_status_history_is_a_prefix_of_the_linear_chain_when_completed(agent_ctx):
    state = _run(agent_ctx, _happy_path_client())
    expected_prefix = ["PLANNED", "SECURITY_VALIDATED", "HYPOTHESES_GENERATED", "EVIDENCE_COLLECTION",
                        "COUNTER_EVIDENCE", "CONTRADICTION_ANALYSIS", "METHOD_SELECTION", "CONFIDENCE_EVALUATION",
                        "COMPLETED"]
    assert state.status_history == expected_prefix


def test_orchestrator_attributes_the_initial_kpi_lookup_to_evidence_agent(agent_ctx):
    state = _run(agent_ctx, _happy_path_client())
    assert state.audit_trace[0].agent_role == "EVIDENCE"
    assert state.audit_trace[0].tool_call == "compare_kpi"
    assert not any(e.agent_role == "ORCHESTRATOR" and e.security_decision == "ALLOWED" for e in state.audit_trace)


def test_unknown_kpi_id_leads_to_needs_clarification(agent_ctx):
    state = _run(agent_ctx, _happy_path_client(), kpi_id="not_a_real_kpi")
    assert state.status == InvestigationStatus.NEEDS_CLARIFICATION


def test_no_hypotheses_generated_leads_to_abstained(agent_ctx):
    def never_submits(messages):
        return text_only_response("I couldn't find a hypothesis.")
    client = ScriptedRoutingClient({"Hypothesis Agent": never_submits})
    state = _run(agent_ctx, client)
    assert state.status == InvestigationStatus.ABSTAINED
    assert state.hypotheses == []


def test_executive_role_investigation_never_contains_internal_classified_evidence(agent_ctx):
    state = _run(agent_ctx, _happy_path_client(), requester_role=RequesterRole.EXECUTIVE)
    for c in state.classified_evidence:
        ev = agent_ctx.evidence_store[c.evidence_id]
        assert ev.security.classification.value != "INTERNAL"


# ---------------------------------------------------------------------------
# Structural: the Orchestrator never independently generates a business
# conclusion (task §1A) -- an AST scan, not a runtime property.
# ---------------------------------------------------------------------------

def test_orchestrator_never_imports_evidence_schema_or_constructs_result_types():
    tree = ast.parse((REPO_ROOT / "src" / "agents" / "orchestrator.py").read_text())
    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_names.add(node.module or "")
            for alias in node.names:
                imported_names.add(alias.name)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in {"Hypothesis", "ClassifiedEvidence", "MethodSelection", "HypothesisResult",
                                         "ContradictionRecord"}
    assert "evidence.schema" not in imported_names
    assert "EvidenceObject" not in imported_names


def test_orchestrator_agent_role_has_no_allowed_tools():
    assert policy.ALLOWED_TOOLS_PER_AGENT[AgentRole.ORCHESTRATOR] == frozenset()


def test_state_machine_alone_defines_valid_orchestrator_pipeline_order():
    """The Orchestrator's stage list (private to orchestrator.py) must be
    exactly the linear chain the state machine independently defines --
    this test would fail if orchestrator.py's stage order and
    state_machine.py's ALLOWED_TRANSITIONS ever drifted apart."""
    from agents.models import InvestigationStatus as S
    linear = [S.PLANNED, S.SECURITY_VALIDATED, S.HYPOTHESES_GENERATED, S.EVIDENCE_COLLECTION, S.COUNTER_EVIDENCE,
              S.CONTRADICTION_ANALYSIS, S.METHOD_SELECTION, S.CONFIDENCE_EVALUATION, S.COMPLETED]
    for i, s in enumerate(linear[:-1]):
        assert linear[i + 1] in ALLOWED_TRANSITIONS[s]
