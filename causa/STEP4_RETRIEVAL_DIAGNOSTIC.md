# STEP4_RETRIEVAL_DIAGNOSTIC.md

## Evidence Fabric — Retrieval Failure Analysis

**Step:** 4A  
**Date:** 2026-08-27  
**Baseline metrics (existing system):** P@5 = 0.0, P@10 = 0.017, MRR = 0.017

---

## ⚠️ 2026-08-28 update — see `STEP4A_VALIDATION.md` §0

Most of the failure documented below turned out to be an **`EmbeddingCache`
disk-persistence bug**, not the E5-small weakness this diagnostic
concluded. `EmbeddingCache.save()` persisted orphaned vector rows left
behind by duplicate-text batches, while `_load()` re-derives each key's
index positionally from the sorted keys array — desyncing the key→vector
mapping for most of the corpus (427 of 5,019 reviews share duplicate text)
on every disk round-trip. Fixed in `src/evidence/embeddings.py`
(`put_many()` and `save()`); full root-cause writeup, repro, and corrected
numbers in `STEP4A_VALIDATION.md` §0. The rest of this document is kept
as originally written for the audit trail — its component-by-component
audit (§1-§9, §11) is still accurate; only the "root cause" framing in
§10/§12/the summary table below has been superseded.

## Executive Summary

The retrieval failure is **real, not an evaluation artefact** — but its
true cause was a caching bug (see the update above), not primarily
E5-small's semantic capability. All 31 expected review_row_ids from the
eval set ARE present in the vector index (0 missing). Originally believed
root cause (superseded):

1. ~~**Primary:** E5-small has insufficient discriminative power over very
   short, informal Portuguese reviews. The score gap between on-topic and
   off-topic text is only ~0.05 cosine units.~~ Real, but far smaller a
   factor than believed — corrected dense MRR is 0.333, not 0.017.
2. **Secondary (still valid):** The eval set uses only 5–8 expected
   documents per query against a pool of 5,019, making the task
   intrinsically hard.
3. **Contributing (still valid):** No lexical fallback existed until Step
   4A added BM25 — it remains the best single method even post-fix.

---

## Audit Findings: Component-by-Component

### 1. Evaluation Dataset

**File:** `data/evidence/eval/retrieval_eval_set.json`  
**Scope:** 6 query categories × 1 query each = 6 queries total.  
**Expected docs per query:** 5–8 (out of 5,019 indexed).  
**Verdict:** ✅ Labels are correct.

Evidence:
- All 31 expected `review_row_id` values exist in `fact_reviews.parquet`.
- All 31 are present in the vector index (confirmed by direct lookup).
- Row texts match the intent of the query label:
  - row 128: *"Demorou de mais pra entrega"* → delivery complaint ✓
  - row 859: *"O produto veio estragado"* → quality complaint ✓
  - row 1098: *"Produto com defeito apresenta risco..."* → quality ✓
- Evidence IDs are derived deterministically via
  `evidence_id_for("review", review_row_id)`.

**Finding:** The evaluation set is correctly constructed. The failure is
NOT caused by wrong labels or wrong row IDs.

---

### 2. Query Formulation

**Queries used (from `retrieval_eval_set.json`):**
| Query ID | Semantic query |
|---|---|
| dc1 | `"atraso na entrega, demora"` |
| pq1 | `"produto com defeito, quebrado, veio estragado"` |
| ls1 | `"péssimo, horrível, não recomendo"` |
| pe1 | `"excelente, ótimo, entrega rápida, adorei"` |
| sd1 | `"passou do prazo, atraso no envio"` |
| csc1 | `"problema, qualidade ruim, atraso"` |

**Verdict:** ✅ Queries are thematically correct.

Queries are short comma-separated keyword phrases — appropriate for an
E5-prefix query embedding. They are NOT translated to English before
embedding (correct: E5-small is multilingual).

**Finding:** Query formulation is not the root cause, but the short
comma-separated format may produce slightly different representations
than natural sentences. This is a known E5 trade-off, not a bug.

---

### 3. E5 Prefix Usage and Configuration

**File:** `config/embedding.yaml`

```yaml
model: intfloat/multilingual-e5-small
revision: 614241f622f53c4eeff9890bdc4f31cfecc418b3
query_prefix: "query: "
passage_prefix: "passage: "
```

**Verification:** Confirmed via code inspection that:
- `embeddings.py::embed_query()` prepends `"query: "` before encoding.
- `embeddings.py::embed_reviews_batch()` prepends `"passage: "` for every
  review text stored in the index.
- Both paths use `normalize_embeddings=True`.

**Verdict:** ✅ E5 asymmetric prefix convention is correctly implemented.

---

### 4. Preprocessing

**File:** `review_ingestion.py::normalize_review_row()`

Pipeline:
1. Concatenate `review_comment_title` + `review_comment_message` (title first)
2. NFKC unicode normalization
3. Collapse whitespace runs

**Verdict:** ✅ Preprocessing is correct and non-destructive.

Reviews with no title and no message are correctly stored as empty strings
(`text=""`) and excluded from the vector index (only `text_rows = [r for r
if r.text]` are embedded). 7,141 of 12,160 Oct-Nov 2017 reviews have no
text at all — these are correctly excluded.

---

### 5. Language Detection

**File:** `language.py`

- Uses `langdetect` with `DetectorFactory.seed = 0` (reproducible).
- Text shorter than 10 characters is classified `UNKNOWN`.

**Language distribution (Oct-Nov 2017 window, all 12,160 rows):**
| Language | Count |
|---|---|
| PT | 4,241 |
| UNKNOWN | 7,519 |
| OTHER | 374 |
| EN | 26 |

**Finding:** 62% of reviews are `UNKNOWN` (no text or < 10 chars).
Of the 5,019 reviews with text (in the index), most are PT.

**Verdict:** ✅ Language detection is correctly applied as metadata, not
as a retrieval filter. It does not cause retrieval failures.

---

### 6. Embedding Normalization

**Verification:**
```
Query vector norm: 1.0000   (confirmed via live test)
```

Passage vectors are also normalized via `normalize_embeddings=True` in
`sentence_transformers`. The `FlatCosineIndex` re-normalizes on load as a
belt-and-suspenders check.

**Verdict:** ✅ Normalization is correct. `np.dot(q, p) = cosine_similarity`
holds for all vectors in the index.

---

### 7. Similarity Metric

**File:** `vector_index.py::FlatCosineIndex.search()`

```python
scores = sub @ query_vector   # dot product of L2-normalized vectors = cosine similarity
order = np.argsort(-scores)[:k]
```

**Verdict:** ✅ Cosine similarity is correctly implemented via the
normalized dot-product path.

---

### 8. Vector Search / Candidate Restriction

**File:** `retrieval.py`

```python
pool_size = max(query.top_k * 5, query.top_k)
scored = index.search(query_vector, k=pool_size, candidate_positions=candidate_positions)
```

For top_k=10, pool_size=50. The search retrieves top-50 candidates from
the filtered subset before MMR reranking.

**Candidates after filter (from existing eval report):**
| Query | Candidates after filter |
|---|---|
| dc1 (delivery) | 5,019 |
| pq1 (quality) | 5,019 |
| ls1 (low score, filter max=2) | 1,486 |
| pe1 (positive, filter min=4) | 3,079 |
| sd1 (shipping) | 5,019 |
| csc1 (category=bed_bath_table) | 553 |

**Finding:** Structured pre-filtering is working correctly. For queries
with `review_score_max=2` (ls1), filtering reduces candidates by 70%.
For category-specific queries (csc1), filtering reduces by 89%.

**Verdict:** ✅ Candidate restriction is correctly implemented. The large
candidate pools (5,019 for unfiltered queries) mean the semantic ranker
must work harder.

---

### 9. Ranking Direction

**File:** `vector_index.py`

```python
order = np.argsort(-scores)[:k]   # descending
```

**Verdict:** ✅ Top-K is correctly selected by highest similarity, not lowest.

---

### 10. Originally-reported (superseded) root cause: E5-small Score Discrimination Failure

> **Superseded 2026-08-28** — see the update note at the top of this
> document. The scores below are genuine E5 outputs (the general
> "short PT reviews cluster tightly in cosine space" observation is
> re-confirmed post-fix in `STEP4A_VALIDATION.md` §7), but the eval set's
> near-zero P@5/MRR was mostly caused by a cache bug swapping the
> *specific* expected documents' vectors for unrelated ones, not by this
> discrimination gap alone. Corrected dense MRR is 0.333.

**Live measurement** of cosine similarity between delivery query and
representative passages:

| Text | Score | On-topic? |
|---|---|---|
| `"Demorou de mais pra entrega"` | **0.9044** | ✅ Yes |
| `"produto atrasado sem resposta da loja"` | **0.8919** | ✅ Yes |
| `"Tentei obter uma resposta sobre o atraso..."` | **0.8683** | ✅ Yes |
| `"O produto veio estragado"` | 0.8676 | ❌ No (quality) |
| `"Produto com defeito apresenta risco"` | 0.8712 | ❌ No (quality) |
| `"bom vendedor, produto chegou certo"` | 0.8538 | ❌ No (positive) |
| `"tudo certo recebi o produto"` | 0.8443 | ❌ No (positive) |

**Critical observation:**
- Best on-topic score: 0.9044
- Best off-topic score: 0.8712
- **Discrimination gap: ~0.05 cosine units**

This 0.05 gap is insufficient to reliably rank 5 specific on-topic reviews
above 5,000+ off-topic ones. Any moderate off-topic review that shares
common words ("produto", "entrega", "recebimento") will score within this
band.

**Why does this happen?**
1. **Short text dominance:** Most Olist reviews are 3–10 words. E5-small's
   multilingual cross-lingual transfer was trained primarily on longer
   multilingual document pairs. Very short texts compress into a dense
   region of the embedding space where topic boundaries blur.
2. **Domain vocabulary overlap:** Portuguese e-commerce reviews share
   high-frequency words ("produto", "entrega", "recebimento") across
   ALL topics, making topic separation very dependent on rare discriminating
   terms that may not be well-represented in a 117M-parameter multilingual
   model.
3. **Informal language:** Short, colloquial phrases like *"demorou de mais
   pra entrega"* use non-standard Portuguese ("pra" instead of "para")
   that may not be well-represented in E5's multilingual training data
   (which skews toward formal web text).

---

### 11. MMR Reranking Effect

**File:** `reranking.py::mmr_rerank()`  
**Lambda:** 0.7 (relevance-weighted)

MMR selects for diversity among the top-50 dense-retrieved candidates.
Since the dense retriever already fails to separate on-topic from
off-topic reviews within those 50 candidates, MMR cannot improve recall
— it can only increase diversity among equally-wrong results.

**Finding:** MMR is correctly implemented but cannot compensate for
upstream retrieval failure.

---

### 12. Eval Set Size vs. Corpus Size

| | Value |
|---|---|
| Total indexed reviews | 5,019 |
| Avg expected per query | ~5.5 |
| Avg expected / total | **0.11%** |

The evaluation task requires retrieving 0.11% of the corpus. Even a
perfect semantic ranker would need very strong discrimination on short
informal Portuguese text to consistently find these 5–8 documents in
top-10 out of 5,019.

---

## Summary Table of Findings

| Component | Finding | Verdict |
|---|---|---|
| Evaluation labels | All 31 expected IDs exist in index | ✅ Correct |
| Query formulation | Thematically appropriate, correct language | ✅ Correct |
| E5 prefix convention | `query: ` / `passage: ` correctly applied | ✅ Correct |
| Preprocessing | NFKC + whitespace, non-destructive | ✅ Correct |
| Language detection | Metadata only, not a filter | ✅ Correct |
| Normalization | L2-normalized, `cosine = dot product` | ✅ Correct |
| Similarity metric | Cosine via normalized dot product | ✅ Correct |
| Structured filter | Correctly reduces candidate pool | ✅ Correct |
| Ranking direction | Descending by score | ✅ Correct |
| MMR reranking | Correctly implemented, diversifies top-K | ✅ Correct |
| E5-small discrimination | ~0.05 gap on-topic vs. off-topic — real, but not the dominant cause | ⚠️ Contributing (not primary) |
| **`EmbeddingCache` disk persistence** | **`save()`/`_load()` desync key→vector mapping for duplicate-text rows — see `STEP4A_VALIDATION.md` §0** | **❌ ACTUAL ROOT CAUSE** |
| Short review dominance | 62% of corpus < 10 chars | ❌ Contributing |
| No lexical fallback | BM25 absent (fixed in Step 4A) | ❌ Contributing |

---

## Diagnosis: Superseded — see `STEP4A_VALIDATION.md` §0

The "~80% intrinsic / ~20% architectural" split below was this document's
original conclusion and is **superseded**. A meaningful share of what was
attributed to "intrinsic" model weakness was actually an `EmbeddingCache`
disk-persistence bug corrupting the specific expected documents' cached
vectors (`STEP4A_VALIDATION.md` §0). With that fixed, dense E5-small's
corrected MRR is 0.333 — genuinely competitive with BM25's 0.333-0.389,
not a near-total failure. Kept below for the audit trail only:

**Originally-claimed intrinsic (~80%):** The Olist review corpus consists
overwhelmingly of very short, informal Portuguese text. E5-small lacks
sufficient density in this region of its embedding space to discriminate
between topically different 3–10-word reviews. E5-base and E5-large were
since evaluated (2026-08-28) and both score *below* E5-small on this eval
set — the "bigger model would help" hypothesis is not supported so far
(see `STEP4A_VALIDATION.md` §8), though the eval set is too small to be
conclusive either way.

**Originally-claimed architectural (~20%):** The absence of a lexical
(BM25) baseline meant exact keyword matches ("defeito", "atraso") were not
rewarded explicitly. Step 4A added BM25 + query expansion, which remains
the best single method post-fix (MRR=0.389). A Hybrid RRF combination was
also implemented and benchmarked — it underperforms both individual
methods even with corrected, genuinely-signal-bearing dense scores
(`STEP4A_VALIDATION.md` §4.2), so it is not recommended here.

---

## Recommended Remediation

1. **Implement BM25 lexical baseline** — provides exact-match signal
   independent of embedding quality.
2. **Hybrid RRF fusion** — combine BM25 + E5-small rankings to capture
   both lexical and semantic signal.
3. **Query expansion** — add controlled bilingual synonyms
   (e.g., delivery → entrega → atraso → demorou) without LLM.
4. **RETRIEVAL_INSUFFICIENT sentinel** — do not return arbitrary results
   when confidence is below a documented floor.
5. **Model comparison** — benchmark E5-base and E5-large to measure
   whether larger models close the discrimination gap on this corpus.

Full benchmark results: `reports/step4a_retrieval_benchmark.json`.
