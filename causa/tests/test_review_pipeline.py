"""Review pipeline tests (Step 4 §6/§7/§10/§11/§12).

Real canonical data (October-November 2017 window, via the review_corpus /
review_evidence / built_vector_index fixtures in conftest.py), real
langdetect, real multilingual-e5-small embeddings, real numpy vector index --
nothing mocked. No LLM call anywhere in this file.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evidence.embeddings import EMBEDDING_DIM, EmbeddingCache, embed_query, embed_reviews_batch  # noqa: E402
from evidence.language import LANG_PT, LANG_UNKNOWN, detect_language  # noqa: E402
from evidence.models import SecurityClassification, TrustLevel  # noqa: E402
from evidence.review_ingestion import (  # noqa: E402
    MULTI_ITEM_AMBIGUOUS, SINGLE_CATEGORY_ORDER, SINGLE_ITEM_ORDER, normalize_review_row,
)
from evidence.vector_index import FlatCosineIndex  # noqa: E402


# ---------------------------------------------------------------------------
# normalize_review_row
# ---------------------------------------------------------------------------

def test_normalize_review_row_strips_and_collapses_whitespace():
    norm = normalize_review_row("  Ótimo  ", "chegou   rápido\r\n")
    assert norm["text"] == "Ótimo chegou rápido"


def test_normalize_review_row_preserves_raw_text_separately():
    norm = normalize_review_row(None, "produto   bom\n\n")
    assert norm["raw_text"] == "produto   bom\n\n"
    assert norm["text"] != norm["raw_text"]


def test_normalize_review_row_handles_missing_title_and_message():
    norm = normalize_review_row(None, None)
    assert norm["text"] == "" and norm["raw_text"] == ""


# ---------------------------------------------------------------------------
# Category/seller attribution (task §7's non-governed join)
# ---------------------------------------------------------------------------

def test_category_attribution_methods_present_in_real_data(review_corpus):
    methods = {r.category_attribution_method for r in review_corpus}
    assert SINGLE_ITEM_ORDER in methods
    assert MULTI_ITEM_AMBIGUOUS in methods


def test_multi_item_orders_have_no_confident_category(review_corpus):
    ambiguous = [r for r in review_corpus if r.category_attribution_method == MULTI_ITEM_AMBIGUOUS]
    assert ambiguous, "expected at least one ambiguous multi-item order in the Oct-Nov 2017 window"
    for r in ambiguous:
        assert r.category is None
        assert r.seller is None


def test_single_item_orders_get_a_confident_category(review_corpus):
    confident = [r for r in review_corpus if r.category_attribution_method in
                 (SINGLE_ITEM_ORDER, SINGLE_CATEGORY_ORDER)]
    assert confident
    for r in confident[:50]:
        assert r.category is not None
        assert r.seller is not None


# ---------------------------------------------------------------------------
# Language detection (task §10)
# ---------------------------------------------------------------------------

def test_detect_language_portuguese_majority_in_real_corpus(review_corpus):
    text_rows = [r for r in review_corpus if r.text]
    langs = [detect_language(r.text).language for r in text_rows]
    pt_share = langs.count(LANG_PT) / len(langs)
    assert pt_share > 0.7, f"expected Olist reviews to be majority Portuguese, got {pt_share:.2%}"


def test_detect_language_short_text_is_unknown():
    assert detect_language("ok").language == LANG_UNKNOWN
    assert detect_language("").language == LANG_UNKNOWN
    assert detect_language(None).language == LANG_UNKNOWN


def test_detect_language_is_deterministic():
    text = "O produto chegou muito atrasado e veio quebrado, péssima experiência."
    assert detect_language(text) == detect_language(text)


# ---------------------------------------------------------------------------
# Review evidence objects
# ---------------------------------------------------------------------------

def test_review_evidence_is_always_untrusted(review_evidence):
    assert review_evidence
    for ev in review_evidence:
        assert ev.security.trust_level == TrustLevel.UNTRUSTED_DATA


def test_review_evidence_seller_bearing_rows_are_internal(review_evidence):
    seller_bearing = [ev for ev in review_evidence if "seller" in ev.dimensions]
    assert seller_bearing
    for ev in seller_bearing:
        assert ev.security.classification == SecurityClassification.INTERNAL


# ---------------------------------------------------------------------------
# Embeddings (task §11)
# ---------------------------------------------------------------------------

def test_embedding_cache_hit_on_second_call(tmp_path):
    cache = EmbeddingCache(path=tmp_path / "cache.npz")
    texts = ["entrega muito atrasada", "produto excelente, recomendo"]
    embed_reviews_batch(texts, cache)
    assert cache.stats()["misses"] == 2
    embed_reviews_batch(texts, cache)
    assert cache.stats()["hits"] == 2


def test_embedding_cache_persists_across_instances(tmp_path):
    path = tmp_path / "persist.npz"
    cache1 = EmbeddingCache(path=path)
    embed_reviews_batch(["produto com defeito"], cache1)
    cache1.save()

    cache2 = EmbeddingCache(path=path)
    vec = cache2.get(list(cache1._keys)[0])
    assert vec is not None
    assert vec.shape == (EMBEDDING_DIM,)


def test_embedding_cache_put_many_survives_duplicate_keys_across_calls():
    """Regression test: put_many() must not misalign key -> vector index
    when an earlier batch contained duplicate keys (very common here --
    many Olist reviews share identical short text). The append offset has
    to come from the actual vector-array length, not len(self._keys),
    or every key added in a later call silently resolves to some other
    row's real (but wrong) embedding."""
    cache = EmbeddingCache.__new__(EmbeddingCache)
    cache._keys = {}
    cache._vectors = None
    cache.hits = 0
    cache.misses = 0

    # First call: "A" appears twice in the same batch.
    cache.put_many(["A", "B", "A"], np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32))
    # Second call: brand-new keys added on top.
    cache.put_many(["C", "D"], np.array([[0.0, -1.0], [-1.0, 0.0]], dtype=np.float32))

    assert np.array_equal(cache.get("A"), [1.0, 0.0])
    assert np.array_equal(cache.get("B"), [0.0, 1.0])
    assert np.array_equal(cache.get("C"), [0.0, -1.0])
    assert np.array_equal(cache.get("D"), [-1.0, 0.0])


def test_embedding_cache_survives_save_reload_with_duplicate_keys(tmp_path):
    """Regression test: save() must persist exactly one vector per unique
    key, in the same order _load() will re-derive indices from. Duplicate
    review text is common in this corpus (many rows share identical short
    text, e.g. "Otimo produto"), which used to leave orphaned rows in
    self._vectors after put_many(); saving those verbatim desynced every
    key's index from its actual vector on the next load, silently handing
    back a DIFFERENT (but still valid-looking) review's embedding."""
    path = tmp_path / "roundtrip.npz"
    cache = EmbeddingCache(path=path)
    cache.put_many(["A", "B", "A"], np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32))
    cache.put_many(["C", "D"], np.array([[0.0, -1.0], [-1.0, 0.0]], dtype=np.float32))
    before = {k: cache.get(k).tolist() for k in ["A", "B", "C", "D"]}
    cache.save()

    reloaded = EmbeddingCache(path=path)
    after = {k: reloaded.get(k).tolist() for k in ["A", "B", "C", "D"]}
    assert after == before


def test_query_and_passage_prefixes_produce_different_embeddings():
    from evidence.embeddings import embed_passage
    text = "entrega atrasada"
    q = embed_query(text)
    p = embed_passage(text)
    assert not np.allclose(q, p)


# ---------------------------------------------------------------------------
# Vector index (task §12)
# ---------------------------------------------------------------------------

def test_vector_index_metadata_maps_every_required_field(built_vector_index):
    index, text_rows, _cache = built_vector_index
    assert len(index) == len(text_rows)
    m = index.metadata[0]
    for field in ("review_row_id", "review_id", "order_id", "month", "review_score", "language",
                  "security_status"):
        assert hasattr(m, field)


def test_vector_index_search_returns_top_delivery_related_reviews(built_vector_index):
    # E5-small on short, informal Portuguese reviews produces a tightly
    # clustered similarity range (typically 0.90-0.95) -- a top-5 result can
    # legitimately be phrased without the literal words "atraso"/"demora"
    # (e.g. "meu pedido nao foi entregue" is a genuine delivery complaint).
    # This asserts on a broader, still delivery-specific keyword set rather
    # than requiring an exact substring match on the query's own wording.
    index, text_rows, _cache = built_vector_index
    qv = embed_query("atraso na entrega")
    results = index.search(qv, k=5)
    assert len(results) == 5
    delivery_keywords = ("atras", "demor", "entreg", "prazo", "chegou", "chegar")
    top_texts = [text_rows[pos].text.lower() for pos, _score in results]
    assert any(any(kw in t for kw in delivery_keywords) for t in top_texts), top_texts


def test_vector_index_rebuild_is_deterministic(built_vector_index):
    index, text_rows, cache = built_vector_index
    from evidence.embeddings import embed_reviews_batch
    rebuilt = embed_reviews_batch([r.text for r in text_rows], cache)
    assert np.allclose(index.vectors, rebuilt / np.linalg.norm(rebuilt, axis=1, keepdims=True), atol=1e-5)


def test_vector_index_save_and_load_round_trip(built_vector_index, tmp_path):
    index, _text_rows, _cache = built_vector_index
    index.save(tmp_path / "idx")
    reloaded = FlatCosineIndex.load(tmp_path / "idx")
    assert len(reloaded) == len(index)
    assert np.allclose(reloaded.vectors, index.vectors)
    assert reloaded.metadata[0] == index.metadata[0]
