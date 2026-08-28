"""Step 5: Hypothesis Agent tests (task §1B/§10).

Uses agents.llm_client.FakeLLMClient throughout -- no network, fully
deterministic -- except where noted. The real evidence-gathering tools
(get_driver_decomposition etc.) ARE exercised for real via agent_ctx; only
the model's own text is scripted.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from _llm_test_helpers import tool_call_response, text_only_response  # noqa: E402
from agents import hypothesis_agent  # noqa: E402
from agents.llm_client import FakeLLMClient  # noqa: E402
from agents.models import InvestigationState, RequesterRole  # noqa: E402


def _fresh_state() -> InvestigationState:
    state = InvestigationState(investigation_id="h1", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    state.movement = {"absolute": 346051.94, "percentage": 52.1}
    return state


def _submit(hyps: list, call_id="c1"):
    return tool_call_response(call_id, "submit_hypotheses", {"hypotheses": hyps})


_H_VOLUME = {"driver": "volume", "dimension": "orders", "mechanism": "order-count expansion",
             "statement": "Revenue growth may be associated with an increase in order volume.",
             "expected_evidence": ["DRIVER_CONTRIBUTION:volume"], "falsification_evidence": []}
_H_DELIVERY = {"driver": "delivery", "dimension": "avg_review_score", "mechanism": "service-quality feedback",
               "statement": "Delivery deterioration may be associated with declining review scores.",
               "expected_evidence": ["CONCURRENT_KPI:avg_delivery_days"], "falsification_evidence": []}


def test_generates_hypotheses_from_an_immediate_submit(agent_ctx):
    state = _fresh_state()
    fake = FakeLLMClient([_submit([_H_VOLUME, _H_DELIVERY])])
    hypothesis_agent.generate_hypotheses(state, fake, agent_ctx)
    assert len(state.hypotheses) == 2
    ids = {h.hypothesis_id for h in state.hypotheses}
    assert ids == {"H1", "H2"}


def test_caps_at_five_hypotheses(agent_ctx):
    six = [dict(_H_VOLUME, driver=f"driver{i}", dimension=f"dim{i}") for i in range(6)]
    state = _fresh_state()
    fake = FakeLLMClient([_submit(six)])
    hypothesis_agent.generate_hypotheses(state, fake, agent_ctx)
    assert len(state.hypotheses) <= hypothesis_agent.MAX_HYPOTHESES


def test_duplicate_driver_dimension_pair_is_deduplicated(agent_ctx):
    duplicate = dict(_H_VOLUME, statement="Revenue growth may also be associated with order volume, restated.")
    state = _fresh_state()
    fake = FakeLLMClient([_submit([_H_VOLUME, duplicate, _H_DELIVERY])])
    hypothesis_agent.generate_hypotheses(state, fake, agent_ctx)
    pairs = {(h.driver, h.dimension) for h in state.hypotheses}
    assert len(pairs) == len(state.hypotheses)   # no duplicate (driver, dimension) survived
    assert any(e["type"] == "hypothesis_diversity_violation" for e in state.security_events)


def test_causal_language_in_statement_is_rejected_not_silently_rewritten(agent_ctx):
    causal = dict(_H_VOLUME, statement="Order volume growth caused the revenue increase.")
    state = _fresh_state()
    fake = FakeLLMClient([_submit([causal, _H_DELIVERY])])
    hypothesis_agent.generate_hypotheses(state, fake, agent_ctx)
    assert all("caused" not in h.statement for h in state.hypotheses)
    assert len(state.hypotheses) == 1   # the causal one was DROPPED, not rewritten
    assert any(e["type"] == "causal_language_rejected" for e in state.security_events)


def test_fabricated_number_in_statement_is_rejected(agent_ctx):
    fabricated = dict(_H_VOLUME, statement="Revenue grew by a wildly fabricated R$9,999,999.99 due to volume.")
    # (the sentence above ALSO contains "due to", separately caught by the causal guard --
    # constructed this way deliberately to prove numeric validation runs independently)
    numeric_only = dict(_H_VOLUME,
                         statement="Revenue growth of R$9,999,999.99 is associated with order volume expansion.")
    state = _fresh_state()
    fake = FakeLLMClient([_submit([numeric_only, _H_DELIVERY])])
    hypothesis_agent.generate_hypotheses(state, fake, agent_ctx)
    assert len(state.hypotheses) == 1
    assert any(e["type"] == "NUMERIC_VALIDATION_FAILED" for e in state.security_events)


def test_no_submit_call_leaves_hypotheses_empty_never_crashes(agent_ctx):
    state = _fresh_state()
    fake = FakeLLMClient([text_only_response("I couldn't decide on any hypotheses.")])
    hypothesis_agent.generate_hypotheses(state, fake, agent_ctx)
    assert state.hypotheses == []


def test_every_generated_hypothesis_has_driver_dimension_expected_and_falsification_evidence(agent_ctx):
    state = _fresh_state()
    fake = FakeLLMClient([_submit([_H_VOLUME, _H_DELIVERY])])
    hypothesis_agent.generate_hypotheses(state, fake, agent_ctx)
    for h in state.hypotheses:
        assert h.driver and h.dimension and h.mechanism and h.statement
        assert isinstance(h.expected_evidence, list) and isinstance(h.falsification_evidence, list)
