"""Step 5: Confidence Judge tests (task §1F).

100% deterministic policy engine -- no LLM involved anywhere in this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents import confidence_judge  # noqa: E402
from agents.models import (  # noqa: E402
    AnalyticalMethod,
    ClassifiedEvidence,
    ConfidenceLevel,
    ContradictionRecord,
    ContradictionSeverity,
    EvidenceClassification,
    Hypothesis,
    InvestigationState,
    MethodSelection,
    RequesterRole,
)


class _Quality:
    def __init__(self, source_reliability=1.0, freshness=1.0, historical_sufficiency=1.0):
        self.source_reliability, self.freshness, self.historical_sufficiency = (
            source_reliability, freshness, historical_sufficiency)


class _Ev:
    def __init__(self, evidence_tier="T2_ARITHMETIC", **quality_kwargs):
        self.quality = _Quality(**quality_kwargs)
        self.evidence_tier = type("Tier", (), {"value": evidence_tier})()


def _hypothesis(hid="H1"):
    return Hypothesis(hypothesis_id=hid, statement="X may be associated with Y.", driver="volume", dimension="orders",
                       mechanism="m")


def _state_with(classified, severity=ContradictionSeverity.NONE, method=AnalyticalMethod.T2_ARITHMETIC,
                insufficiency_hit=False):
    state = InvestigationState(investigation_id="c1", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    state.hypotheses = [_hypothesis()]
    state.classified_evidence = classified
    state.contradictions = [ContradictionRecord(contradiction_id="CR-H1", hypothesis_id="H1", severity=severity)]
    state.selected_methods = [MethodSelection(hypothesis_id="H1", method=method, justification="j")]
    if insufficiency_hit:
        state.retrieval_insufficiency_events = [{"hypothesis_id": "H1"}]
    return state


def _classified(n, cls=EvidenceClassification.SUPPORTS, **quality_kwargs):
    return [ClassifiedEvidence(evidence_id=f"ev_{i}", hypothesis_id="H1", classification=cls,
                                rationale="r", source_evidence=_Ev(**quality_kwargs)) for i in range(n)]


def test_no_evidence_at_all_abstains():
    state = _state_with([])
    confidence_judge.evaluate(state)
    assert state.hypothesis_results[0].confidence == ConfidenceLevel.ABSTAIN
    assert state.confidence == ConfidenceLevel.ABSTAIN


def test_insufficient_data_method_always_abstains_regardless_of_evidence():
    state = _state_with(_classified(5), method=AnalyticalMethod.INSUFFICIENT_DATA)
    confidence_judge.evaluate(state)
    assert state.hypothesis_results[0].confidence == ConfidenceLevel.ABSTAIN


def test_strong_supporting_evidence_no_contradiction_reaches_high():
    state = _state_with(_classified(3, source_reliability=1.0, freshness=1.0, historical_sufficiency=1.0))
    confidence_judge.evaluate(state)
    assert state.hypothesis_results[0].confidence == ConfidenceLevel.HIGH


def test_strong_contradiction_caps_at_medium_even_with_perfect_support():
    state = _state_with(_classified(3, source_reliability=1.0, freshness=1.0, historical_sufficiency=1.0),
                         severity=ContradictionSeverity.STRONG)
    confidence_judge.evaluate(state)
    assert state.hypothesis_results[0].confidence in (ConfidenceLevel.MEDIUM, ConfidenceLevel.LOW, ConfidenceLevel.ABSTAIN)
    assert state.hypothesis_results[0].confidence != ConfidenceLevel.HIGH


def test_large_amount_of_weak_context_evidence_never_becomes_high_confidence():
    """task's own requirement, verbatim: 'A large amount of weak evidence
    must NOT automatically become high confidence.' One weak SUPPORTS item
    padded with 20 CONTEXT items must not out-score genuine completeness."""
    weak_support = _classified(1, cls=EvidenceClassification.SUPPORTS, source_reliability=0.3, freshness=0.3,
                                historical_sufficiency=0.3)
    padding = _classified(20, cls=EvidenceClassification.CONTEXT)
    state = _state_with(weak_support + padding)
    confidence_judge.evaluate(state)
    assert state.hypothesis_results[0].confidence != ConfidenceLevel.HIGH


def test_retrieval_insufficiency_with_thin_completeness_forces_needs_clarification():
    thin = _classified(1, cls=EvidenceClassification.SUPPORTS) + _classified(4, cls=EvidenceClassification.CONTEXT)
    state = _state_with(thin, insufficiency_hit=True)
    confidence_judge.evaluate(state)
    assert state.hypothesis_results[0].confidence == ConfidenceLevel.NEEDS_CLARIFICATION


def test_hypothesis_result_is_valid_for_every_produced_result():
    state = _state_with(_classified(3))
    confidence_judge.evaluate(state)
    for r in state.hypothesis_results:
        assert r.is_valid()


def test_supported_result_always_carries_at_least_one_evidence_id():
    state = _state_with(_classified(2))
    confidence_judge.evaluate(state)
    result = state.hypothesis_results[0]
    if result.status == "SUPPORTED":
        assert len(result.evidence_ids) >= 1


def test_investigation_level_confidence_is_the_worst_across_hypotheses():
    state = InvestigationState(investigation_id="c2", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    state.hypotheses = [_hypothesis("H1"), _hypothesis("H2")]
    state.classified_evidence = (
        [ClassifiedEvidence(evidence_id="ev_1", hypothesis_id="H1", classification=EvidenceClassification.SUPPORTS,
                             rationale="r", source_evidence=_Ev(source_reliability=1.0, freshness=1.0, historical_sufficiency=1.0))
         for _ in range(3)]
        # H2 gets no evidence at all -> ABSTAIN
    )
    state.contradictions = [
        ContradictionRecord(contradiction_id="CR-H1", hypothesis_id="H1", severity=ContradictionSeverity.NONE),
        ContradictionRecord(contradiction_id="CR-H2", hypothesis_id="H2", severity=ContradictionSeverity.NONE),
    ]
    state.selected_methods = [
        MethodSelection(hypothesis_id="H1", method=AnalyticalMethod.T2_ARITHMETIC, justification="j"),
        MethodSelection(hypothesis_id="H2", method=AnalyticalMethod.INSUFFICIENT_DATA, justification="j"),
    ]
    confidence_judge.evaluate(state)
    h1_result = next(r for r in state.hypothesis_results if r.hypothesis_id == "H1")
    h2_result = next(r for r in state.hypothesis_results if r.hypothesis_id == "H2")
    assert h1_result.confidence == ConfidenceLevel.HIGH
    assert h2_result.confidence == ConfidenceLevel.ABSTAIN
    assert state.confidence == ConfidenceLevel.ABSTAIN   # worst, not best, of the two


def test_causal_selector_never_selects_t3_or_t4():
    """causal_selector.py (task §1E): 'Never allow the LLM to declare
    causality' -- concretely, no code path in select_methods() can produce
    T3_QUASI_EXPERIMENTAL/T4_EXPERIMENTAL, regardless of how much SUPPORTS
    evidence a hypothesis has (the Olist dataset offers no natural
    experiment for this engine to justify either tier)."""
    from agents import causal_selector

    for n in (0, 1, 3, 10):
        state = _state_with(_classified(n))
        state.selected_methods = []
        causal_selector.select_methods(state)
        for m in state.selected_methods:
            assert m.method not in (AnalyticalMethod.T3_QUASI_EXPERIMENTAL, AnalyticalMethod.T4_EXPERIMENTAL)


def test_causal_selector_downgrades_on_strong_contradiction_never_upgrades():
    from agents import causal_selector

    state = _state_with(_classified(3), severity=ContradictionSeverity.STRONG)
    state.selected_methods = []
    causal_selector.select_methods(state)
    result = state.selected_methods[0]
    assert result.downgraded is True
    assert result.method != AnalyticalMethod.T2_ARITHMETIC   # was downgraded FROM T2_ARITHMETIC
    assert result.downgrade_reason is not None
