"""
dense_retriever.py — Step 4A: dense retriever wrapping FlatCosineIndex.

DenseRetriever implements the Retriever protocol. The embedding model is
injected via an EmbeddingProvider at construction time — never hardcoded.
This allows swapping E5-small → E5-base → E5-large without touching callers.

The E5EmbeddingProvider is the concrete adapter for
intfloat/multilingual-e5-small|base|large. It reads its configuration
from config/embedding.yaml and applies the correct query:/passage: prefixes
as required by the E5 convention.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from evidence.vector_index import FlatCosineIndex


# ── E5 embedding provider ──────────────────────────────────────────────────

@dataclass
class E5EmbeddingProvider:
    """Concrete EmbeddingProvider backed by intfloat/multilingual-e5-*.

    Reads model/revision/dimension/prefix from config/embedding.yaml by
    default, but all fields are overridable at construction time so the
    same class can serve E5-small, E5-base, or E5-large.
    """
    model_name: str
    dimension: int
    query_prefix: str
    passage_prefix: str
    revision: Optional[str] = None
    _model: object = field(default=None, init=False, repr=False)

    @classmethod
    def from_config(cls) -> "E5EmbeddingProvider":
        """Build from config/embedding.yaml (the default production path)."""
        from evidence.embeddings import (
            EMBEDDING_DIM, EMBEDDING_MODEL, EMBEDDING_REVISION,
            QUERY_PREFIX, PASSAGE_PREFIX,
        )
        return cls(
            model_name=EMBEDDING_MODEL,
            dimension=EMBEDDING_DIM,
            query_prefix=QUERY_PREFIX,
            passage_prefix=PASSAGE_PREFIX,
            revision=EMBEDDING_REVISION,
        )

    @classmethod
    def from_model_name(cls, model_name: str, revision: Optional[str] = None) -> "E5EmbeddingProvider":
        """Build a new E5 provider for a different model size.
        Dimension is inferred from the model name convention.
        """
        if "large" in model_name:
            dim = 1024
        elif "base" in model_name:
            dim = 768
        else:
            dim = 384  # small
        return cls(
            model_name=model_name,
            dimension=dim,
            query_prefix="query: ",
            passage_prefix="passage: ",
            revision=revision,
        )

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(
                self.model_name,
                revision=self.revision,
                token=False,
            )
        return self._model

    def embed_query(self, text: str) -> np.ndarray:
        model = self._get_model()
        vec = model.encode([self.query_prefix + text], normalize_embeddings=True)[0]
        return vec.astype(np.float32)

    def embed_passage(self, text: str) -> np.ndarray:
        model = self._get_model()
        vec = model.encode([self.passage_prefix + text], normalize_embeddings=True)[0]
        return vec.astype(np.float32)

    def embed_passages_batch(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        model = self._get_model()
        prefixed = [self.passage_prefix + t for t in texts]
        vecs = model.encode(prefixed, normalize_embeddings=True, batch_size=batch_size)
        return np.asarray(vecs, dtype=np.float32)

    def latency_stats(self) -> dict:
        """Return basic model metadata (no timing — timing is per-call)."""
        return {"model_name": self.model_name, "dimension": self.dimension}


# ── Dense retriever ────────────────────────────────────────────────────────

@dataclass
class DenseRetriever:
    """Retriever backed by a FlatCosineIndex and an EmbeddingProvider.

    The embedding model is injected — the caller decides which E5 size
    to use; this class has no preference.
    """
    index: FlatCosineIndex
    provider: E5EmbeddingProvider

    @property
    def method_name(self) -> str:
        # e.g. "dense_intfloat/multilingual-e5-small"
        return f"dense_{self.provider.model_name}"

    def retrieve(
        self,
        query_text: str,
        k: int,
        candidate_positions: Optional[list[int]] = None,
        expand_query: bool = False,   # ignored for dense — no lexical expansion
    ) -> list[tuple[int, float]]:
        """Embed query, cosine-search the index (restricted to candidates),
        return [(position, cosine_score), ...] descending."""
        q_vec = self.provider.embed_query(query_text)
        pool = max(k * 5, k)
        return self.index.search(q_vec, k=pool, candidate_positions=candidate_positions)[:k]

    def retrieve_with_latency(
        self,
        query_text: str,
        k: int,
        candidate_positions: Optional[list[int]] = None,
    ) -> tuple[list[tuple[int, float]], float]:
        """Like retrieve(), but also returns embed+search latency in ms."""
        t0 = time.perf_counter()
        results = self.retrieve(query_text, k, candidate_positions=candidate_positions)
        latency_ms = (time.perf_counter() - t0) * 1000
        return results, round(latency_ms, 3)
