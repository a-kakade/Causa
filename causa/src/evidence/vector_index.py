"""
vector_index.py — Step 4: a lightweight local vector index (task §12).

Numpy brute-force cosine-similarity flat index -- not FAISS. The
text-bearing review corpus this prototype indexes (the Oct-Nov 2017
investigation window's reviews, or the full corpus for a production build)
is small enough (tens of thousands of rows, 384-dim vectors) that a single
matrix multiply is fast and exact, and it avoids adding a second heavy
dependency beyond sentence-transformers/torch. FAISS remains an acceptable
future upgrade (task §12 says "acceptable", not "required") if the corpus
grows enough that brute force stops being fast.

The index is NOT the source of truth (task §12) -- data/processed/
fact_reviews.parquet is. Everything here is rebuildable deterministically
from that table: `build()` never uses randomness, and identical input rows
in identical order always yield identical vectors/metadata.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np


@dataclass
class VectorIndexMetadata:
    """One entry per indexed review -- task §12's required mapping."""
    review_row_id: int
    review_id: str
    order_id: str
    month: Optional[str]
    category: Optional[str]
    seller: Optional[str]
    customer_state: Optional[str]
    seller_state: Optional[str]
    review_score: int
    language: str
    security_status: str


class FlatCosineIndex:
    def __init__(self, vectors: np.ndarray, metadata: list[VectorIndexMetadata]):
        assert vectors.shape[0] == len(metadata), "vector count must match metadata count"
        # Vectors from embeddings.py are already L2-normalized (normalize_embeddings=True),
        # but re-normalizing here makes cosine similarity correct even if a
        # caller ever hands this class un-normalized vectors.
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.vectors = (vectors / norms).astype(np.float32)
        self.metadata = metadata

    @classmethod
    def build(cls, vectors: np.ndarray, metadata: list[VectorIndexMetadata]) -> "FlatCosineIndex":
        return cls(vectors, metadata)

    def __len__(self) -> int:
        return len(self.metadata)

    def search(self, query_vector: np.ndarray, k: int, candidate_positions: Optional[list[int]] = None):
        """Returns [(position, score), ...] sorted by descending cosine
        similarity, restricted to `candidate_positions` if given (task §13:
        semantic search must run over a pre-filtered candidate subset, never
        the whole index)."""
        query_vector = query_vector.astype(np.float32)
        qnorm = np.linalg.norm(query_vector)
        if qnorm > 0:
            query_vector = query_vector / qnorm

        if candidate_positions is not None:
            if not candidate_positions:
                return []
            sub = self.vectors[candidate_positions]
            scores = sub @ query_vector
            order = np.argsort(-scores)[:k]
            return [(candidate_positions[i], float(scores[i])) for i in order]

        scores = self.vectors @ query_vector
        k = min(k, len(scores))
        top = np.argpartition(-scores, k - 1)[:k] if k > 0 else np.array([], dtype=int)
        top = top[np.argsort(-scores[top])]
        return [(int(i), float(scores[i])) for i in top]

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self.vectors)
        with open(directory / "metadata.jsonl", "w") as f:
            for m in self.metadata:
                f.write(json.dumps(asdict(m)) + "\n")

    @classmethod
    def load(cls, directory: Path) -> "FlatCosineIndex":
        vectors = np.load(directory / "vectors.npy")
        metadata = []
        with open(directory / "metadata.jsonl") as f:
            for line in f:
                metadata.append(VectorIndexMetadata(**json.loads(line)))
        return cls(vectors, metadata)
