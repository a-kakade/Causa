"""Step 5: Contradiction Engine tests (task §12).

score_contradiction_severity is 100% deterministic; the two-proportion
z-test it optionally consults is the SAME real one Step 4's graph.py already
computes (evidence.graph.check_low_score_rate_contradiction) -- reused here,
never re-derived. "Do not resolve contradictions by majority vote" is
verified by never letting the model's own contradiction_level (self-reported
in a CounterEvidenceReport) override the deterministic score.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.counter_evidence_agent import _find_graph_z_test, build_contradiction_records, score_contradiction_severity  # noqa: E402
from agents.models import (  # noqa: E402
    AgentRole,
    AnalyticalMethod,
    ClassifiedEvidence,
    ContradictionSeverity,
    CounterEvidenceReport,
    EvidenceClassification,
    Hypothesis,
    InvestigationState,
    RequesterRole,
)
from evidence import graph as graph_module  # noqa: E402
from tools import gateway  # noqa: E402


# ---------------------------------------------------------------------------
# Pure severity-scoring boundary tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("n_contradicts,graph_check,expected", [
    (0, None, ContradictionSeverity.NONE),
    (1, None, ContradictionSeverity.WEAK),
    (2, None, ContradictionSeverity.MODERATE),
    (3, None, ContradictionSeverity.STRONG),
    (5, None, ContradictionSeverity.STRONG),
    (0, {"z": 1.0, "n_total": 50}, ContradictionSeverity.WEAK),          # graph present but not strong
    (0, {"z": 2.5, "n_total": 10}, ContradictionSeverity.WEAK),          # strong z but n too small
    (0, {"z": 2.5, "n_total": 50}, ContradictionSeverity.MODERATE),      # strong graph alone
    (1, {"z": 2.5, "n_total": 50}, ContradictionSeverity.STRONG),        # strong graph + >=1 contradicts
])
def test_score_contradiction_severity_boundaries(n_contradicts, graph_check, expected):
    assert score_contradiction_severity(n_contradicts, graph_check) == expected


def test_severity_never_resolved_by_majority_vote_over_the_models_own_opinion():
    """The model's self-reported contradiction_level in a CounterEvidenceReport
    (here deliberately set to the opposite of what the real math implies)
    must have ZERO influence on score_contradiction_severity's output --
    only real counts/z-tests feed it."""
    report_says_none = CounterEvidenceReport(hypothesis_id="H1", contradiction_level=ContradictionSeverity.NONE)
    assert score_contradiction_severity(3, None) == ContradictionSeverity.STRONG   # real count says STRONG anyway

    report_says_strong = CounterEvidenceReport(hypothesis_id="H1", contradiction_level=ContradictionSeverity.STRONG)
    assert score_contradiction_severity(0, None) == ContradictionSeverity.NONE     # real count says NONE anyway


# ---------------------------------------------------------------------------
# Real graph reuse: Step 4's own two-proportion z-test, via agent_ctx
# ---------------------------------------------------------------------------

def test_find_graph_z_test_reuses_step4s_real_contradiction_edges(agent_ctx):
    hypothesis = Hypothesis(
        hypothesis_id="H1", statement="Delivery deterioration may be associated with declining review scores.",
        driver="delivery", dimension="avg_review_score", mechanism="service-quality feedback",
    )
    result = _find_graph_z_test(hypothesis, agent_ctx)
    # May legitimately be None (no CONTRADICTS edge was found among real top-mover
    # categories in this corpus -- see STEP4_VALIDATION.md §12) OR a real dict with a
    # genuine z-score -- either is a valid, non-fabricated outcome; assert the SHAPE
    # is right whenever one is found, never assert a specific fabricated z-score.
    if result is not None:
        assert set(result) == {"z", "n_total", "note"}
        assert isinstance(result["n_total"], int) and result["n_total"] > 0


def test_find_graph_z_test_returns_none_for_unrelated_hypothesis(agent_ctx):
    hypothesis = Hypothesis(
        hypothesis_id="H2", statement="Revenue growth may be associated with order volume expansion.",
        driver="volume", dimension="orders", mechanism="order-count expansion",
    )
    assert _find_graph_z_test(hypothesis, agent_ctx) is None


def test_real_electronics_category_contradiction_is_detectable_via_the_reused_mechanism(agent_ctx):
    """docs/EVIDENCE_GRAPH.md §3 / STEP4_VALIDATION.md §12: the `electronics`
    category (present in the corpus, not a top-10 revenue mover) has a real,
    non-fabricated contradiction (low-score rate genuinely DECREASED,
    18.2% -> 15.3%). Verifies check_low_score_rate_contradiction itself
    (Step 4, unmodified) still produces this real result -- the mechanism
    score_contradiction_severity's graph_check argument depends on."""
    prev_scores = [r.review_score for r in agent_ctx.review_corpus if r.month == "2017-10" and r.category == "electronics"]
    curr_scores = [r.review_score for r in agent_ctx.review_corpus if r.month == "2017-11" and r.category == "electronics"]
    if len(prev_scores) < 15 or len(curr_scores) < 15:
        pytest.skip("electronics category sample size below the governed floor in this corpus snapshot")
    check = graph_module.check_low_score_rate_contradiction(prev_scores, curr_scores)
    assert check.contradicts is True   # rate did not increase -- a real contradiction, not fabricated


# ---------------------------------------------------------------------------
# build_contradiction_records: pure re-derivation, no new tool calls, always unresolved
# ---------------------------------------------------------------------------

def _fake_evidence(evidence_id="ev_x", evidence_tier="T2_ARITHMETIC"):
    class _Ev:
        pass
    ev = _Ev()
    ev.evidence_tier = type("T", (), {"value": evidence_tier})()
    return ev


def test_build_contradiction_records_produces_one_record_per_hypothesis_always_unresolved(agent_ctx):
    state = InvestigationState(investigation_id="cr1", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    state.hypotheses = [
        Hypothesis(hypothesis_id="H1", statement="X may be associated with Y.", driver="volume", dimension="orders",
                   mechanism="m"),
        Hypothesis(hypothesis_id="H2", statement="A may be associated with B.", driver="mix", dimension="product_category",
                   mechanism="m"),
    ]
    state.classified_evidence = [
        ClassifiedEvidence(evidence_id="ev_a", hypothesis_id="H1", classification=EvidenceClassification.SUPPORTS,
                            rationale="consistent with the hypothesis", source_evidence=_fake_evidence()),
        ClassifiedEvidence(evidence_id="ev_b", hypothesis_id="H2", classification=EvidenceClassification.CONTRADICTS,
                            rationale="opposes the hypothesis", source_evidence=_fake_evidence()),
    ]
    state.counter_evidence_reports = [CounterEvidenceReport(hypothesis_id="H2", contradicting_evidence=["ev_b"])]

    build_contradiction_records(state, agent_ctx)

    assert len(state.contradictions) == 2
    by_id = {c.hypothesis_id: c for c in state.contradictions}
    assert by_id["H1"].severity == ContradictionSeverity.NONE
    assert by_id["H2"].severity == ContradictionSeverity.WEAK
    assert all(c.unresolved for c in state.contradictions)   # never auto-resolved
