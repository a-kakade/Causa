"""
hybrid_retriever.py — Step 4A: Reciprocal Rank Fusion (RRF) hybrid retriever.

Combines BM25Retriever + DenseRetriever outputs via RRF — a transparent,
parameter-free fusion method from Cormack et al. (2009) that works well
without tuned fusion weights.

RRF formula:
    score(d) = Σ_r 1 / (k_rrf + rank_r(d))

where k_rrf=60 is the standard smoothing constant.

A document scores high when it ranks high in MULTIPLE retriever lists,
regardless of absolute score magnitudes. This neutralizes the BM25 vs.
cosine scale incompatibility without needing learned weights.

Architecture:
    BM25Retriever → ranked list A
    DenseRetriever → ranked list B
    RRF fusion → combined ranked list
    → (optional) cross-encoder reranker
    → top-K

No LLM anywhere in this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from evidence.bm25_retriever import BM25Index, expand_query_tokens, tokenize
from evidence.dense_retriever import DenseRetriever


# ── RRF constants ──────────────────────────────────────────────────────────

RRF_K: int = 60  # Standard Cormack et al. (2009) smoothing constant


def reciprocal_rank_fusion(
    ranked_lists: list[list[tuple[int, float]]],
    k: int = RRF_K,
) -> list[tuple[int, float]]:
    """Fuse multiple ranked lists via RRF.

    ranked_lists: each element is [(doc_idx, score), ...] in descending
    score order. The scores are ignored — only rank position matters.

    Returns [(doc_idx, rrf_score), ...] descending by rrf_score.
    """
    rrf_scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank_zero, (doc_idx, _score) in enumerate(ranked):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0.0) + 1.0 / (k + rank_zero + 1)
    return sorted(rrf_scores.items(), key=lambda p: -p[1])


# ── BM25-only retriever wrapper ────────────────────────────────────────────

@dataclass
class LexicalRetriever:
    """Thin wrapper around BM25Index implementing the Retriever protocol."""
    bm25_index: BM25Index
    _method: str = "bm25"

    @property
    def method_name(self) -> str:
        return self._method

    def retrieve(
        self,
        query_text: str,
        k: int,
        candidate_positions: Optional[list[int]] = None,
        expand_query: bool = False,
    ) -> list[tuple[int, float]]:
        return self.bm25_index.query(
            query_text,
            k=k,
            candidate_positions=candidate_positions,
            expand=expand_query,
        )


# ── Hybrid retriever ───────────────────────────────────────────────────────

@dataclass
class HybridRetriever:
    """RRF fusion of a lexical retriever and a dense retriever.

    Both sub-retrievers independently rank candidates from the
    candidate_positions pool. Their ranked lists are fused via RRF,
    ensuring the ordering reflects consensus across retrieval signals.
    """
    lexical: LexicalRetriever
    dense: DenseRetriever
    rrf_k: int = RRF_K
    # How many candidates to request from each sub-retriever before fusion.
    # A pool_factor of 3 means top-3K per retriever for final top-K output.
    pool_factor: int = 3

    @property
    def method_name(self) -> str:
        return f"hybrid_rrf_{self.lexical.method_name}+{self.dense.method_name}"

    def retrieve(
        self,
        query_text: str,
        k: int,
        candidate_positions: Optional[list[int]] = None,
        expand_query: bool = False,
    ) -> list[tuple[int, float]]:
        """Retrieve top-k via RRF fusion."""
        pool_size = max(k * self.pool_factor, k + 20)

        bm25_results = self.lexical.retrieve(
            query_text, k=pool_size,
            candidate_positions=candidate_positions,
            expand_query=expand_query,
        )
        dense_results = self.dense.retrieve(
            query_text, k=pool_size,
            candidate_positions=candidate_positions,
        )

        fused = reciprocal_rank_fusion([bm25_results, dense_results], k=self.rrf_k)
        return fused[:k]

    def retrieve_with_components(
        self,
        query_text: str,
        k: int,
        candidate_positions: Optional[list[int]] = None,
        expand_query: bool = False,
    ) -> tuple[list[tuple[int, float]], dict]:
        """Like retrieve(), but also returns the per-component ranked lists
        for diagnostic inspection."""
        pool_size = max(k * self.pool_factor, k + 20)

        bm25_results = self.lexical.retrieve(
            query_text, k=pool_size,
            candidate_positions=candidate_positions,
            expand_query=expand_query,
        )
        dense_results = self.dense.retrieve(
            query_text, k=pool_size,
            candidate_positions=candidate_positions,
        )
        fused = reciprocal_rank_fusion([bm25_results, dense_results], k=self.rrf_k)

        return fused[:k], {
            "bm25_top_positions": [p for p, _ in bm25_results[:k]],
            "dense_top_positions": [p for p, _ in dense_results[:k]],
            "rrf_k": self.rrf_k,
        }
