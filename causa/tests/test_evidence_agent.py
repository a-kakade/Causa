"""Step 5: Evidence Agent tests (task §1C/§11).

Exercises the REAL governed tools (get_driver_decomposition etc., via
agent_ctx) with a scripted model that requests one real tool call, reads the
real evidence_id(s) that came back, and classifies them -- proving the full
tool-call -> classification -> guardrail pipeline, not just the guardrails
in isolation.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from _llm_test_helpers import extract_evidence_ids, last_tool_result_content, tool_call_response  # noqa: E402
from agents import evidence_agent  # noqa: E402
from agents.llm_client import FakeLLMClient  # noqa: E402
from agents.models import ClassifiedEvidence, EvidenceClassification, Hypothesis, InvestigationState, RequesterRole  # noqa: E402


def _fresh_state_with_hypothesis(hid="H1", driver="volume", dimension="orders") -> InvestigationState:
    state = InvestigationState(investigation_id="e1", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    state.hypotheses = [Hypothesis(hypothesis_id=hid, statement="X may be associated with Y.", driver=driver,
                                    dimension=dimension, mechanism="m", expected_evidence=["DRIVER_CONTRIBUTION:volume"])]
    return state


_DRIVER_ARGS = dict(kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
                     period_current_label="2017-11", period_previous_start="2017-10-01",
                     period_previous_end="2017-10-31", period_previous_label="2017-10",
                     segment_dimensions=["product_category"], top_n=5)


def _real_tool_then_classify_script(messages):
    content = last_tool_result_content(messages)
    if content:
        ids = extract_evidence_ids(content)
        classifications = [{"evidence_id": i, "classification": "SUPPORTS", "rationale": "consistent direction"}
                            for i in ids[:2]]
        return tool_call_response("c2", "submit_evidence_classification", {"classifications": classifications})
    return tool_call_response("c1", "get_driver_decomposition", _DRIVER_ARGS)


def test_classifies_real_evidence_from_a_real_tool_call(agent_ctx):
    state = _fresh_state_with_hypothesis()
    fake = FakeLLMClient(_real_tool_then_classify_script)
    evidence_agent.collect_evidence(state, fake, agent_ctx)
    assert len(state.classified_evidence) >= 1
    for c in state.classified_evidence:
        assert c.evidence_id in agent_ctx.evidence_store   # every citation is REAL, never invented
        assert c.hypothesis_id == "H1"


def test_hallucinated_evidence_id_is_dropped_not_invented(agent_ctx):
    def script(messages):
        content = last_tool_result_content(messages)
        if content:
            classifications = [{"evidence_id": "ev_totally_made_up_id_12345", "classification": "SUPPORTS",
                                 "rationale": "invented"}]
            return tool_call_response("c2", "submit_evidence_classification", {"classifications": classifications})
        return tool_call_response("c1", "get_driver_decomposition", _DRIVER_ARGS)

    state = _fresh_state_with_hypothesis()
    fake = FakeLLMClient(script)
    evidence_agent.collect_evidence(state, fake, agent_ctx)
    assert not any(c.evidence_id == "ev_totally_made_up_id_12345" for c in state.classified_evidence)
    assert any(e["type"] == "hallucinated_evidence_id" for e in state.security_events)


def test_concurrent_kpi_evidence_is_always_forced_to_context(agent_ctx):
    def script(messages):
        content = last_tool_result_content(messages)
        if content:
            ids = extract_evidence_ids(content)
            classifications = [{"evidence_id": i, "classification": "SUPPORTS",   # model WRONGLY says SUPPORTS
                                 "rationale": "model incorrectly treats concurrent KPI as direct support"}
                                for i in ids]
            return tool_call_response("c2", "submit_evidence_classification", {"classifications": classifications})
        return tool_call_response("c1", "get_concurrent_kpis", dict(
            kpi_ids=["avg_delivery_days"], period_current_start="2017-11-01", period_current_end="2017-11-30",
            period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
            period_previous_label="2017-10",
        ))

    state = _fresh_state_with_hypothesis(driver="delivery", dimension="avg_review_score")
    fake = FakeLLMClient(script)
    evidence_agent.collect_evidence(state, fake, agent_ctx)
    for c in state.classified_evidence:
        ev = agent_ctx.evidence_store[c.evidence_id]
        if ev.evidence_type.value == "CONCURRENT_KPI":
            assert c.classification == EvidenceClassification.CONTEXT   # floor overrides the model


def test_low_confidence_evidence_forced_insufficient_regardless_of_model_opinion(agent_ctx):
    from agents.evidence_agent import _apply_floor
    ev_dict = {"evidence_type": "SEGMENT_CONTRIBUTION", "confidence": "LOW", "security": {"security_status": "SAFE"},
               "metadata": {}}
    final, reason = _apply_floor(ev_dict, "SUPPORTS")
    assert final == "INSUFFICIENT" and "confidence" in reason


def test_small_sample_size_forced_insufficient_regardless_of_model_opinion(agent_ctx):
    from agents.evidence_agent import _apply_floor
    ev_dict = {"evidence_type": "SEGMENT_CONTRIBUTION", "confidence": "HIGH", "security": {"security_status": "SAFE"},
               "metadata": {"sample_size": 3}}
    final, reason = _apply_floor(ev_dict, "SUPPORTS")
    assert final == "INSUFFICIENT" and "sample_size" in reason


def test_no_submit_call_leaves_no_classified_evidence_never_crashes(agent_ctx):
    from _llm_test_helpers import text_only_response
    state = _fresh_state_with_hypothesis()
    fake = FakeLLMClient([text_only_response("giving up")])
    evidence_agent.collect_evidence(state, fake, agent_ctx)
    assert state.classified_evidence == []


def test_original_evidence_object_is_never_rewritten(agent_ctx):
    """task §11: classification must preserve the original evidence object."""
    state = _fresh_state_with_hypothesis()
    fake = FakeLLMClient(_real_tool_then_classify_script)
    evidence_agent.collect_evidence(state, fake, agent_ctx)
    for c in state.classified_evidence:
        stored = agent_ctx.evidence_store[c.evidence_id]
        assert c.source_evidence is stored   # identity, not a copy or rewrite
