"""Retrieval tests (Step 4 §13/§14/§15/§25).

Structured-first retrieval over the real October-November 2017 vector index
(built_vector_index fixture) -- verifies the mandatory pipeline order,
governed-dimension filter validation, clearance enforcement, and that
results always carry provenance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from evidence import retrieval  # noqa: E402
from evidence.retrieval import UnauthorizedFilterError, UnsupportedFilterError  # noqa: E402
from evidence.schema import EvidenceQuery  # noqa: E402


@pytest.fixture(scope="module")
def registry() -> SemanticRegistry:
    r = SemanticRegistry.load()
    r.validate()
    return r


@pytest.fixture(scope="module")
def review_row_id_index(review_corpus, review_evidence):
    """Maps review_row_id -> its CUSTOMER_REVIEW EvidenceObject. review_corpus
    and review_evidence are built from the same ordered list in conftest.py,
    so zipping them by position is exact."""
    return {row.review_row_id: ev for row, ev in zip(review_corpus, review_evidence)}


# ---------------------------------------------------------------------------
# validate_structured_filters (task §14)
# ---------------------------------------------------------------------------

def test_unsupported_filter_key_rejected(registry):
    with pytest.raises(UnsupportedFilterError):
        retrieval.validate_structured_filters({"not_a_real_key": "x"}, "PUBLIC_ANALYTICAL", registry)


def test_governed_dimension_filter_accepted_at_sufficient_clearance(registry):
    retrieval.validate_structured_filters({"month": "2017-11"}, "PUBLIC_ANALYTICAL", registry)
    retrieval.validate_structured_filters({"category": "bed_bath_table"}, "PUBLIC_ANALYTICAL", registry)


def test_seller_filter_requires_internal_clearance(registry):
    with pytest.raises(UnauthorizedFilterError):
        retrieval.validate_structured_filters({"seller": "abc123"}, "PUBLIC_ANALYTICAL", registry)
    retrieval.validate_structured_filters({"seller": "abc123"}, "INTERNAL", registry)   # should not raise


def test_review_pipeline_only_keys_are_allowed(registry):
    retrieval.validate_structured_filters(
        {"review_score_min": "1", "review_score_max": "2", "language": "PT"}, "PUBLIC_ANALYTICAL", registry)


# ---------------------------------------------------------------------------
# Structured-first pipeline (task §13)
# ---------------------------------------------------------------------------

def test_structured_filter_bounds_candidates_before_semantic_search(built_vector_index, registry, review_row_id_index):
    index, _text_rows, _cache = built_vector_index
    query = EvidenceQuery(
        investigation_id="test_inv", question="delivery complaints in November",
        structured_filters={"month": "2017-11", "review_score_max": "2"},
        semantic_query="atraso entrega",
    )
    results, telemetry = retrieval.retrieve(query, index, registry, review_row_id_index)
    assert telemetry.candidates_before_filter == len(index)
    assert telemetry.candidates_after_filter <= telemetry.candidates_before_filter
    assert telemetry.candidates_after_filter < telemetry.candidates_before_filter
    assert telemetry.vector_searches_performed == 1
    assert telemetry.llm_calls_made == 0


def test_never_semantic_searches_full_corpus_when_filters_narrow_it(built_vector_index, registry,
                                                                      review_row_id_index):
    index, _text_rows, _cache = built_vector_index
    narrow_query = EvidenceQuery(
        investigation_id="test_inv", question="narrow",
        structured_filters={"month": "2017-11", "review_score_max": "1"},
        semantic_query="produto",
    )
    _results, telemetry = retrieval.retrieve(narrow_query, index, registry, review_row_id_index)
    assert telemetry.candidates_after_filter < len(index)


def test_retrieval_never_returns_bare_strings(built_vector_index, registry, review_row_id_index):
    index, _text_rows, _cache = built_vector_index
    query = EvidenceQuery(investigation_id="test_inv", question="q", semantic_query="entrega atrasada", top_k=3)
    results, _telemetry = retrieval.retrieve(query, index, registry, review_row_id_index)
    assert results
    for r in results:
        assert r.source.review_id is not None
        assert r.retrieval.rank >= 1
        assert r.lineage


def test_retrieval_without_semantic_query_uses_deterministic_fallback(built_vector_index, registry,
                                                                        review_row_id_index):
    index, _text_rows, _cache = built_vector_index
    query = EvidenceQuery(investigation_id="test_inv", question="q",
                           structured_filters={"month": "2017-11"}, top_k=5)
    results, telemetry = retrieval.retrieve(query, index, registry, review_row_id_index)
    assert telemetry.vector_searches_performed == 0
    assert results


def test_pii_redaction_applied_to_content_not_underlying_evidence(built_vector_index, registry,
                                                                     review_row_id_index):
    index, _text_rows, _cache = built_vector_index
    # Find a piece of evidence with detected PII, if any exist in this window.
    pii_bearing = [ev for ev in review_row_id_index.values() if ev.security.pii_detected]
    if not pii_bearing:
        pytest.skip("no PII-bearing review in the Oct-Nov 2017 test window")
    ev = pii_bearing[0]
    original_text = ev.metadata["text"]
    query = EvidenceQuery(investigation_id="test_inv", question="q",
                           structured_filters={"month": ev.dimensions.get("month", "2017-11")}, top_k=50)
    results, _telemetry = retrieval.retrieve(query, index, registry, review_row_id_index)
    match = next((r for r in results if r.evidence_id == ev.evidence_id), None)
    if match is not None and match.security.pii_detected:
        assert match.content != original_text or "[REDACTED_" in match.content
        assert ev.metadata["text"] == original_text   # underlying evidence object untouched


# ---------------------------------------------------------------------------
# Retrieval evaluation reproducibility (task §23/§30.18)
# ---------------------------------------------------------------------------

def test_retrieval_evaluation_metric_functions_are_pure_and_deterministic():
    import step4_retrieval_eval as eval_script

    retrieved = ["ev_a", "ev_b", "ev_c", "ev_d", "ev_e"]
    expected = {"ev_c", "ev_z"}
    r1 = (eval_script.precision_at_k(retrieved, expected, 5), eval_script.mrr(retrieved, expected))
    r2 = (eval_script.precision_at_k(retrieved, expected, 5), eval_script.mrr(retrieved, expected))
    assert r1 == r2 == (0.2, pytest.approx(1 / 3))


def test_retrieval_evaluation_eval_set_loads_and_has_six_categories():
    import json
    eval_set_path = REPO_ROOT / "data" / "evidence" / "eval" / "retrieval_eval_set.json"
    with open(eval_set_path) as f:
        eval_set = json.load(f)
    categories = {c["category"] for c in eval_set["categories"]}
    assert categories == {
        "delivery_complaint", "product_quality_complaint", "low_satisfaction",
        "positive_experience", "shipping_delay", "category_specific_complaint",
    }


def test_retrieval_evaluation_query_is_reproducible_across_runs(built_vector_index, registry, review_row_id_index):
    index, _text_rows, _cache = built_vector_index
    query = EvidenceQuery(investigation_id="eval_test", question="q", semantic_query="atraso na entrega",
                           requester_clearance="INTERNAL", top_k=10)
    results1, _t1 = retrieval.retrieve(query, index, registry, review_row_id_index)
    results2, _t2 = retrieval.retrieve(query, index, registry, review_row_id_index)
    assert [r.evidence_id for r in results1] == [r.evidence_id for r in results2]
