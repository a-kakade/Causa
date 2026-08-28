# STEP 4A VALIDATION — Retrieval Failure Analysis and Optimization

Every number in this document is computed live via real scripts against
the actual October-November 2017 Olist review corpus. None are hardcoded.

Full machine-readable output:
- `reports/step4a_retrieval_benchmark.json`
- `reports/step4a_length_analysis.json`
- `reports/step4a_language_analysis.json`
- `reports/step4a_extended_benchmark.json` (E5-base/large + cross-encoder)

Diagnostic report: `STEP4_RETRIEVAL_DIAGNOSTIC.md`

Reproduce:

```bash
.venv/bin/python scripts/step4a_retrieval_benchmark.py
.venv/bin/python scripts/step4a_extended_benchmark.py   # needs HF_TOKEN
.venv/bin/python -m pytest tests/test_bm25.py tests/test_review_pipeline.py -v
```

---

## 0. 2026-08-28 update: the real root cause was a cache bug, not E5-small

This document originally concluded (§1.2 below, preserved for the audit
trail) that `multilingual-e5-small` had an intrinsic ~0.05-cosine
discrimination gap on this corpus, making dense retrieval nearly useless
(P@5=0.0, MRR=0.017). **That diagnosis was wrong.** The actual cause was a
disk-persistence bug in `EmbeddingCache` (`src/evidence/embeddings.py`):

- `EmbeddingCache.put_many()` appended new vectors using
  `start = len(self._keys)` (the *unique*-key count) as the array offset,
  not the vector array's actual row count.
- `EmbeddingCache.save()` then persisted **every** row in `self._vectors`
  (including orphaned rows left behind when a batch contained duplicate
  texts), but only the currently-referenced unique keys.
- `EmbeddingCache._load()` re-derives each key's index from its position in
  the *sorted keys array* (`{k: i for i, k in enumerate(keys)}`), which is
  only correct if the saved vector array has exactly one row per key, in
  that same order.

This corpus has 427 duplicate review texts out of 5,019 (e.g. many reviews
say only "Otimo produto" or "recomendo"), so nearly every `save()` →
reload cycle silently desynced the key → vector mapping: `cache.get(key)`
would return some *other* review's real, valid E5 embedding instead of the
one asked for. The corrupted vectors were never garbage or NaN — they were
genuine passage embeddings of different Portuguese review text — so cosine
scores still looked plausible (clustered in the same 0.84-0.92 band
documented in §1.2), which is exactly why this was invisible until the
disk cache was compared row-by-row against a fresh re-encode of the same
text:

```
row 128 ('Demorou de mais pra entrega'):        cos(cached, fresh) = 0.865
row 2567 ('Tentei obter uma resposta...'):      cos(cached, fresh) = 0.848
row 3648 ('Além da demora para emitir...'):     cos(cached, fresh) = 0.868
# ... all 31 eval-set expected rows: 0.83-0.90, never 1.0
```

versus rows with no duplicate elsewhere in the corpus, which matched
exactly (`cos = 1.000000`). A minimal repro:

```python
cache = EmbeddingCache(path=tmp)
cache.put_many(["A", "B", "A"], vectors_1)   # "A" appears twice
cache.put_many(["C", "D"], vectors_2)
cache.save()
reloaded = EmbeddingCache(path=tmp)
reloaded.get("C")  # returns A's vector, not C's, before the fix
```

**Fix** (both in `src/evidence/embeddings.py`):
1. `put_many()` now uses `self._vectors.shape[0]` as the append offset,
   not `len(self._keys)`.
2. `save()` now compacts `self._vectors` down to exactly one row per
   unique key, in the same order `_load()` will re-derive indices from,
   before writing to disk.

Both are covered by new regression tests in `tests/test_review_pipeline.py`
(`test_embedding_cache_put_many_survives_duplicate_keys_across_calls`,
`test_embedding_cache_survives_save_reload_with_duplicate_keys`). The
corrupted `data/evidence/embedding_cache/reviews_e5_small_v1.npz` was
deleted and rebuilt from scratch; every one of the 5,019 cached vectors now
matches a fresh single-item re-encode exactly (`cos = 1.0`), and a full
independent batch re-encode of the whole corpus matches the rebuilt index
byte-for-byte (`max L2 diff = 0.0`).

**Every number in the rest of this document has been re-measured against
the corrected cache.** The updated picture: BM25+expansion is still the
best single method, but its margin over dense E5-small shrank from a
false "22x MRR improvement" to a real "+17%" (MRR 0.389 vs. 0.333) — dense
retrieval on this corpus was never as broken as first reported. §1.2-§13
below are otherwise left as originally written (for the audit trail) except
where a table's numbers changed; §14 (Known Limitations) is fully updated.

---

## 1. Failure Diagnosis

### 1.1 What was investigated

Starting point (later found to be a cache-corruption artifact, see §0):
P@5 = 0.0, P@10 = 0.017, MRR = 0.017 on the 6-query engineering eval set
using multilingual-e5-small.

All 10 diagnostic axes originally audited:

| Axis | Finding |
|---|---|
| Evaluation-set problems | ✅ All 31 expected row_ids ARE in the index (0 missing) |
| Query formulation | ✅ Correct Portuguese keyword phrases |
| E5 prefix convention | ✅ `query: ` / `passage: ` applied correctly |
| Preprocessing | ✅ NFKC normalization correct |
| Language detection | ✅ Metadata-only, not a filter |
| Embedding normalization | ✅ L2-normalized, cosine = dot product |
| Similarity/ranking | ✅ Descending cosine, correct |
| Vector search | ✅ Candidate restriction works |
| Metadata filtering | ✅ Structured pre-filter correct |
| Intrinsic difficulty | ⚠️ Real, but much smaller than first measured (see §0) |
| **Embedding cache persistence** | **❌ ACTUAL ROOT CAUSE — see §0** |
| No lexical fallback | ❌ Still a real contributing cause — BM25 still wins |

### 1.2 Originally-reported (incorrect) root cause: E5-small discrimination gap

*(Preserved for the audit trail — see §0 for what this measurement was
actually seeing.)*

Live measured cosine similarity — delivery query vs. diverse passages,
against the then-corrupted cache:

| Passage | Score | Relevant? |
|---|---|---|
| "Demorou de mais pra entrega" | **0.9044** | ✅ |
| "produto atrasado sem resposta da loja" | **0.8919** | ✅ |
| "Tentei obter uma resposta sobre o atraso..." | **0.8683** | ✅ |
| "Produto com defeito apresenta risco" | 0.8712 | ❌ |
| "O produto veio estragado" | 0.8676 | ❌ |
| "bom vendedor, produto chegou certo" | 0.8538 | ❌ |
| "tudo certo recebi o produto" | 0.8443 | ❌ |

Because the cache-corruption bug silently substitutes one review's real
embedding for another's, this table's *scores* are genuine E5 outputs and
the *general* observation (short, informal PT reviews cluster tightly in
cosine space) remains true and is re-confirmed post-fix — see §7. What was
wrong was attributing the eval set's 0.0/0.017 P@5/MRR entirely to this
effect, when most of it was actually specific expected-document vectors
being swapped for unrelated ones.

### 1.3 Contributing causes (still valid post-fix)

- **Short reviews dominate:** Average doc length = 7.63 tokens.
- **No lexical baseline:** Exact-match on domain keywords was absent
  (addressed in §2).
- **Informal Portuguese:** Non-standard spelling ("pra" vs "para")
  under-represented in E5-small's training data.

---

## 2. BM25 Lexical Baseline

### 2.1 Implementation

**File:** `src/evidence/bm25_retriever.py`

- BM25+ with k1=1.5, b=0.75, delta=1.0
- Pure Python/numpy — zero new dependencies
- Portuguese-aware regex tokenizer
- Bilingual stop-word list (~50 words, governed)
- Governed query expansion vocabulary (~40 entries, no LLM)
- Build time: **0.035 seconds** over 5,019 documents

BM25 never touches embeddings or the disk cache, so none of its numbers
were affected by the §0 cache bug — every figure below is unchanged from
the original measurement.

### 2.2 BM25 results (live)

| Metric | Dense E5-small (corrected, §3) | BM25 | Difference |
|---|---|---|---|
| P@5 | 0.067 | **0.133** | 2× |
| P@10 | 0.033 | **0.083** | 2.5× |
| Recall@10 | 0.049 | **0.161** | 3.3× |
| MRR | 0.333 | **0.333** | tie |
| Latency | ~1,087 ms (cold) | **0.9 ms** | ~1200× faster |

BM25 still wins on P@5/P@10/Recall@10 and matches dense on MRR, at a
fraction of the latency and zero model/GPU cost. Short keyword-rich
Portuguese reviews remain a regime where exact-match term weighting is
genuinely strong — but (unlike the original write-up implied) dense
retrieval is competitive here too, not a non-contender.

---

## 3. Dense Baseline Validation

**Files:** `src/evidence/dense_retriever.py`, `src/evidence/embeddings.py`

E5EmbeddingProvider wraps the E5 model with injected model name — never
hardcoded. DenseRetriever takes it as a constructor parameter.

### 3.2 E5 configuration verified

| Field | Value | Status |
|---|---|---|
| Model | `intfloat/multilingual-e5-small` | ✅ Correct |
| Revision | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | ✅ Pinned |
| Query prefix | `"query: "` | ✅ Applied |
| Passage prefix | `"passage: "` | ✅ Applied |
| Normalize | `True` | ✅ L2-normalized |
| Similarity | Cosine via dot product | ✅ Correct |

### 3.3 Dense baseline results (corrected, post cache-fix)

| Metric | Value |
|---|---|
| P@5 | 0.067 |
| P@10 | 0.033 |
| Recall@10 | 0.049 |
| MRR | 0.333 |
| Latency (cold, incl. model load) | ~1,087 ms |
| Latency (warm query embed) | ~20 ms |
| Index size | 5,019 × 384 float32 ≈ 7.4 MB |

Dense retrieval is correctly deployed **and performs reasonably** on this
corpus once measured against the corrected cache — 2 of 6 eval queries
(`pq1`, `pe1`) retrieve their best relevant review at rank 1 (MRR
contribution = 1.0 each). It still trails BM25+expansion overall (§11),
consistent with the corpus's short, informal-Portuguese text being a hard
regime for a 117M-parameter multilingual encoder, but the gap is a modest
one, not the near-total failure originally reported.

---

## 4. Hybrid Retrieval

### 4.1 Implementation

**File:** `src/evidence/hybrid_retriever.py`

Method: **Reciprocal Rank Fusion (RRF)** — Cormack et al. (2009).

```
score(d) = Σ_r 1 / (60 + rank_r(d))
```

k=60 (standard). No learned weights. No LLM.

### 4.2 Hybrid results (corrected)

| Metric | BM25 | Dense | Hybrid RRF | Hybrid+Expand |
|---|---|---|---|---|
| P@5 | **0.133** | 0.067 | 0.067 | 0.033 |
| P@10 | 0.083 | 0.033 | **0.083** | **0.083** |
| Recall@10 | **0.161** | 0.049 | 0.149 | 0.136 |
| MRR | **0.333** | **0.333** | 0.296 | 0.230 |
| Latency | **0.9 ms** | 1,087 ms | 14.9 ms | 14.0 ms |

**Revised key finding:** now that dense retrieval has genuine signal
(MRR=0.333, not the originally-measured 0.0), RRF fusion *still* does not
beat either individual method — it lands 11% below BM25/Dense on MRR. This
is a more interesting result than the original "garbage-in-garbage-out"
explanation: even when both retrievers independently perform well, naive
rank-based fusion can dilute rather than reinforce signal when the two
methods agree on *which* documents are relevant but disagree on their
exact rank order within the top-10. Hybrid RRF is not recommended here
regardless of which retriever's numbers you trust.

---

## 5. Reranking Evaluation

### 5.1 Cross-encoder results (now evaluated — HF auth restored 2026-08-28)

Three cross-encoder models were probed and all loaded successfully:
`amberoad/bert-multilingual-passage-reranking-msmarco`,
`cross-encoder/ms-marco-MiniLM-L-6-v2`, `cross-encoder/ms-marco-MiniLM-L-12-v2`.

The multilingual one (`amberoad/...`) was used to rerank the top-50
candidates from BM25+expansion and from Hybrid RRF+expansion down to
top-10. Note: this model is a 2-class classifier (logits for
`[not_relevant, relevant]`), not a scalar-score cross-encoder like the
MiniLM models — `scripts/step4a_extended_benchmark.py`'s `rerank()` was
fixed to soft-max the two logits and use the "relevant" class probability
as the ranking score (its original `key=lambda p: -p[1]` crashed with
`TypeError: bad operand type for unary -: 'list'` on this model's
`(n, 2)` output shape).

| Method | P@5 | P@10 | Recall@10 | MRR | Latency |
|---|---|---|---|---|---|
| BM25+expand → CE rerank | 0.067 | 0.050 | 0.100 | 0.333 | 459.6 ms |
| Hybrid RRF+expand → CE rerank | 0.067 | 0.050 | 0.100 | 0.333 | 516.3 ms |

### 5.2 Verdict

Cross-encoder reranking ties plain E5-small's MRR (0.333) but does **not**
beat BM25+expansion alone (0.389), while adding 450-500× the latency of
BM25 and reloading a ~700MB model. Not recommended for deployment on this
corpus/eval-set size. It may earn its cost on a larger, more ambiguous
query set where reranking has more candidates worth discriminating between
— re-evaluate if the eval set grows past 6 queries (§14).

---

## 6. Query Expansion

### 6.1 Implementation

`QUERY_EXPANSION_MAP` in `bm25_retriever.py` — governed bilingual
vocabulary, no LLM, no NLTK:

```python
"atraso": ["atrasado", "demorou", "demora", "demorado", "prazo", ...],
"defeito": ["defeituoso", "danificado", "quebrado", "estragado", ...],
```

### 6.2 Effect

BM25 never touches embeddings, so this section is unaffected by the §0 fix.

| Method | P@5 | P@10 | MRR |
|---|---|---|---|
| BM25 | 0.133 | 0.083 | 0.333 |
| BM25 + expansion | 0.133 | 0.083 | **0.389** |

MRR improves by +0.056. A relevant document moves to a higher rank
position when its synonym matches the expanded query. P@K is unchanged
because the same set of docs is returned.

---

## 7. Short-Review Analysis

### 7.1 Length bucket breakdown (recall@10, corrected)

| Token bucket | # Expected docs | BM25 recall | Dense recall |
|---|---|---|---|
| 1–3 tokens | 0 | — | — |
| 4–10 tokens | 12 | 0.083 | **0.167** |
| 11–25 tokens | 15 | **0.267** | 0.000 |
| 25+ tokens | 7 | 0.000 | 0.000 |

Dense now *beats* BM25 in the 4-10 token bucket (0.167 vs 0.083) — the
shortest reviews, where exact keyword overlap is least likely and semantic
similarity has more room to help. BM25 still dominates the 11-25 token
bucket, where there's enough text for keyword matching to work reliably.
25+ token bucket still fails both methods.

### 7.2 Language breakdown (recall@10, corrected)

| Language | # Expected docs | BM25 | Dense |
|---|---|---|---|
| PT | 34 | 0.147 | 0.059 |
| EN | 0 | — | — |

Dense retrieval is no longer at exactly 0.000 on PT (was the headline
"dense fails on PT" claim in the original write-up) — it recovers 2 of 34
expected documents, versus BM25's 5 of 34. Still a real gap, just not the
total failure first reported.

---

## 8. Model Comparison

| Model | P@5 | MRR | Latency (warm) | Memory | Status |
|---|---|---|---|---|---|
| E5-small (117M) | **0.067** | **0.333** | ~20ms | ~448MB | Evaluated |
| E5-base (~278M) | 0.033 | 0.190 | ~28ms | ~1.1GB | **Evaluated (2026-08-28)** |
| E5-large (~560M) | 0.033 | 0.190 | ~45ms | ~2.2GB | **Evaluated (2026-08-28)** |
| **BM25+expansion** | **0.133** | **0.389** | **1.0ms** | **<1MB** | Evaluated |

**Counter-intuitive finding:** E5-base and E5-large both score *worse*
than E5-small on this eval set (MRR 0.190 vs. 0.333), not better. This
could mean larger multilingual E5 checkpoints are tuned more for
longer-document retrieval and lose relative sharpness on ultra-short
informal text — but it could just as easily be noise from a 6-query eval
set, where one or two rank flips swing MRR by 0.1+. Treat "bigger E5
hurts here" as a hypothesis, not a conclusion, until re-tested on a larger
eval set (§14). It does NOT change the recommendation in §12 — BM25+expansion
was already ahead of every dense variant.

---

## 9. Retriever Architecture

### 9.1 New components

```
EmbeddingProvider (protocol)          retriever_interface.py
    ↓
E5EmbeddingProvider.from_config()     dense_retriever.py
    ↓
DenseRetriever                        dense_retriever.py

BM25Index                             bm25_retriever.py
    ↓
LexicalRetriever                      hybrid_retriever.py

LexicalRetriever + DenseRetriever
    ↓ RRF fusion
HybridRetriever                       hybrid_retriever.py
    ↓
RetrievalInsufficient sentinel        retriever_interface.py
    ↓
Evidence objects
```

### 9.2 Backwards compatibility

`src/evidence/retrieval.py` is NOT modified. The existing `retrieve()`
function and all `test_retrieval.py` tests pass unchanged.

---

## 10. RETRIEVAL_INSUFFICIENT Sentinel

**File:** `src/evidence/retriever_interface.py`

```python
@dataclass(frozen=True)
class RetrievalInsufficient:
    candidate_count: int
    best_score: float
    retrieval_method: str   # "bm25" | "dense_e5" | "hybrid_rrf"
    coverage: float
    reason: str
    SENTINEL: str = "RETRIEVAL_INSUFFICIENT"
```

Score floors: `MIN_DENSE_SCORE_FLOOR = 0.82`, `MIN_BM25_SCORE_FLOOR = 0.5`.
When retrieval confidence is too low, the system returns this sentinel
rather than filling top-K with arbitrary results. The Confidence Judge
(Step 5) consumes this signal to decide whether to abstain or escalate.
These floors were set against the (at the time believed-correct, actually
corrupted) dense baseline; now that genuine dense scores are confirmed to
still commonly land at 0.84-0.92 for both relevant and irrelevant passages
(§1.2/§7), `MIN_DENSE_SCORE_FLOOR = 0.82` remains a reasonable floor — it
was never actually recalibrated off the corrupted numbers, so no change
needed, but this is now backed by verified-correct measurements rather
than corrupted ones.

---

## 11. Final Comparison Table (corrected, 2026-08-28)

| Method | P@5 | P@10 | R@10 | MRR | Latency | Memory |
|---|---|---|---|---|---|---|
| Dense E5-small | 0.067 | 0.033 | 0.049 | 0.333 | ~1,087ms cold / ~20ms warm | ~448MB |
| Dense E5-base | 0.033 | 0.050 | 0.069 | 0.190 | ~28ms warm | ~1.1GB |
| Dense E5-large | 0.033 | 0.033 | 0.061 | 0.190 | ~45ms warm | ~2.2GB |
| BM25 | 0.133 | 0.083 | 0.161 | 0.333 | **0.9ms** | **<1MB** |
| **BM25 + expansion** | **0.133** | 0.083 | 0.149 | **0.389** | 1.0ms | <1MB |
| Hybrid RRF | 0.067 | 0.083 | 0.149 | 0.296 | 14.9ms | ~449MB |
| Hybrid RRF + expand | 0.033 | 0.083 | 0.136 | 0.230 | 14.0ms | ~449MB |
| BM25+expand → CE rerank | 0.067 | 0.050 | 0.100 | 0.333 | 459.6ms | ~1.1GB |
| Hybrid+expand → CE rerank | 0.067 | 0.050 | 0.100 | 0.333 | 516.3ms | ~1.1GB |

*(Superseded numbers from the corrupted-cache measurement, kept for the
audit trail: Dense E5-small was originally reported as P@5=0.000,
P@10=0.000, R@10=0.000, MRR=0.000 at ~1,284ms — see §0.)*

---

## 12. Architecture Recommendation

**Recommended: BM25 + query expansion as primary retriever.** (Unchanged
conclusion, revised justification.)

Reasons:
1. **Evidence quality:** MRR=0.389 vs. dense E5-small's corrected 0.333 —
   a genuine +17% improvement, not the previously-claimed 22×.
2. **Traceability:** BM25 term scores fully decomposable — no opaque
   vectors.
3. **Latency:** 1.0ms vs. ~20-1,087ms for dense, ~460-520ms for
   cross-encoder reranking — 20-1200× faster depending on comparison.
4. **Cost:** Zero GPU, zero model memory beyond the tokenizer, zero
   download.
5. **Hybrid hurts here regardless of dense quality:** RRF fusion
   underperforms both individual methods even now that dense has real
   signal (§4.2) — this is a structural property of rank-fusion on this
   eval set, not an artifact of one retriever being broken.
6. **Bigger E5 models don't help:** E5-base/large both score below
   E5-small (§8) — model-size scaling is not a promising direction here
   without further investigation.
7. **Cross-encoder reranking doesn't clear the bar either:** ties E5-small's
   MRR at 450-500× BM25's latency (§5).
8. **Expansion is free:** +0.056 MRR with a hardcoded synonym table.

Future path:
1. Grow the eval set past 6 queries before trusting any of the §8/§5
   comparisons as more than directional — single-query rank flips
   currently move MRR by ±0.17.
2. Re-run the full model/reranker comparison once the eval set is larger;
   the current ranking (BM25+expansion > E5-small ≈ CE-rerank > E5-base ≈
   E5-large > Hybrid RRF) may not hold at scale.
3. Add a cache-integrity spot-check (compare N random cached vectors
   against a fresh re-encode) to CI or the build pipeline, so a
   regression like §0's ever gets caught automatically rather than by a
   manual row-by-row audit.

---

## 13. Tests

### `tests/test_bm25.py` — 37 tests

| Class | Tests |
|---|---|
| TestTokenize | 8 |
| TestQueryExpansion | 6 |
| TestBM25Index | 12 |
| TestBM25EdgeCases | 4 |
| TestRRFFusion | 5 |
| TestRetrievalInsufficient | 2 |

### `tests/test_review_pipeline.py` — 2 new regression tests (2026-08-28)

- `test_embedding_cache_put_many_survives_duplicate_keys_across_calls`
- `test_embedding_cache_survives_save_reload_with_duplicate_keys`

Both reproduce the §0 bug directly (no model load required — synthetic
keys/vectors) and fail against the pre-fix code.

All 547 tests pass (545 existing + 2 new). 0 regressions.

---

## 14. Known Limitations

- **Fixed 2026-08-28:** cross-encoder reranking and E5-base/E5-large were
  blocked by an expired HF token; a fresh token unblocked all three. Cross-
  encoder reranking ties E5-small's MRR at 450-500× the latency of BM25 —
  not recommended. E5-base/E5-large both score *below* E5-small on this
  eval set, an unexpected result that needs a larger eval set to confirm
  or refute (see next point).
- **Eval set is small (6 queries)** — directionally correct, not
  statistically robust. This matters more than the original write-up
  implied: the §0 cache-corruption fix alone moved MRR from 0.017 to
  0.333, and the E5-base/E5-large "regression" in §8 could easily be
  eval-set noise of similar magnitude. Any single-digit-query eval set
  should be treated as a smoke test, not a leaderboard.
- BM25 cannot generalize across languages (not needed for this corpus).
- 1–3-token reviews: the current eval set has zero expected documents in
  this bucket, so this limitation is untested rather than confirmed;
  either result is possible.
- **New:** a cache/index correctness check (fresh-vs-cached spot check,
  or a full round-trip test after every `save()`) does not yet run
  automatically — the §0 bug shipped silently through five prior "Step"
  commits before being caught by a manual audit. Recommended follow-up,
  not yet implemented.

---

## STOP CONDITION MET

1. ✅ Failure source diagnosed: originally misattributed to an E5-small
   discrimination gap; actual root cause found and fixed 2026-08-28 — an
   `EmbeddingCache` save/reload bug that silently swapped cached
   embeddings between reviews sharing duplicate text (§0).
2. ✅ BM25 baseline implemented and benchmarked (MRR=0.389 vs. corrected
   dense MRR=0.333 — a real but modest +17%, not the previously-claimed
   22×).
3. ✅ Dense baseline validated and re-measured against the corrected
   cache: genuinely competitive with BM25 on MRR, still behind on
   P@5/P@10/Recall@10.
4. ✅ Hybrid RRF implemented and benchmarked (still does not beat
   BM25-alone, even with corrected dual-signal inputs — a more robust
   finding than originally reported).
5. ✅ Reranking evaluated end-to-end: 3 cross-encoders probed, one
   benchmarked on real candidates (ties E5-small MRR, 450-500× slower,
   not recommended).
6. ✅ Query expansion: +0.056 MRR improvement with a governed bilingual
   vocabulary (unaffected by the cache bug, unchanged).
7. ✅ RETRIEVAL_INSUFFICIENT sentinel implemented; floors re-validated
   against corrected scores.
8. ✅ Short-review and language breakdown completed and re-measured.
9. ✅ Final retrieval architecture selected: BM25 + expansion (same
   conclusion as before, now on a corrected evidence base).
10. ✅ 547 total tests pass (545 + 2 new regression tests for the §0 bug),
    0 regressions.

Retrieval failure: originally reported as ~80% intrinsic to the corpus,
~20% architectural. **Corrected:** a meaningful share of the originally-
measured failure was neither — it was a disk-cache bug. With that fixed,
the residual gap between BM25+expansion and dense retrieval is real but
modest (+17% MRR), and short informal PT text remains a genuinely harder
regime for both methods than longer, more formal text.
