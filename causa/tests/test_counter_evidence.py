"""Step 5: Counter-Evidence Agent tests (task §1D).

collect_counter_evidence() is LLM-backed (adversarial search); severity
scoring / ContradictionRecord construction is covered separately and more
thoroughly in tests/test_contradictions.py -- this file focuses on the
agent's own collection/guardrail behavior.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

from _llm_test_helpers import extract_evidence_ids, last_tool_result_content, text_only_response, tool_call_response  # noqa: E402
from agents import counter_evidence_agent  # noqa: E402
from agents.llm_client import FakeLLMClient  # noqa: E402
from agents.models import (  # noqa: E402
    ClassifiedEvidence,
    ContradictionSeverity,
    EvidenceClassification,
    Hypothesis,
    InvestigationState,
    RequesterRole,
)


def _state_with_supported_hypothesis(agent_ctx) -> InvestigationState:
    state = InvestigationState(investigation_id="ce1", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    state.hypotheses = [Hypothesis(hypothesis_id="H1", statement="X may be associated with Y.", driver="volume",
                                    dimension="orders", mechanism="m")]
    # Give it a real evidence_id from the fixture's own store, so
    # downstream ClassifiedEvidence.source_evidence is a genuine object.
    real_id = next(iter(agent_ctx.evidence_store))
    state.classified_evidence = [
        ClassifiedEvidence(evidence_id=real_id, hypothesis_id="H1", classification=EvidenceClassification.SUPPORTS,
                            rationale="supports the hypothesis", source_evidence=agent_ctx.evidence_store[real_id]),
    ]
    return state


def test_hypothesis_with_no_supports_is_skipped_gets_a_none_severity_record(agent_ctx):
    state = InvestigationState(investigation_id="ce0", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    state.hypotheses = [Hypothesis(hypothesis_id="H1", statement="X may be associated with Y.", driver="volume",
                                    dimension="orders", mechanism="m")]
    fake = FakeLLMClient([])   # must never even be called
    counter_evidence_agent.collect_counter_evidence(state, fake, agent_ctx)
    assert state.counter_evidence_reports == []
    assert fake.calls == []


def test_submits_a_report_via_a_real_tool_call(agent_ctx):
    def script(messages):
        content = last_tool_result_content(messages)
        if content:
            ids = extract_evidence_ids(content)
            return tool_call_response("c2", "submit_counter_evidence_report", {
                "supporting_evidence": [], "contradicting_evidence": ids[:1],
                "unresolved_questions": ["Is the sample size sufficient in every affected segment?"],
                "contradiction_level": "WEAK",
            })
        return tool_call_response("c1", "get_driver_decomposition", dict(
            kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
            period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
            period_previous_label="2017-10", segment_dimensions=["customer_state"], top_n=5,
        ))

    state = _state_with_supported_hypothesis(agent_ctx)
    fake = FakeLLMClient(script)
    counter_evidence_agent.collect_counter_evidence(state, fake, agent_ctx)
    assert len(state.counter_evidence_reports) == 1
    report = state.counter_evidence_reports[0]
    assert report.hypothesis_id == "H1"
    assert len(report.contradicting_evidence) == 1
    assert report.contradicting_evidence[0] in agent_ctx.evidence_store


def test_hallucinated_ids_in_report_are_dropped(agent_ctx):
    def script(messages):
        return tool_call_response("c1", "submit_counter_evidence_report", {
            "supporting_evidence": ["ev_made_up_1"], "contradicting_evidence": ["ev_made_up_2"],
            "unresolved_questions": [], "contradiction_level": "NONE",
        })

    state = _state_with_supported_hypothesis(agent_ctx)
    fake = FakeLLMClient(script)
    counter_evidence_agent.collect_counter_evidence(state, fake, agent_ctx)
    report = state.counter_evidence_reports[0]
    assert report.supporting_evidence == [] and report.contradicting_evidence == []
    assert sum(1 for e in state.security_events if e["type"] == "hallucinated_evidence_id") == 2


def test_causal_language_in_unresolved_question_is_dropped(agent_ctx):
    def script(messages):
        return tool_call_response("c1", "submit_counter_evidence_report", {
            "supporting_evidence": [], "contradicting_evidence": [],
            "unresolved_questions": ["Delivery deterioration caused the review decline, is that resolved?",
                                      "Is the sample large enough?"],
            "contradiction_level": "NONE",
        })

    state = _state_with_supported_hypothesis(agent_ctx)
    fake = FakeLLMClient(script)
    counter_evidence_agent.collect_counter_evidence(state, fake, agent_ctx)
    report = state.counter_evidence_reports[0]
    assert all("caused" not in q for q in report.unresolved_questions)
    assert "Is the sample large enough?" in report.unresolved_questions
    assert any(e["type"] == "causal_language_rejected" for e in state.security_events)


def test_models_self_reported_contradiction_level_is_never_trusted_directly(agent_ctx):
    """The submitted contradiction_level is always overwritten with NONE as
    a placeholder here -- the REAL severity is computed later, deterministically,
    by build_contradiction_records (task §12: never resolved by (self-reported)
    vote)."""
    def script(messages):
        return tool_call_response("c1", "submit_counter_evidence_report", {
            "supporting_evidence": [], "contradicting_evidence": [], "unresolved_questions": [],
            "contradiction_level": "STRONG",   # model claims STRONG
        })

    state = _state_with_supported_hypothesis(agent_ctx)
    fake = FakeLLMClient(script)
    counter_evidence_agent.collect_counter_evidence(state, fake, agent_ctx)
    assert state.counter_evidence_reports[0].contradiction_level == ContradictionSeverity.NONE


def test_no_submit_call_still_produces_a_placeholder_report_never_crashes(agent_ctx):
    state = _state_with_supported_hypothesis(agent_ctx)
    fake = FakeLLMClient([text_only_response("I give up.")])
    counter_evidence_agent.collect_counter_evidence(state, fake, agent_ctx)
    assert len(state.counter_evidence_reports) == 1
    assert state.counter_evidence_reports[0].contradiction_level == ContradictionSeverity.NONE
