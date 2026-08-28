"""
retriever_interface.py — Step 4A: abstract retriever protocol.

Defines the EmbeddingProvider and Retriever protocols so the embedding
model is replaceable (BM25 → E5-small → E5-base → hybrid) without
touching callers.

Retriever architecture:

    EmbeddingProvider
        ↓
    DenseRetriever (wraps FlatCosineIndex + EmbeddingProvider)

    LexicalRetriever
        ↓
    BM25Retriever (wraps BM25Index)

    HybridRetriever
        ↓  (RRF fusion of DenseRetriever + BM25Retriever)
    Reranker (optional cross-encoder, no-op if model unavailable)
        ↓
    RETRIEVAL_INSUFFICIENT sentinel (if confidence too low)
        ↓
    Evidence objects

The EmbeddingProvider is injected into DenseRetriever at construction
time — never hardcoded.

RETRIEVAL_INSUFFICIENT:
    When retrieval confidence is low (no candidates, or best score below
    a configured floor), the system returns a structured sentinel rather
    than filling top-K with arbitrary low-confidence reviews.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol, runtime_checkable


# ── Retrieval result sentinel ──────────────────────────────────────────────

@dataclass(frozen=True)
class RetrievalInsufficient:
    """Returned instead of results when confidence is too low to commit
    to a ranked list.  Downstream callers (future Confidence Judge) use
    this to decide whether to abstain, broaden the query, or escalate.
    """
    candidate_count: int
    best_score: float
    retrieval_method: str          # "bm25" | "dense_e5" | "hybrid_rrf" | ...
    coverage: float                # candidates_after_filter / candidates_before_filter
    reason: str                    # human-readable explanation

    # Sentinel tag — never confused with a list of EvidenceResult
    SENTINEL: str = field(default="RETRIEVAL_INSUFFICIENT", init=False, compare=False)


# Minimum score thresholds — tuned empirically from Step 4A benchmarks.
# Dense: cosine similarity (0-1). BM25: unnormalized BM25+ score.
# These are NOT used to filter individual results but to decide
# whether the BEST result is good enough to return anything at all.
MIN_DENSE_SCORE_FLOOR: float = 0.82   # below ~0.82 E5-small loses discrimination
MIN_BM25_SCORE_FLOOR: float = 0.5     # BM25+ — at least one term match required
MIN_HYBRID_SCORE_FLOOR: float = 0.05  # RRF scores are small by construction


# ── Protocols ──────────────────────────────────────────────────────────────

@runtime_checkable
class EmbeddingProvider(Protocol):
    """Anything that can embed a query string into a float32 vector.

    The dimension is encoded in the provider's implementation, not here.
    DenseRetriever calls this once per query — never once per document.
    """
    model_name: str
    dimension: int

    def embed_query(self, text: str) -> "np.ndarray":  # noqa: F821
        ...

    def embed_passage(self, text: str) -> "np.ndarray":  # noqa: F821
        ...


@runtime_checkable
class Retriever(Protocol):
    """Common protocol for all retriever implementations."""

    @property
    def method_name(self) -> str:
        """Short tag identifying the retrieval method, e.g. 'bm25', 'dense_e5_small'."""
        ...

    def retrieve(
        self,
        query_text: str,
        k: int,
        candidate_positions: Optional[list[int]] = None,
        expand_query: bool = False,
    ) -> list[tuple[int, float]]:
        """Return [(doc_position, score), ...] descending by score.

        candidate_positions: pre-filtered subset of the corpus (structured-
        first contract).  None means search the whole corpus.
        expand_query: enable bilingual query expansion (BM25 only).
        """
        ...
