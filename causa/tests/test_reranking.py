"""Reranking tests (Step 4 §24). Pure numpy, no engine/canonical data needed."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evidence.reranking import deterministic_metadata_diversity_rerank, mmr_rerank  # noqa: E402


def _synthetic_vectors():
    # Two near-identical "cluster A" vectors (very similar), one distinct
    # "cluster B" vector with slightly lower raw relevance.
    rng = np.array([
        [1.0, 0.0, 0.0],   # 0: cluster A, highest relevance
        [0.99, 0.01, 0.0],  # 1: cluster A, near-duplicate of 0, 2nd highest relevance
        [0.0, 1.0, 0.0],   # 2: cluster B, distinct, 3rd highest relevance
    ])
    norms = np.linalg.norm(rng, axis=1, keepdims=True)
    return rng / norms


def test_mmr_increases_diversity_vs_pure_relevance_ordering():
    vectors = _synthetic_vectors()
    scored = [(0, 0.95), (1, 0.94), (2, 0.80)]
    pure_relevance_order = [pos for pos, _ in sorted(scored, key=lambda p: -p[1])]
    assert pure_relevance_order == [0, 1, 2]

    mmr_order = [pos for pos, _ in mmr_rerank(vectors, scored, k=2, lambda_param=0.5)]
    # Pure relevance would pick [0, 1] (both cluster A, near-duplicates).
    # MMR at lambda=0.5 should prefer diversity enough to pick cluster B's
    # item 2 over the near-duplicate item 1.
    assert mmr_order[0] == 0
    assert 2 in mmr_order


def test_mmr_lambda_one_equals_pure_relevance_order():
    vectors = _synthetic_vectors()
    scored = [(0, 0.7), (1, 0.95), (2, 0.80)]
    result = mmr_rerank(vectors, scored, k=3, lambda_param=1.0)
    assert [pos for pos, _ in result] == [1, 2, 0]


def test_mmr_returns_original_relevance_scores_not_mmr_scores():
    vectors = _synthetic_vectors()
    scored = [(0, 0.95), (1, 0.94), (2, 0.80)]
    result = mmr_rerank(vectors, scored, k=3, lambda_param=0.5)
    scores_by_pos = dict(result)
    assert scores_by_pos[0] == 0.95
    assert scores_by_pos[2] == 0.80


def test_mmr_is_deterministic_across_runs():
    vectors = _synthetic_vectors()
    scored = [(0, 0.95), (1, 0.94), (2, 0.80)]
    r1 = mmr_rerank(vectors, scored, k=2, lambda_param=0.5)
    r2 = mmr_rerank(vectors, scored, k=2, lambda_param=0.5)
    assert r1 == r2


def test_mmr_empty_candidates_returns_empty():
    vectors = _synthetic_vectors()
    assert mmr_rerank(vectors, [], k=5) == []


# ---------------------------------------------------------------------------
# Metadata-diversity fallback
# ---------------------------------------------------------------------------

def test_deterministic_metadata_diversity_round_robins_categories():
    # positions 0,1,2 are category "a"; 3,4 are category "b"
    categories = {0: "a", 1: "a", 2: "a", 3: "b", 4: "b"}
    scored = [(0, 0.9), (1, 0.85), (2, 0.8), (3, 0.7), (4, 0.6)]
    result = deterministic_metadata_diversity_rerank(scored, lambda pos: categories[pos], k=3)
    picked_categories = [categories[pos] for pos, _ in result]
    # Round-robin should surface category "b" before exhausting all of "a".
    assert picked_categories.count("b") >= 1
    assert result[0] == (0, 0.9)   # highest-relevance item still comes first


def test_deterministic_metadata_diversity_is_deterministic():
    categories = {0: "a", 1: "a", 2: "b"}
    scored = [(0, 0.9), (1, 0.85), (2, 0.8)]
    r1 = deterministic_metadata_diversity_rerank(scored, lambda pos: categories[pos], k=3)
    r2 = deterministic_metadata_diversity_rerank(scored, lambda pos: categories[pos], k=3)
    assert r1 == r2


def test_deterministic_metadata_diversity_respects_k():
    categories = {0: "a", 1: "b", 2: "c", 3: "d"}
    scored = [(0, 0.9), (1, 0.8), (2, 0.7), (3, 0.6)]
    result = deterministic_metadata_diversity_rerank(scored, lambda pos: categories[pos], k=2)
    assert len(result) == 2
