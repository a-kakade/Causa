"""
reranking.py — Step 4: top-K diversity reranking (task §24).

Two deterministic rerankers, no randomness anywhere:

- mmr_rerank: standard Maximal Marginal Relevance over already-scored
  candidates, used when a semantic query produced real similarity scores and
  embedding vectors.
- deterministic_metadata_diversity_rerank: a round-robin-by-metadata-key
  fallback used when there is no semantic query (no embeddings to compute
  pairwise similarity from), so a purely structured query still returns a
  diverse top-K instead of K near-duplicate rows (e.g. K reviews all from
  the same category, in the same order).

Relevance stays the primary objective in both -- diversity only breaks ties
among comparably-relevant candidates, per task §24 ("Preserve relevance as
the primary objective").
"""

from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

DEFAULT_MMR_LAMBDA = 0.7


def mmr_rerank(vectors: np.ndarray, scored_candidates: list[tuple[int, float]], k: int,
               lambda_param: float = DEFAULT_MMR_LAMBDA) -> list[tuple[int, float]]:
    """scored_candidates: [(position_in_vectors, relevance_score), ...],
    already sorted or unsorted -- this function re-derives the order itself.
    Returns up to k (position, relevance_score) pairs (the ORIGINAL relevance
    score is preserved in the output; the MMR score is only used to pick the
    order, not to overwrite `score` in the returned EvidenceResult)."""
    if not scored_candidates:
        return []
    if lambda_param >= 1.0:
        # Pure relevance order -- no diversity term, deterministic tie-break
        # on position so results are stable across runs.
        return sorted(scored_candidates, key=lambda pair: (-pair[1], pair[0]))[:k]

    pool = list(scored_candidates)
    selected: list[tuple[int, float]] = []
    selected_vecs: list[np.ndarray] = []

    while pool and len(selected) < k:
        best_idx, best_mmr = None, None
        for i, (pos, relevance) in enumerate(pool):
            if selected_vecs:
                sims = [float(np.dot(vectors[pos], sv)) for sv in selected_vecs]
                diversity_penalty = max(sims)
            else:
                diversity_penalty = 0.0
            mmr_score = lambda_param * relevance - (1 - lambda_param) * diversity_penalty
            # Deterministic tie-break: higher mmr_score wins; ties broken by
            # original candidate order (pool index), never randomly.
            if best_mmr is None or mmr_score > best_mmr or (mmr_score == best_mmr and i < best_idx):
                best_idx, best_mmr = i, mmr_score
        chosen = pool.pop(best_idx)
        selected.append(chosen)
        selected_vecs.append(vectors[chosen[0]])

    return selected


def deterministic_metadata_diversity_rerank(scored_candidates: list[tuple[int, float]],
                                             diversity_key: Callable[[int], object], k: int
                                             ) -> list[tuple[int, float]]:
    """Round-robins candidates across distinct values of `diversity_key(pos)`
    (e.g. category, or a review-score bucket), taking the highest-relevance
    remaining candidate from each group in turn, cycling through groups in a
    fixed (first-seen) order. Used when there's no embedding-based relevance
    signal to build a similarity-based diversity penalty from."""
    if not scored_candidates:
        return []
    ordered = sorted(scored_candidates, key=lambda pair: (-pair[1], pair[0]))
    groups: dict[object, list[tuple[int, float]]] = {}
    group_order: list[object] = []
    for pos, score in ordered:
        key = diversity_key(pos)
        if key not in groups:
            groups[key] = []
            group_order.append(key)
        groups[key].append((pos, score))

    result: list[tuple[int, float]] = []
    group_cursors = {key: 0 for key in group_order}
    while len(result) < k and any(group_cursors[key] < len(groups[key]) for key in group_order):
        for key in group_order:
            if len(result) >= k:
                break
            cursor = group_cursors[key]
            if cursor < len(groups[key]):
                result.append(groups[key][cursor])
                group_cursors[key] = cursor + 1
    return result
