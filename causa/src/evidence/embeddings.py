"""
embeddings.py — Step 4: the multilingual embedding model wrapper (task §11).

Model: intfloat/multilingual-e5-small (config/embedding.yaml pins the exact
Hugging Face revision). 384-dim embeddings. E5 convention: queries are
embedded with a "query: " prefix, passages (review text) with "passage: ".
1 review = 1 retrieval document -- no chunking (task §11).

This environment's cached Hugging Face auth token happens to be expired,
which makes AUTHENTICATED Hub calls fail with 401 even for this fully public
model. Anonymous access works fine, so every Hub call in this module passes
token=False rather than relying on ambient HF_TOKEN state.

`SentenceTransformer` (and therefore torch) is imported lazily inside
get_model(), not at module load time, so importing evidence.embeddings
doesn't force a multi-hundred-MB model load for code paths (e.g. schema
tests) that never embed anything.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Optional

import numpy as np
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_CONFIG_PATH = REPO_ROOT / "config" / "embedding.yaml"

with open(_CONFIG_PATH) as _f:
    _CONFIG = yaml.safe_load(_f)

EMBEDDING_MODEL: str = _CONFIG["model"]
EMBEDDING_REVISION: str = _CONFIG["revision"]
EMBEDDING_VERSION: str = _CONFIG["embedding_version"]
EMBEDDING_DIM: int = _CONFIG["dimension"]
QUERY_PREFIX: str = _CONFIG["query_prefix"]
PASSAGE_PREFIX: str = _CONFIG["passage_prefix"]
CACHE_PATH: Path = REPO_ROOT / _CONFIG["cache_path"]

_model = None  # module-level lazy singleton


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(EMBEDDING_MODEL, revision=EMBEDDING_REVISION, token=False)
    return _model


def cache_key(normalized_text: str) -> str:
    payload = f"{normalized_text}|{EMBEDDING_MODEL}|{EMBEDDING_VERSION}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class EmbeddingCache:
    """Disk cache backed by one .npz file (not one file per review -- 40K+
    tiny files would be unwieldy). Neither this cache nor the vector index
    built from it is the source of truth (task §12) -- both are rebuildable
    from data/processed/fact_reviews.parquet at any time."""

    def __init__(self, path: Path = CACHE_PATH):
        self.path = path
        self._keys: dict[str, int] = {}
        self._vectors: Optional[np.ndarray] = None
        self.hits = 0
        self.misses = 0
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            data = np.load(self.path, allow_pickle=False)
            keys = data["keys"]
            self._vectors = data["vectors"].astype(np.float32)
            self._keys = {k: i for i, k in enumerate(keys)}

    def get(self, key: str) -> Optional[np.ndarray]:
        idx = self._keys.get(key)
        if idx is None:
            self.misses += 1
            return None
        self.hits += 1
        return self._vectors[idx]

    def put_many(self, new_keys: list[str], new_vectors: np.ndarray) -> None:
        if not new_keys:
            return
        # The append offset MUST be the current row count of self._vectors,
        # not len(self._keys). new_keys can contain internal duplicates
        # (very common here -- many Olist reviews share identical short
        # text), which makes the unique-key dict grow slower than the
        # vector array. Using len(self._keys) as the offset silently
        # misaligns every key added in a later put_many() call by the
        # accumulated duplicate count, so cache.get(key) returns some
        # other row's real (but wrong) embedding instead of key's own --
        # a bug that stays invisible (cosine scores still look plausible)
        # while corrupting retrieval quality.
        start = 0 if self._vectors is None else self._vectors.shape[0]
        if self._vectors is None:
            self._vectors = new_vectors.astype(np.float32)
        else:
            self._vectors = np.vstack([self._vectors, new_vectors.astype(np.float32)])
        for i, k in enumerate(new_keys):
            self._keys[k] = start + i

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys_arr = np.array(sorted(self._keys, key=self._keys.get))
        if self._vectors is None or len(keys_arr) == 0:
            vectors_to_save = np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
        else:
            # self._vectors may hold more rows than len(self._keys): a
            # single put_many() batch with duplicate keys (common here --
            # many Olist reviews share identical short text) appends one
            # row per input text but keeps only the LAST occurrence's index
            # in self._keys, orphaning the earlier rows. _load() re-derives
            # each key's index from its position in the sorted keys array
            # (0..N-1), which is only correct if the saved vectors array is
            # exactly N rows, one per unique key, in that same order.
            # Saving self._vectors verbatim (with orphaned rows still in
            # it) desyncs that positional mapping on the next load, so
            # compact it down to one row per key first.
            vectors_to_save = np.stack([self._vectors[self._keys[k]] for k in keys_arr])
        np.savez_compressed(self.path, keys=keys_arr, vectors=vectors_to_save)

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "entries": len(self._keys)}


def embed_query(text: str) -> np.ndarray:
    model = get_model()
    vec = model.encode([QUERY_PREFIX + text], normalize_embeddings=True)[0]
    return vec.astype(np.float32)


def embed_passage(text: str) -> np.ndarray:
    model = get_model()
    vec = model.encode([PASSAGE_PREFIX + text], normalize_embeddings=True)[0]
    return vec.astype(np.float32)


def embed_reviews_batch(texts: list[str], cache: EmbeddingCache, batch_size: int = 64) -> np.ndarray:
    """Checks the cache per item first, embeds only cache misses in batched
    model.encode() calls, writes new vectors back to the cache, and returns
    the full (n, EMBEDDING_DIM) matrix in input order."""
    keys = [cache_key(t) for t in texts]
    result = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
    miss_indices: list[int] = []
    for i, key in enumerate(keys):
        cached = cache.get(key)
        if cached is not None:
            result[i] = cached
        else:
            miss_indices.append(i)

    if miss_indices:
        model = get_model()
        miss_texts = [PASSAGE_PREFIX + texts[i] for i in miss_indices]
        embedded = model.encode(miss_texts, normalize_embeddings=True, batch_size=batch_size)
        embedded = np.asarray(embedded, dtype=np.float32)
        for j, i in enumerate(miss_indices):
            result[i] = embedded[j]
        cache.put_many([keys[i] for i in miss_indices], embedded)

    return result
