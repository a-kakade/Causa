# STEP 4 VALIDATION — Causa Evidence Fabric

Every number in this document is computed live via the real Step 3B
(`kpi.engine.KPIEngine`), Step 3C (`anomaly.engine.detect`), and Step 3D
(`drivers.engine.decompose`) engines, converted to evidence objects by
`src/evidence/structured_adapter.py`, plus a real review pipeline
(`src/evidence/review_ingestion.py`, `embeddings.py`, `vector_index.py`)
over `data/processed/fact_reviews.parquet` — via
`scripts/step4_validate_engine.py` and `scripts/step4_retrieval_eval.py`.
None are hardcoded. Full machine-readable output:
`reports/step4_validation.json`, `reports/retrieval_evaluation.json`.
Architecture: `docs/EVIDENCE_FABRIC.md`, `docs/EVIDENCE_GRAPH.md`,
`docs/RAG_GOVERNANCE.md`.

Reproduce:

```bash
.venv/bin/python scripts/step4_validate_engine.py
.venv/bin/python scripts/step4_retrieval_eval.py
```

---

## 1. Evidence taxonomy

`T1_DESCRIPTIVE`, `T2_ARITHMETIC`, `T3_STATISTICAL` are populated.
`T4_CAUSAL`, `T5_EXPERIMENTAL` are declared for extensibility and never
instantiated — enforced by `evidence.models.POPULATED_IN_STEP4`, checked at
construction time by every adapter function. See `docs/EVIDENCE_FABRIC.md` §2.

## 2. Evidence schema

Strict Pydantic `EvidenceObject` (`extra="forbid"`), `Claim`,
`EvidenceQuery`, `EvidenceResult` in `src/evidence/schema.py`. Causal
language is rejected in `claim`/`Claim.text` at construction time (same
wordlist Steps 3C/3D's tests already scan for). `metadata`/`dimensions` are
bounded to flat primitive dicts. 35 tests in `tests/test_evidence_schema.py`.

## 3. Structured evidence integration — exact Step 3B/3C/3D reproduction

| Metric | Computed % change | Required % change | Match |
|---|---|---|---|
| Revenue | +52.10% | +52.1% | ✅ |
| Orders | +62.90% | +62.9% | ✅ |
| AOV | -6.75% | -6.75% | ✅ |
| Freight Revenue | +60.69% | +60.69% | ✅ |
| Avg Delivery Days | +27.87% | +27.87% | ✅ |
| Avg Review Score | -5.16% | -5.16% | ✅ |

Revenue absolute change: **R$346,051.94** (computed via
`KPIEngine.compare_periods` → `structured_adapter.comparison_result_to_evidence`),
exact match.

PVM (via `structured_adapter.driver_decomposition_result_to_evidence_bundle`):

| Driver | Computed | Required | Match |
|---|---|---|---|
| Volume | +417,227.65 | +417,227.65 | ✅ |
| Price | +4,674.63 | +4,674.63 | ✅ |
| Mix | -75,850.34 | -75,850.34 | ✅ |

Materiality (`anomaly_result_to_evidence`): verdict **CRITICAL** (expected
one of MATERIAL/CRITICAL) ✅.

**`all_required_values_match: true`** — every value above was independently
verified against `reports/step4_validation.json`.

56 structured `EvidenceObject`s were produced for the November 2017 package:
6 `KPI_MOVEMENT`, 2 `ANOMALY_SIGNAL`/`STATISTICAL_RESULT`, 3
`DRIVER_CONTRIBUTION`, 40 `SEGMENT_CONTRIBUTION` (4 dimensions × 10 ranked
segments), 5 `CONCURRENT_KPI`.

`structured_adapter.py` never imports pandas and never touches
`data/processed/*.parquet` directly — verified by an AST source scan
(`test_structured_adapter.py::test_adapter_module_has_no_pandas_import`).

## 4. Review corpus statistics

October-November 2017 investigation window (the scope used by the review
pipeline, tests, and the November package — see `docs/EVIDENCE_FABRIC.md` §6):

- Total review rows: **12,160** (7,534 November, 4,626 October)
- Rows with non-empty normalized text: **5,019**
- `category_attribution_method` distribution: `single_item_order` ~89%,
  `single_category_order` ~8%, `multi_item_order_ambiguous` ~1.5%,
  `no_items_on_order` ~0.8% (consistent with the fan-out rate documented in
  `config/kpis.yaml`)

## 5. Language distribution

| Language | Count |
|---|---|
| PT | 4,241 |
| UNKNOWN (text < 10 chars) | 7,519 |
| OTHER | 374 |
| EN | 26 |

(counts over all 12,160 review evidence objects; `UNKNOWN` dominates because
most reviews in this corpus have no text at all or very short text — median
review has no comment, per Step 1's finding that only 41.3% of reviews carry
`review_comment_message`.)

## 6. PII / security results

- Reviews flagged `pii_detected=True`: **577 / 12,160 (4.7%)** — mostly the
  conservative capitalized-token name heuristic (no NER library installed;
  see `docs/EVIDENCE_FABRIC.md` §7 for the documented "targaryen/lannister/
  stark" false-positive pattern).
- `security_status` distribution: **12,160 SAFE, 0 SUSPICIOUS, 0 BLOCKED**
  in the real October-November 2017 corpus. The 4 synthetic prompt-injection
  fixtures (`data/evidence/security_fixtures/prompt_injection_fixtures.json`,
  never merged into the real corpus) all classify `BLOCKED` — verified in
  `tests/test_security.py`.
- No `eval`/`exec`/`subprocess` call site exists anywhere under
  `src/evidence/` (static AST scan).

## 7. Embedding model

`intfloat/multilingual-e5-small` via `sentence-transformers`, pinned to
Hugging Face revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`
(`config/embedding.yaml`), 384 dimensions, `"query: "`/`"passage: "`
prefixes. This environment's cached HF auth token is expired, so every Hub
call in `embeddings.py` passes `token=False` for anonymous access to this
public model. Disk cache: `data/evidence/embedding_cache/reviews_e5_small_v1.npz`,
keyed by `sha256(normalized_text|model|embedding_version)`.

## 8. Vector index

Numpy brute-force cosine-similarity flat index (`FlatCosineIndex`) — not
FAISS (acceptable per spec, not mandatory; the ~5,000-vector corpus makes
brute force fast and exact). Index is rebuildable deterministically from
`data/processed/fact_reviews.parquet`; every vector maps to
`review_row_id`/`review_id`/`order_id`/`month`/`category`/`seller`/
`customer_state`/`seller_state`/`review_score`/`language`/`security_status`.
Not the source of truth.

## 9. Retrieval architecture

Structured-first, mandatory: `validate_structured_filters` →
`apply_structured_filters` (candidate positions only) → semantic search
restricted to that subset → `minimum_relevance` cutoff → `reranking.py`
(MMR or metadata-diversity) → `EvidenceResult` (with PII redaction applied
here, never on the underlying evidence). Governed-dimension validation
reuses `SemanticRegistry`/`CLEARANCE_RANK`. See `docs/RAG_GOVERNANCE.md`.

## 10. Retrieval evaluation

6-category, manually curated engineering evaluation set
(`data/evidence/eval/retrieval_eval_set.json`) — **explicitly not a
statistical benchmark**.

| Metric | Value |
|---|---|
| Mean Precision@5 | 0.067 |
| Mean Precision@10 | 0.033 |
| Mean MRR | 0.333 |
| Mean irrelevant-retrieval-rate | 0.967 |
| Mean latency | ~57ms |

**Update (2026-08-28, Step 4A follow-up):** the numbers originally recorded
here (P@5=0.0, MRR=0.017) were an artifact of a disk-persistence bug in
`EmbeddingCache`, not a genuine E5-small limitation — see
`STEP4A_VALIDATION.md` §1 for the full root-cause writeup and
`src/evidence/embeddings.py`'s `EmbeddingCache.save()`/`put_many()` for the
fix. With the corrected cache, dense retrieval still trails BM25+expansion
(MRR 0.333 vs. 0.389 — see `STEP4A_VALIDATION.md`), but the earlier
"E5-small essentially fails on this corpus" framing was wrong: 2 of 6
queries (`pq1`, `pe1`) now retrieve their top relevant review at rank 1
(MRR=1.0). The residual gap is real (short informal PT text remains hard),
just far smaller than first measured. Structured pre-filtering (reported
per-query as `candidates_before_filter`/`candidates_after_filter` in
`reports/retrieval_evaluation.json`) remains the primary mitigation for
candidate-pool size. See `docs/RAG_GOVERNANCE.md` §6 for the full
methodology and worked example.

## 11. Evidence graph

`networkx.MultiDiGraph`. Real November 2017 build: **39 nodes, 29 edges**;
node types `{CONFIDENCE, DRIVER, EVIDENCE, INVESTIGATION, KPI, MOVEMENT}`;
relationship types `{EXPLAINED_BY, HAS_CONFIDENCE, HAS_MOVEMENT, SUPPORTED_BY}`.
Revenue's `KPI_MOVEMENT` node has exactly 3 `EXPLAINED_BY` edges (volume,
price, mix); the delivery movement node has `SUPPORTED_BY` edges to 5
sampled November delivery-related review evidence nodes. See
`docs/EVIDENCE_GRAPH.md` §2 for the full worked diagram.

## 12. Contradiction representation

Real two-proportion z-test comparing low-score (`review_score<=2`) rates,
October vs. November 2017, run for all 9 top revenue-mover product
categories with sufficient sample (n≥15 both periods). **Result: all 9
showed the low-score rate increasing** (z-scores 0.62-4.46) — no
`CONTRADICTS` edge was produced in the real build, because none of the
actual top movers disagreed with the "delivery got worse, satisfaction got
worse" pattern. The mechanism itself is proven on real data in
`tests/test_graph.py` using the `electronics` category (present in the
corpus, not a top-10 revenue mover), whose low-score rate genuinely
*decreased* (18.2% → 15.3%, z=-0.50) — a real, non-fabricated contradiction
case. See `docs/EVIDENCE_GRAPH.md` §3.

## 13. Access control

Reuses `PUBLIC_ANALYTICAL`/`INTERNAL`/`RESTRICTED` and `CLEARANCE_RANK` from
the existing Step 3A/3B/3D convention. `access_control.filter_graph` removes
unauthorized nodes/edges (not just labels), strips `seller`/`seller_id`
attributes below `INTERNAL`, and unconditionally strips
`customer_id`/`customer_unique_id` at every clearance level.
`safe_node_count`/`safe_edge_count` compute counts *after* filtering.
`redact_error_message` scrubs identifier-shaped tokens from exception text.
17 tests in `tests/test_access_control.py`.

## 14. Traceability demonstration

Full chain reconstructed and verified in `tests/test_traceability.py`:
`evidence_id → review_id/order_id (on the EvidenceObject) → canonical
fact_reviews.parquet row (matched on review_id+order_id, review_score
cross-checked) → raw olist_order_reviews_dataset.csv row (review_score
cross-checked again)`. Structured evidence traces through its
`SemanticRegistry.get_lineage_chain(kpi_id)` chain exactly (byte-for-byte
equality asserted). Two independent builds of the same evidence produce
identical `evidence_id`s (reproducibility).

## 15. November 2017 evidence package

`investigation_id = "november_2017_revenue"`. Built by
`evidence.engine.build_november_2017_evidence_package`:

- **Structured**: revenue/orders/AOV/freight/delivery/review movements, PVM
  (volume/price/mix), segment contributions (product_category/seller/
  customer_state/seller_state, top 10 each), materiality/anomaly signal for
  revenue.
- **Unstructured**: 4 named retrieval subsets, each with 10 results —
  `delivery_related` (semantic query, INTERNAL clearance), `low_score`
  (structured filter `review_score_max<=2`), `category_specific` (structured
  filter on the top revenue-mover category, `bed_bath_table`),
  `product_quality` (semantic query for defect/quality complaints).
- **Graph**: the full worked example from §11, plus 9 real contradiction
  checks from §12.

Build time: **~53 seconds** (dominated by `langdetect` over ~5,000
text-bearing reviews and E5 embedding of the same set; embedding results are
cached on disk for subsequent runs).

## 16. Latency and cost

Per-query retrieval telemetry (`reports/step4_validation.json::retrieval`):
structured-filter latency sub-millisecond to a few ms; semantic search
latency ranges ~4ms (structured-filter-only fallback) to a few hundred ms
(semantic query, model already warm); `estimated_embedding_cost_usd: 0.0`
throughout (self-hosted model, zero API calls); `llm_calls_made: 0` on every
single result, structured and unstructured.

## 17. Tests

130 tests across the 9 required files, all passing:

| File | Tests |
|---|---|
| `test_evidence_schema.py` | 35 |
| `test_structured_adapter.py` | 12 |
| `test_review_pipeline.py` | 18 |
| `test_security.py` | 11 |
| `test_retrieval.py` | 12 |
| `test_reranking.py` | 8 |
| `test_graph.py` | 12 |
| `test_access_control.py` | 17 |
| `test_traceability.py` | 5 |

All 508 tests in the full repository suite pass (`.venv/bin/python -m pytest
tests/ -q`), confirming zero regressions against Steps 2/3A/3B/3C/3D.

## 18. Known limitations

- `FreshnessInfo.data_availability_time` is `None` everywhere — canonical
  build date isn't tracked per-row today; documented rather than faked.
- PII name detection is a weak capitalized-token heuristic (no NER library
  installed); documented as intentionally over-flagging.
- Retrieval precision on this corpus is measurably weak with
  `multilingual-e5-small` on very short, informal review text (§10) — an
  honestly disclosed, not hidden, characteristic of this prototype.
- The review-pipeline test/production scope (October-November 2017,
  ~12K rows) is narrower than the full 99,224-row historical corpus, chosen
  deliberately for build-time reasons and because it is exactly the
  investigation's own scope; a full-corpus build is supported by
  `evidence.engine.build_review_index(canonical, months=...)` but was not
  run for this validation.
- The contradiction check in the real November package found no
  disagreement among the actual top revenue-mover categories (§12) — this
  is a real result, not a failure of the mechanism (demonstrated separately
  in `tests/test_graph.py`).

---

## STOP CONDITION MET

No multi-agent orchestration, hypothesis/causal/action/persona agents, final
narratives, recommendations, or frontend exist anywhere in `src/evidence/`.
Every structured evidence figure traces to the exact Step 3B/3C/3D engines
already validated in prior steps, computed live with zero recomputation
(machine-verified by an AST scan). Every review evidence object is
`trust_level=UNTRUSTED_DATA`, never executed as instructions, with PII
redaction happening only at the retrieval layer. Zero LLM calls exist
anywhere in this package (`llm_calls_made=0` on every telemetry record). The
November 2017 investigation's KPI movements, PVM, materiality verdict, and
segment contributions all reproduce the required Step 3B/3C/3D values
exactly.

**Step 4 is complete. Multi-agent orchestration, causal inference, action
recommendations, and final narratives have not been started.**
