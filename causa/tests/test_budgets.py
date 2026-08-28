"""Step 5: Investigation Budget tests (task §9)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.llm_client import FakeLLMClient, LLMResponse  # noqa: E402
from agents.models import Budgets, BudgetExceeded, InvestigationState, InvestigationStatus, RequesterRole  # noqa: E402
from agents import orchestrator  # noqa: E402
from tools import gateway  # noqa: E402


def test_budgets_default_and_increment():
    b = Budgets()
    b.increment("tool_calls")
    assert b.used_tool_calls == 1
    assert not b.exhausted()


def test_check_raises_when_at_limit():
    b = Budgets(max_tool_calls=2)
    b.increment("tool_calls")
    b.increment("tool_calls")
    with pytest.raises(BudgetExceeded) as exc_info:
        b.increment("tool_calls")
    assert exc_info.value.budget_name == "tool_calls"
    assert exc_info.value.limit == 2


def test_every_budget_dimension_enforced_independently():
    for name in ("iterations", "agent_calls", "tool_calls", "retrieval_calls", "tokens", "latency_seconds"):
        b = Budgets(**{f"max_{name}": 1})
        b.increment(name)
        with pytest.raises(BudgetExceeded):
            b.increment(name)


def test_exhausted_reflects_any_single_dimension():
    b = Budgets(max_agent_calls=1)
    assert not b.exhausted()
    b.increment("agent_calls")
    assert b.exhausted()


def test_budget_exceeded_message_names_the_dimension_and_limit():
    exc = BudgetExceeded("tool_calls", 5, 6)
    assert "tool_calls" in str(exc) and "5" in str(exc)


# ---------------------------------------------------------------------------
# A tiny budget must terminate BUDGET_EXCEEDED, never hang or crash (task §9:
# "Never continue indefinitely.")
# ---------------------------------------------------------------------------

def test_investigation_with_exhausted_tool_call_budget_terminates_budget_exceeded(agent_ctx):
    state = InvestigationState(
        investigation_id="budget_test", requester_role=RequesterRole.ANALYST, kpi_id="revenue", period="2017-11",
        budgets=Budgets(max_tool_calls=0),
    )
    from agents.state_machine import transition
    transition(state, InvestigationStatus.SECURITY_VALIDATED)
    try:
        state.budgets.increment("iterations")
        result = gateway.call_tool(state, __import__("agents.models", fromlist=["AgentRole"]).AgentRole.EVIDENCE,
                                    "compare_kpi", dict(kpi_id="revenue", current_start="2017-11-01",
                                                         current_end="2017-11-30", previous_start="2017-10-01",
                                                         previous_end="2017-10-31"), agent_ctx)
        assert not result.ok
    except BudgetExceeded:
        pass


def test_orchestrator_with_tiny_agent_call_budget_terminates_gracefully(agent_ctx):
    """A budget so small the Hypothesis Agent cannot even make its first LLM
    call must still leave the investigation in a well-formed terminal state
    -- never an unhandled exception."""
    fake = FakeLLMClient([])   # any call at all raises RuntimeError (script exhausted) if reached
    state = orchestrator.run_investigation(
        investigation_id="tiny_budget", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
        period_current_start="2017-11-01", period_current_end="2017-11-30", period_current_label="2017-11",
        period_previous_start="2017-10-01", period_previous_end="2017-10-31", period_previous_label="2017-10",
        ctx=agent_ctx, llm_client=fake, budgets=Budgets(max_agent_calls=0),
    )
    assert state.status == InvestigationStatus.BUDGET_EXCEEDED
    assert state.status_history[-1].startswith("BUDGET_EXCEEDED")
