"""
bm25_retriever.py — Step 4A: lexical BM25 retriever over the review corpus.

Implements Robertson & Spärck Jones BM25 (BM25+) entirely in numpy — no
external library required. Designed to slot into the retriever abstraction
defined in retriever_interface.py.

BM25 parameters:
  k1 = 1.5  (term frequency saturation — tuned for short informal text)
  b  = 0.75 (length normalization — standard default)
  delta = 1.0 (BM25+ floor to prevent zero scores for matching terms)

Tokenization:
  - NFKC unicode normalization (matches review_ingestion.py)
  - Lowercase
  - Portuguese-aware regex tokenizer (handles accented chars)
  - Stop-words: a small, governed bilingual list (Portuguese + English)
    — NOT loaded from NLTK, just a hardcoded constant, so the module has
    zero extra dependencies.

Design decisions:
  - Inverted index stored as dict[term -> list[(doc_idx, tf)]] for O(1)
    lookups per query term, sparse over the full vocabulary.
  - IDF uses smooth BM25+ formula: log((N - df + 0.5) / (df + 0.5) + 1)
    to avoid negative scores on high-frequency terms.
  - candidate_positions parameter restricts scoring to pre-filtered subset,
    matching the structured-first pipeline contract in retrieval.py.
  - Query expansion via a small governed bilingual vocabulary (no LLM).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter, defaultdict
from typing import Optional

# ── tokenizer ──────────────────────────────────────────────────────────────

# Matches Unicode letters and digits (includes accented Portuguese chars)
_TOKEN_RE = re.compile(r"[^\W\d_][\w]*", re.UNICODE)

# Governed bilingual stop-word list — intentionally small.
# Only removes truly uninformative function words; domain words (e.g.
# "produto", "entrega") are deliberately kept so BM25 can rank on them.
_STOP_WORDS = frozenset({
    # Portuguese function words
    "a", "à", "ao", "as", "às", "de", "do", "da", "dos", "das",
    "e", "é", "em", "no", "na", "nos", "nas", "o", "os", "um", "uma",
    "uns", "umas", "que", "se", "ou", "por", "para", "com", "não",
    "mais", "mas", "me", "te", "lhe", "nos", "vos", "lhes",
    "eu", "tu", "ele", "ela", "nós", "vós", "eles", "elas",
    "esse", "essa", "esses", "essas", "este", "esta", "estes", "estas",
    "aquele", "aquela", "aqueles", "aquelas", "isso", "isto", "aquilo",
    "muito", "bem", "já", "só", "até",
    # English function words (small set — Olist corpus is ~95% PT)
    "the", "a", "an", "in", "on", "at", "to", "of", "and", "or",
    "is", "was", "are", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "will", "would", "should", "could",
    "not", "no", "it", "its", "i", "you", "he", "she", "we", "they",
})

# ── governed query expansion vocabulary ─────────────────────────────────────
# Small, manually-curated bilingual synonym map.
# Maps each canonical concept → list of Portuguese/English synonyms.
# Only used when the caller passes expand_query=True.
# These are observation-domain terms — NOT generic word embeddings.
QUERY_EXPANSION_MAP: dict[str, list[str]] = {
    # delivery / shipping
    "delivery":  ["entrega", "envio", "prazo", "demorou", "atraso", "atrasado",
                  "demora", "demorado", "chegou", "recebimento"],
    "entrega":   ["delivery", "envio", "prazo", "demorou", "atraso", "atrasado",
                  "demora", "chegou"],
    "atraso":    ["atrasado", "demorou", "demora", "demorado", "prazo", "passou",
                  "delay", "late"],
    "demora":    ["demorou", "demorado", "atraso", "atrasado", "prazo", "delay"],
    "envio":     ["entrega", "enviar", "shipped", "shipping", "postagem"],
    # product quality
    "quality":   ["qualidade", "defeito", "quebrado", "estragado", "danificado",
                  "defeituoso", "problema"],
    "qualidade": ["quality", "defeito", "defeituoso", "danificado", "estragado"],
    "defeito":   ["defeituoso", "danificado", "quebrado", "estragado", "falha",
                  "defective", "broken", "damaged"],
    "quebrado":  ["quebrada", "quebrou", "defeito", "danificado", "broken"],
    "estragado": ["estragada", "estragou", "defeito", "danificado", "broken"],
    # satisfaction
    "péssimo":   ["horrível", "ruim", "terrível", "decepcionante", "worst",
                  "terrible", "awful"],
    "horrível":  ["péssimo", "ruim", "terrível", "awful", "horrible"],
    "ótimo":     ["excelente", "perfeito", "maravilhoso", "great", "excellent"],
    "excelente": ["ótimo", "perfeito", "maravilhoso", "excellent", "great",
                  "outstanding"],
}


def tokenize(text: str) -> list[str]:
    """NFKC-normalize, lowercase, regex-tokenize, remove stop-words."""
    normalized = unicodedata.normalize("NFKC", text).lower()
    tokens = _TOKEN_RE.findall(normalized)
    return [t for t in tokens if t not in _STOP_WORDS and len(t) >= 2]


def expand_query_tokens(tokens: list[str]) -> list[str]:
    """Expand tokens using the governed bilingual vocabulary.
    Returns the original tokens PLUS any synonyms found, deduplicated
    in insertion order. Never uses an LLM."""
    seen: set[str] = set(tokens)
    expanded: list[str] = list(tokens)
    for tok in tokens:
        for synonym in QUERY_EXPANSION_MAP.get(tok, []):
            if synonym not in seen:
                seen.add(synonym)
                expanded.append(synonym)
    return expanded


# ── BM25 index ──────────────────────────────────────────────────────────────

class BM25Index:
    """BM25+ inverted index over a list of text documents.

    Construction is O(n·L) where n = number of documents and L = average
    doc length. Query is O(q·df) where q = number of unique query terms
    and df = per-term document frequency — fast even without FAISS/Lucene
    for a ~5 000-document corpus.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75, delta: float = 1.0):
        self.k1 = k1
        self.b = b
        self.delta = delta

        # Core data structures
        self._doc_lengths: list[int] = []
        self._avgdl: float = 0.0
        self._N: int = 0
        # inverted index: term → list of (doc_idx, tf)
        self._inverted: dict[str, list[tuple[int, int]]] = defaultdict(list)
        # document frequency per term
        self._df: dict[str, int] = {}
        # raw token lists kept for potential future use
        self._doc_tokens: list[list[str]] = []

    @classmethod
    def build(cls, texts: list[str], k1: float = 1.5, b: float = 0.75,
              delta: float = 1.0) -> "BM25Index":
        idx = cls(k1=k1, b=b, delta=delta)
        idx._N = len(texts)
        total_len = 0

        for doc_idx, text in enumerate(texts):
            tokens = tokenize(text)
            idx._doc_tokens.append(tokens)
            idx._doc_lengths.append(len(tokens))
            total_len += len(tokens)

            tf_map = Counter(tokens)
            for term, tf in tf_map.items():
                idx._inverted[term].append((doc_idx, tf))

        idx._avgdl = total_len / max(1, idx._N)
        idx._df = {term: len(postings) for term, postings in idx._inverted.items()}
        return idx

    def idf(self, term: str) -> float:
        """Smooth BM25+ IDF — never negative."""
        df = self._df.get(term, 0)
        return math.log((self._N - df + 0.5) / (df + 0.5) + 1.0)

    def score(self, query_tokens: list[str],
              candidate_positions: Optional[list[int]] = None) -> list[tuple[int, float]]:
        """Score all (or candidate_positions) documents against query_tokens.

        Returns [(doc_idx, bm25_score), ...] sorted by descending score,
        excluding docs with score == 0.

        candidate_positions restricts scoring to a pre-filtered subset,
        matching retrieval.py's structured-first contract.
        """
        if not query_tokens or self._N == 0:
            return []

        candidate_set: Optional[set[int]] = (
            set(candidate_positions) if candidate_positions is not None else None
        )

        accum: dict[int, float] = {}
        k1, b, delta, avgdl = self.k1, self.b, self.delta, self._avgdl

        for term in set(query_tokens):  # deduplicate query terms
            idf_val = self.idf(term)
            if idf_val <= 0:
                continue
            postings = self._inverted.get(term)
            if not postings:
                continue
            for doc_idx, tf in postings:
                if candidate_set is not None and doc_idx not in candidate_set:
                    continue
                dl = self._doc_lengths[doc_idx]
                norm_tf = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
                bm25_plus_score = idf_val * (norm_tf + delta)
                accum[doc_idx] = accum.get(doc_idx, 0.0) + bm25_plus_score

        if not accum:
            return []

        return sorted(accum.items(), key=lambda p: -p[1])

    def query(self, query_text: str,
              k: int = 10,
              candidate_positions: Optional[list[int]] = None,
              expand: bool = False) -> list[tuple[int, float]]:
        """Tokenize query_text, optionally expand, score, return top-k."""
        tokens = tokenize(query_text)
        if expand:
            tokens = expand_query_tokens(tokens)
        scored = self.score(tokens, candidate_positions=candidate_positions)
        return scored[:k]

    def stats(self) -> dict:
        return {
            "n_docs": self._N,
            "vocab_size": len(self._df),
            "avg_doc_length": round(self._avgdl, 2),
            "k1": self.k1,
            "b": self.b,
            "delta": self.delta,
        }
