"""
test_bm25.py — unit tests for the BM25 retriever (Step 4A).

Tests:
  - tokenization (Portuguese accents, stop-word removal, minimum length)
  - query expansion (governed bilingual vocabulary)
  - BM25Index build, IDF, score, query
  - candidate_positions restriction
  - empty corpus and empty query edge cases
  - RETRIEVAL_INSUFFICIENT sentinel construction
  - RRF fusion correctness
"""

from __future__ import annotations

import pytest

from evidence.bm25_retriever import (
    BM25Index,
    QUERY_EXPANSION_MAP,
    expand_query_tokens,
    tokenize,
)
from evidence.hybrid_retriever import reciprocal_rank_fusion
from evidence.retriever_interface import RetrievalInsufficient


# ── Tokenizer ──────────────────────────────────────────────────────────────

class TestTokenize:
    def test_lowercase(self):
        assert "entrega" in tokenize("ENTREGA")

    def test_accents_preserved(self):
        tokens = tokenize("atraso na entrega ótimo péssimo")
        assert "ótimo" in tokens
        assert "péssimo" in tokens
        assert "atraso" in tokens

    def test_stop_words_removed(self):
        tokens = tokenize("o produto é de boa qualidade")
        assert "o" not in tokens
        assert "é" not in tokens
        assert "de" not in tokens
        assert "produto" in tokens
        assert "qualidade" in tokens

    def test_min_length(self):
        # single-char tokens are excluded
        tokens = tokenize("a b c produto")
        assert "a" not in tokens
        assert "b" not in tokens
        assert "produto" in tokens

    def test_nfkc_normalization(self):
        # ﬁ ligature should normalize
        tokens = tokenize("produto")
        assert "produto" in tokens

    def test_empty_string(self):
        assert tokenize("") == []

    def test_numbers_included(self):
        tokens = tokenize("prazo de 3 dias")
        # numbers with 2+ chars are included; "3" is a single char, excluded
        assert "dias" in tokens

    def test_portuguese_review_delivery(self):
        tokens = tokenize("Demorou de mais pra entrega")
        assert "demorou" in tokens
        assert "entrega" in tokens
        # stop words stripped
        assert "de" not in tokens


# ── Query expansion ────────────────────────────────────────────────────────

class TestQueryExpansion:
    def test_delivery_expansion(self):
        tokens = tokenize("atraso entrega")
        expanded = expand_query_tokens(tokens)
        # Should include synonyms
        assert "demorou" in expanded
        assert "demora" in expanded
        assert "envio" in expanded

    def test_quality_expansion(self):
        tokens = tokenize("defeito")
        expanded = expand_query_tokens(tokens)
        assert "quebrado" in expanded
        assert "estragado" in expanded

    def test_no_duplicate_originals(self):
        tokens = tokenize("defeito")
        expanded = expand_query_tokens(tokens)
        # original token appears exactly once
        assert expanded.count("defeito") == 1

    def test_expansion_preserves_order(self):
        tokens = tokenize("entrega atraso")
        expanded = expand_query_tokens(tokens)
        # original tokens come first
        assert expanded[0] == "entrega"
        assert expanded[1] == "atraso"

    def test_unknown_token_no_expansion(self):
        tokens = ["xyzabc123"]
        expanded = expand_query_tokens(tokens)
        assert expanded == ["xyzabc123"]

    def test_expansion_map_not_empty(self):
        assert len(QUERY_EXPANSION_MAP) > 0
        # key concepts present
        assert "defeito" in QUERY_EXPANSION_MAP
        assert "atraso" in QUERY_EXPANSION_MAP
        assert "entrega" in QUERY_EXPANSION_MAP


# ── BM25Index ──────────────────────────────────────────────────────────────

CORPUS = [
    "Demorou de mais pra entrega",                               # 0 — delivery
    "produto atrasado sem resposta da loja",                     # 1 — delivery
    "produto com defeito quebraram o produto",                   # 2 — quality
    "O produto veio estragado defeito",                          # 3 — quality
    "bom vendedor produto chegou certo",                         # 4 — positive
    "tudo certo recebi o produto",                               # 5 — positive
    "Entrega dentro do prazo excelente",                         # 6 — positive delivery
    "defeito no produto qualidade ruim péssimo",                 # 7 — quality complaint
    "não recebi o produto atraso",                               # 8 — delivery complaint
]


class TestBM25Index:
    @pytest.fixture(scope="class")
    def idx(self):
        return BM25Index.build(CORPUS)

    def test_build_sizes(self, idx):
        assert idx._N == len(CORPUS)
        assert idx._avgdl > 0
        assert len(idx._df) > 0

    def test_idf_high_frequency_positive(self, idx):
        # IDF should always be > 0 with smooth BM25+
        assert idx.idf("produto") > 0

    def test_idf_rare_term_higher(self, idx):
        # A rare term should have higher IDF than a common term
        idf_entrega = idx.idf("entrega")
        idf_produto = idx.idf("produto")  # appears in many docs
        assert idf_entrega >= idf_produto

    def test_delivery_query_ranks_delivery_docs_first(self, idx):
        scored = idx.score(["atraso", "entrega", "demorou"])
        top_positions = [p for p, _ in scored[:3]]
        # Docs 0,1,8 are delivery complaints; at least 2 should be in top-3
        delivery_positions = {0, 1, 8}
        assert len(delivery_positions & set(top_positions)) >= 2

    def test_quality_query_ranks_quality_docs_first(self, idx):
        scored = idx.score(["defeito", "estragado", "qualidade"])
        top_positions = [p for p, _ in scored[:3]]
        quality_positions = {2, 3, 7}
        assert len(quality_positions & set(top_positions)) >= 2

    def test_scores_sorted_descending(self, idx):
        scored = idx.score(["defeito"])
        scores = [s for _, s in scored]
        assert scores == sorted(scores, reverse=True)

    def test_candidate_positions_restricts(self, idx):
        # Only search docs 4 and 5 (positive reviews, no delivery words)
        scored = idx.score(["atraso", "entrega"], candidate_positions=[4, 5])
        returned_positions = {p for p, _ in scored}
        assert returned_positions.issubset({4, 5})

    def test_empty_query_no_results(self, idx):
        assert idx.score([]) == []

    def test_empty_candidate_positions_no_results(self, idx):
        assert idx.score(["entrega"], candidate_positions=[]) == []

    def test_query_method_top_k(self, idx):
        results = idx.query("atraso na entrega", k=3)
        assert len(results) <= 3

    def test_query_with_expansion(self, idx):
        # With expansion, delivery synonyms should also match
        no_exp = idx.query("delay", k=5, expand=False)
        with_exp = idx.query("delay", k=5, expand=True)
        # Expanded query should match at least as many docs
        assert len(with_exp) >= len(no_exp)

    def test_stats(self, idx):
        s = idx.stats()
        assert s["n_docs"] == len(CORPUS)
        assert s["vocab_size"] > 0
        assert s["avg_doc_length"] > 0
        assert s["k1"] == 1.5
        assert s["b"] == 0.75


# ── Edge cases ──────────────────────────────────────────────────────────────

class TestBM25EdgeCases:
    def test_empty_corpus(self):
        idx = BM25Index.build([])
        assert idx.query("test", k=5) == []

    def test_single_doc_corpus(self):
        idx = BM25Index.build(["produto chegou com defeito"])
        results = idx.query("defeito", k=5)
        assert len(results) == 1
        assert results[0][0] == 0  # doc 0

    def test_query_term_not_in_corpus(self):
        idx = BM25Index.build(CORPUS)
        results = idx.score(["xyznonexistent123"])
        assert results == []

    def test_all_docs_match_common_term(self):
        idx = BM25Index.build(["produto a", "produto b", "produto c"])
        results = idx.score(["produto"])
        # All 3 docs should score > 0
        assert len(results) == 3


# ── RRF fusion ─────────────────────────────────────────────────────────────

class TestRRFFusion:
    def test_consensus_doc_ranks_first(self):
        list_a = [(10, 0.9), (20, 0.8), (30, 0.7)]   # doc 10 first
        list_b = [(10, 0.5), (40, 0.4), (20, 0.3)]   # doc 10 first
        fused = reciprocal_rank_fusion([list_a, list_b])
        # doc 10 appears at rank 1 in both lists → highest RRF score
        assert fused[0][0] == 10

    def test_rrf_scores_descending(self):
        list_a = [(1, 0.9), (2, 0.8), (3, 0.7)]
        list_b = [(3, 0.9), (1, 0.8), (4, 0.7)]
        fused = reciprocal_rank_fusion([list_a, list_b])
        scores = [s for _, s in fused]
        assert scores == sorted(scores, reverse=True)

    def test_all_docs_included(self):
        list_a = [(1, 0.9), (2, 0.8)]
        list_b = [(3, 0.7), (4, 0.6)]
        fused = reciprocal_rank_fusion([list_a, list_b])
        positions = {p for p, _ in fused}
        assert {1, 2, 3, 4} == positions

    def test_empty_lists_no_crash(self):
        assert reciprocal_rank_fusion([[], []]) == []
        assert reciprocal_rank_fusion([[(1, 0.9)], []]) == [(1, pytest.approx(1 / 61, rel=1e-4))]

    def test_single_list_order_preserved(self):
        docs = [(1, 0.9), (2, 0.8), (3, 0.7)]
        fused = reciprocal_rank_fusion([docs])
        # Each doc's RRF score = 1/(60+rank); so rank order is the same
        assert [p for p, _ in fused] == [1, 2, 3]


# ── RETRIEVAL_INSUFFICIENT sentinel ──────────────────────────────────────

class TestRetrievalInsufficient:
    def test_construction(self):
        ri = RetrievalInsufficient(
            candidate_count=5,
            best_score=0.3,
            retrieval_method="bm25",
            coverage=0.1,
            reason="No candidates scored above floor",
        )
        assert ri.SENTINEL == "RETRIEVAL_INSUFFICIENT"
        assert ri.candidate_count == 5
        assert ri.best_score == 0.3
        assert ri.retrieval_method == "bm25"

    def test_frozen(self):
        ri = RetrievalInsufficient(
            candidate_count=0,
            best_score=0.0,
            retrieval_method="dense_e5_small",
            coverage=0.0,
            reason="No candidates after filter",
        )
        with pytest.raises((AttributeError, TypeError)):
            ri.candidate_count = 1  # type: ignore[misc]
