# Causa — Project Journey

A living log of the Causa build, step by step. Updated at the end of every step —
read this first if you're picking the project back up after a break. Each entry
links to that step's own validation document, which has the full detail; this
file is the map, not the territory.

**Standard held throughout:** every claim must trace back to the real raw Olist
data (`archive.zip` → `data/raw/olist/`), nothing fabricated or simulated. No step
has skipped ahead of what the prior step actually established.

---

## Where we are right now

**Step 4A complete, then corrected (2026-08-28).** Step 4 (Evidence Fabric) was
built and validated, but its retrieval evaluation revealed P@5≈0, P@10=0.017,
MRR=0.017 using multilingual-e5-small. Step 4A was a mandated deep-dive to
diagnose and fix that failure — without hiding or reclassifying it. That
diagnosis was itself revisited once a fresh HF token unblocked the remaining
Step 4A work (E5-base/large, cross-encoder reranking): comparing cached vs.
freshly re-encoded vectors exposed a real bug, not just an E5-small
limitation. Full writeup: `STEP4A_VALIDATION.md` §0.

**Actual root cause found 2026-08-28:** `EmbeddingCache.save()` persisted
orphaned vector rows left over from duplicate-text batches (427 of 5,019
reviews share identical short text, e.g. "Otimo produto"), while `_load()`
re-derives each key's array index positionally from the sorted keys list —
desyncing the key→vector mapping for most of the corpus on every disk
round-trip. `cache.get(key)` silently returned some *other* review's real
(but wrong) embedding instead of the requested one. Fixed in
`src/evidence/embeddings.py` (`put_many()`, `save()`); 2 new regression
tests added; the corrupted on-disk cache was rebuilt from scratch and
verified byte-identical to a fresh full-corpus re-encode.

**Step 4A findings (corrected):**
- Dense E5-small was never as broken as first measured: corrected MRR=0.333
  (was reported as 0.017 — the cache bug, not model weakness, explains most
  of that gap). BM25+expansion still wins overall, but by +17% MRR
  (0.389 vs. 0.333), not 19.6×.
- BM25 baseline implemented (MRR=0.389 with expansion, 0.9-1.0ms, <1MB memory)
  — still the recommended production retriever.
- Hybrid RRF implemented — still does NOT beat BM25-alone, even now that
  dense retrieval has genuine signal (a more robust finding than the
  original "noise dilutes signal" explanation, which assumed dense MRR=0).
- Query expansion adds +0.056 MRR with a governed bilingual synonym table.
- HF auth restored 2026-08-28: E5-base and E5-large were evaluated and both
  score *below* E5-small (MRR=0.190 vs. 0.333) — counter-intuitive, likely
  eval-set-size noise (6 queries), flagged as a hypothesis not a conclusion.
  Cross-encoder reranking (`amberoad/bert-multilingual-passage-reranking-msmarco`)
  ties E5-small's MRR at 450-500× the latency — not recommended either.
- RETRIEVAL_INSUFFICIENT sentinel implemented for the future Confidence Judge;
  its score floors were re-validated against the corrected numbers (no change
  needed).
- **Recommended production retriever: BM25 + query expansion (unchanged).**
- 547 tests pass (545 + 2 new regression tests), 0 regressions. Steps 2–3D
  untouched.

**Still no causal inference, LLM, agents, or frontend anywhere.**

---

## Timeline

| Step | What | Status | Key artifact |
|---|---|---|---|
| 1 | Raw data EDA + independent audit | ✅ Complete | [DATA_FOUNDATION_REPORT.md](DATA_FOUNDATION_REPORT.md) |
| 2 | Canonical data model + controlled cleaning | ✅ Complete | [STEP2_VALIDATION.md](STEP2_VALIDATION.md) |
| 3A | KPI semantic layer (definitions only) | ✅ Complete | [docs/KPI_SEMANTIC_LAYER.md](docs/KPI_SEMANTIC_LAYER.md) |
| 3B | Deterministic KPI computation engine | ✅ Complete | [STEP3B_VALIDATION.md](STEP3B_VALIDATION.md) |
| 3C | Materiality / anomaly detection engine | ✅ Complete | [STEP3C_VALIDATION.md](STEP3C_VALIDATION.md) |
| 3D | Driver decomposition engine (PVM + contribution) | ✅ Complete | [STEP3D_VALIDATION.md](STEP3D_VALIDATION.md) |
| 4 | Evidence Fabric (structured + unstructured RAG) | ✅ Complete | [STEP4_VALIDATION.md](STEP4_VALIDATION.md) |
| 4A | Retrieval failure analysis + BM25 + hybrid architecture | ✅ Complete | [STEP4A_VALIDATION.md](STEP4A_VALIDATION.md) |
| — | Causal inference, LLM, agents, recommendations, frontend | ⬜ Not started | — |

---

## Step 1 — Raw Data EDA + Repository/Data Foundation Audit

**Source data:** found and extracted `archive.zip` (the real Kaggle Olist
Brazilian E-Commerce dataset) into `data/raw/olist/` — 9 CSVs, 99,441 orders,
verified never modified since.

**What was built:** a first exploratory pass (`scripts/profile_olist.py`,
`kpi_temporal_eda.py`, `text_and_entity_eda.py`, `join_driver_anomaly_eda.py`,
notebook, `docs/EDA_REPORT.md` + 6 companion docs) followed by a **second,
independent audit** (`scripts/audit_raw_data.py`) that re-derived every headline
number from scratch rather than trusting the first pass — both agreed on every
recomputed figure, which is itself the finding worth remembering: the raw data
and both codebases are internally consistent.

**Headline findings that shaped everything after:**
- Order volume collapses at both edges of the raw date range (329 orders across
  all of 2016, 20 across Sept–Oct 2018) — later became the analytical-window
  decision in Step 2.
- Naively joining `orders ⋈ order_items ⋈ order_payments ⋈ order_reviews` before
  summing `price` inflates revenue (~4-4.5% depending on join shape) — became the
  anti-fan-out architecture in Step 2.
- `order_items.price` and `order_payments.payment_value` agree within 1 cent for
  99.61% of orders; the 0.39% gap concentrates in financed installment payments —
  became the CAUSA_REVENUE decision in Step 2.
- `order_reviews.review_id` is not a clean key (814 duplicates, 547 multi-review
  orders) — became the review-governance question resolved in Step 2.
- The dataset is pre-anonymized (no name/email/phone anywhere); 0 organic
  prompt-injection content found in review text.

Full detail: [DATA_FOUNDATION_REPORT.md](DATA_FOUNDATION_REPORT.md),
[REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md), [docs/EDA_REPORT.md](docs/EDA_REPORT.md).

## Step 2 — Canonical Data Model + Controlled Cleaning Layer

**What was built:** 10 canonical Parquet tables in `data/processed/` (3 dims, 4
facts at native grain, 3 explicit order-level aggregates), 5 build/analysis
scripts, 62 passing pytest tests, 6 new governance docs, raw data verified
untouched throughout (full clean rebuild reproduces identical output).

**Decisions made, each backed by a fresh quantitative pass (not copied from
Step 1):**
- **Analytical window: 2017-01 → 2018-08.** Derived by an explicit rule (<10% of
  median month's volume), cross-validated — 2018-09/10 turned out to be
  structurally incomplete (items coverage 6.25%/0%), not just low-volume.
- **CAUSA_REVENUE = `SUM(order_items.price)`**, never `payment_value`. The 381
  mismatches cluster almost perfectly by installment count (0 at 0 installments,
  rising with installments) — confirms financing interest, not a defect.
- **Review governance is use-case-specific**: `fact_reviews` keeps every raw row
  (for future retrieval); `agg_order_reviews.latest_review_score` (bias −0.073)
  is the order-level KPI default; `highest_review_score` was quantitatively
  disqualified (bias +0.376, cherry-picking).
- **Fan-out is structurally prevented**, not just documented — no fan-out-prone
  measure lives on `fact_orders`; `tests/test_fanout.py` proves the naive join
  inflates the total before proving the canonical path doesn't.
- **New finding**: 166 orders have `carrier_delivery_timestamp` before
  `purchase_timestamp` — investigated (121 within an hour, clock-skew; 2
  multi-day outliers), flagged `INVALID_SEQUENCE`, never silently dropped.
- **Geolocation excluded** from the canonical layer — `dim_customer`/`dim_seller`
  already carry clean state/city fields; geolocation has no usable key (26.18%
  exact duplicates).

Full detail: [STEP2_VALIDATION.md](STEP2_VALIDATION.md),
[docs/CANONICAL_DATA_MODEL.md](docs/CANONICAL_DATA_MODEL.md),
[docs/DATA_LINEAGE_V2.md](docs/DATA_LINEAGE_V2.md),
[docs/KPI_SEMANTICS_PREVIEW.md](docs/KPI_SEMANTICS_PREVIEW.md),
[docs/REVIEW_GOVERNANCE.md](docs/REVIEW_GOVERNANCE.md),
[docs/ANALYTICAL_WINDOW.md](docs/ANALYTICAL_WINDOW.md),
[docs/GEOLOCATION_DECISION.md](docs/GEOLOCATION_DECISION.md).

## Step 3A — KPI Semantic Layer

**What was built:** 10 governed KPI contracts (`config/kpis.yaml`) validated
against a JSON Schema (`schemas/kpi_contract.schema.json`) by a Python loader
(`src/kpi/semantic_registry.py`) that computes nothing — it only validates
structure and cross-contract governance rules. 30 new tests
(`tests/test_kpi_contracts.py`), 109 tests passing across the whole repo.

**The 10 KPIs:** Revenue, Orders, AOV, Average Delivery Days, Average Review
Score (primary) + Freight Revenue, Review Volume, On-Time Delivery Rate,
Quantity Sold, Repeat Purchase Rate (supporting).

**Decisions made:**
- **Dimension support is grain-checked per KPI, not assumed.** Item-grain KPIs
  (Revenue, Freight Revenue, Quantity Sold) safely support seller/product/category
  slicing (6/6 dimensions); order-grain KPIs (Orders, AOV, Delivery, Review Score,
  On-Time Rate) do NOT — an order can span multiple sellers/products (~9.86% of
  orders are multi-item), so those dimensions are explicitly marked unsupported
  with a documented reason rather than silently offered.
- **AOV's denominator is deliberately not the same population as the Orders
  KPI** — it's orders-with-item-data specifically, to avoid diluting AOV with
  revenue-less orders.
- **Average Review Score ships 3 explicit variants**, none silently
  interchangeable: order-level representative (default, latest-by-timestamp),
  order-level true average, and review-level average (no dedup).
- **Repeat Purchase Rate is grain-locked to `customer_unique_id`** — a governance
  test fails the build if `customer_id` is ever used instead.
- **Materiality is configuration only** (`implemented: false` on all 10, schema-
  enforced) — no anomaly engine exists yet; thresholds are informed defaults from
  Step 1's exploratory scan, not tuned.
- **Security**: every KPI value is `PUBLIC_ANALYTICAL`; `seller_id` is `INTERNAL`
  wherever it's a supported dimension; no contract exposes a raw customer
  identifier as a queryable dimension at all.

Full detail: [docs/KPI_SEMANTIC_LAYER.md](docs/KPI_SEMANTIC_LAYER.md),
[reports/kpi_semantic_validation.json](reports/kpi_semantic_validation.json).

## Step 3B — Deterministic KPI Computation Engine

**What was built:** `src/kpi/engine.py` (`KPIEngine`), `models.py`
(`KPIRequest`/`KPIResult`/`ComparisonResult`), `query_planner.py` (validates
every request against the Step 3A contract *before* touching data),
`cache.py` (deterministic hash-based computation cache). 122 new tests across
3 files; 231 tests pass repo-wide.

**Architecture**: `KPIRequest → SemanticRegistry → query_planner.plan()
(validation) → QueryPlan → KPIEngine._compute_<kpi_id>() → data/processed/*.parquet
→ KPIResult` — exactly the pipeline the task specified. Every result carries
full metadata (value, period, grain, dimensions, filters, sample_size,
coverage, data_quality, source, lineage, warnings) — never a bare number.

**Validated exactly, computed live (not hardcoded)**: Revenue Oct 2017 =
R$664,219.43, Nov 2017 = R$1,010,271.37, change = +R$346,051.94 (+52.1%);
Orders Oct = 4,631, Nov = 7,544 (+62.9%) — all reproduce from the canonical
Parquet tables via `KPIEngine.compute()`/`compare_periods()`.

**Decisions & findings:**
- **A real bug was found and fixed during this step**: dimension-grouping
  Revenue by `product_category` silently *undercounted* the total by
  R$14,115.98, because pandas' `groupby()` drops `NaN` group keys by default
  (610 products have no category). Fixed with `dropna=False`; a regression
  test (grouped results must sum to the ungrouped total) now guards this
  permanently.
- **Quantity Sold's "1 row = 1 unit" assumption was verified against real data
  before implementing**, per the task's explicit instruction not to fabricate
  it — confirmed a repeat-purchase-within-an-order produces 2 separate
  `order_item` rows with the same product and price, not a quantity field.
- **Dimension support is enforced exactly as Step 3A declared it**: item-grain
  KPIs (Revenue, Freight Revenue, Quantity Sold) support 6 dimensions;
  order-grain KPIs (Orders, AOV, Delivery, Review Score, On-Time Rate) support
  only 2 (month, customer_state) — item-grain dimensions raise
  `UnsupportedDimensionError` with the contract's own documented reason.
- **`repeat_purchase_rate`'s month/cohort dimension is explicitly refused**,
  not approximated — the contract itself documents no ready cohort query
  exists; the engine cites that rather than silently computing something
  wrong.
- **Comparison periods are pure arithmetic** — `ComparisonResult` carries no
  `is_anomaly`/`significant` field of any kind, verified by a test.

Full detail: [STEP3B_VALIDATION.md](STEP3B_VALIDATION.md),
[docs/KPI_COMPUTATION_ENGINE.md](docs/KPI_COMPUTATION_ENGINE.md),
[reports/step3b_validation.json](reports/step3b_validation.json).

## Step 3C — Materiality / Anomaly Detection Engine

**What was built:** `src/anomaly/` — `baseline.py` (6 methods: previous
period, rolling mean/median/std, EWMA, seasonal, plus an entity → category →
regional → global historical-sufficiency fallback ladder), `statistics.py`
(z-score, robust z-score/MAD, percentile — each with documented assumptions),
`materiality.py` (the decision model), `engine.py` (orchestrator). Answers
exactly one question: *"is this KPI movement sufficiently unusual and
materially important to justify launching an investigation?"* — never *why*.
81 new tests; 312 tests pass repo-wide.

**Decisions made:**
- **Materiality is a median of three independent evidence dimensions**
  (magnitude, statistical abnormality, business impact), each tiered
  NORMAL→CRITICAL against the KPI's own governed thresholds — not a product
  or a single threshold crossing. Requires at least two of three to agree
  before the verdict is elevated, so a KPI that swings +100% off a
  denominator of 1 is correctly held at WATCH, not CRITICAL.
- **Two independent, after-the-fact caps** (low baseline confidence, low
  current-period data quality) can only ever pull the verdict *down* to
  WATCH — logged with the specific number that triggered them, never hidden.
- **A sixth verdict, `BASELINE_DISAGREEMENT`**, fires when independent
  baseline methods (previous-period vs. rolling vs. seasonal) disagree by
  ≥2 severity tiers — the engine reports the conflict rather than silently
  picking a winner. Exempted when seasonal is the primary baseline, since a
  season-naive baseline is *expected* to diverge from a genuine seasonal peak.
- **A real 2-observation product** (real canonical data, not synthetic) is
  shown falling back from entity → category level, capped at MEDIUM
  confidence and WATCH verdict — never a high-confidence anomaly from 2 rows.
- **November 2017 revenue is classified CRITICAL** (z≈5.3), with no causal
  language anywhere in the result — verified by a regex scan over every
  string field of the serialized output, not just a documentation promise.
- **A design bug was found and fixed mid-build**: a fallback-level baseline's
  *value* is that level's own raw aggregate (e.g. a whole category's monthly
  total), not scaled to the entity's size — comparing a sparse product's
  R$153 sale against its category's R$30K aggregate produced a nonsensical
  −99% "movement." Fixed by attaching an explicit warning to every such
  result rather than presenting the coarse number as precise.

Full detail: [STEP3C_VALIDATION.md](STEP3C_VALIDATION.md),
[docs/MATERIALITY_ENGINE.md](docs/MATERIALITY_ENGINE.md),
[reports/step3c_validation.json](reports/step3c_validation.json).

## Step 3D — Driver Decomposition Engine

**What was built:** `src/drivers/` — `pvm.py` (Revenue = Price × Volume ×
Mix bridge), `contribution.py` (additive category/seller/geographic
decomposition), `ranking.py` (deterministic, absolute-contribution-based),
`engine.py` (orchestrator + a reconciliation guard that raises rather than
returns a non-reconciling result). Answers exactly one question: *"which
measurable factors mathematically account for this KPI movement?"* — never
*why*. 42 new tests; 354 tests pass repo-wide.

**Validated exactly, computed live**: October→November 2017 Revenue
decomposes to Volume +R$417,227.65, Price +R$4,674.63, Mix −R$75,850.34,
checksum error 0.0 — reproducing Step 1's independently-derived figures from
the canonical layer instead of raw CSVs. Category, seller, customer_state,
and seller_state contributions all reconcile exactly to the same
+R$346,051.94 total, computed independently of each other.

**Decisions made:**
- **Mix is a residual by construction** (`ΔRevenue − Volume − Price`), which
  is what makes the bridge reconcile *exactly* rather than approximately.
- **A documented, deliberate quirk kept bit-for-bit compatible with the
  validated numbers**: a category with no prior-period sales gets an implicit
  R$0 baseline price, so its entire revenue lands in "price effect," not
  "mix" — counter-intuitive, but changing it would change the required
  October→November 2017 result, so it's disclosed rather than "fixed."
- **Seller identity is clearance-gated** (`INTERNAL`) — omitted by default
  with a logged warning, hard error (`UnauthorizedSegmentError`) if
  explicitly requested without clearance.
- **`history_periods`/`confidence` are kept strictly separate from
  `contribution`** — a real November 2017 seller with zero prior history
  still ranks #2 by dollar contribution (+R$14,047.70) while correctly
  flagged `MEDIUM`, not `HIGH`, confidence.
- **Concurrent KPI movements** (Orders, AOV, Freight, Delivery, Review Score)
  are computed for the same period pair via the unmodified Step 3B engine and
  reported as plain arithmetic — never combined into a conclusion; this is
  the deterministic evidence package a future investigation layer would
  consume, not a finding in itself.
- **A real bug was found and fixed mid-build**: the validation script's own
  report-generation helper used a truthy short-circuit
  (`percentage_change and round(...)`) instead of an explicit `is None`
  check, silently hiding a valid `share_of_total_movement` for every
  brand-new entity (whose `percentage_change` is legitimately `None`).

Full detail: [STEP3D_VALIDATION.md](STEP3D_VALIDATION.md),
[docs/DRIVER_DECOMPOSITION.md](docs/DRIVER_DECOMPOSITION.md),
[reports/step3d_validation.json](reports/step3d_validation.json).

---

## Step 4 — Evidence Fabric (Structured + Unstructured RAG)

**What was built:** `src/evidence/` — full Evidence Fabric over the
October-November 2017 review corpus. Schema (`schema.py`, Pydantic strict
mode), structured adapter (`structured_adapter.py` — converts Step 3B/3C/3D
outputs into `EvidenceObject`s with zero pandas in the module), review
ingestion pipeline (`review_ingestion.py` — NFKC normalization, category
attribution with 4 confidence levels), language/PII/safety detection,
embedding (`embeddings.py` — E5-small, disk cache), vector index
(`vector_index.py` — FlatCosineIndex, brute-force cosine, exact), retrieval
(`retrieval.py` — structured-first mandatory pipeline, MMR diversity
reranking), evidence graph (`graph.py` — NetworkX, 39 nodes/29 edges),
access control (`access_control.py` — 3-level clearance). 130 new tests
across 9 files; 508 total pass.

**Findings:** All structured evidence (KPI movements, PVM, anomaly,
segments) reproduced the exact Step 3B/3C/3D numbers. 56 EvidenceObjects
built for the November 2017 package. **But retrieval metrics revealed:**
P@5=0, P@10=0.017, MRR=0.017 — honestly disclosed, not hidden. (Corrected
2026-08-28: mostly an `EmbeddingCache` bug, not model weakness — real
corrected numbers are P@5=0.067, MRR=0.333. See Step 4A below and
`STEP4A_VALIDATION.md` §0.)

Full detail: [STEP4_VALIDATION.md](STEP4_VALIDATION.md),
[docs/EVIDENCE_FABRIC.md](docs/EVIDENCE_FABRIC.md),
[docs/RAG_GOVERNANCE.md](docs/RAG_GOVERNANCE.md).

## Step 4A — Retrieval Failure Analysis and Optimization

**Trigger:** P@5≈0 and P@10=0.017 on the engineering eval set could not
be accepted as-is. Step 4A was a mandated diagnostic and remediation pass.

**What was found (2026-08-27, later corrected — see below):** All 10
diagnostic axes were audited. Believed root cause at the time: E5-small
cosine similarity gap between on-topic and off-topic short Portuguese
reviews is only ~0.05. For "atraso na entrega, demora" (delivery query),
the best on-topic score (0.904) is barely above off-topic generic reviews
(0.844-0.87). With 5,019 candidates and only 5 expected documents, this
gap looked insufficient. All 31 expected eval row_ids ARE in the index (0
missing). Every other pipeline component (prefix convention, normalization,
similarity direction, candidate restriction, ranking direction) was
verified correct.

**Corrected 2026-08-28:** that diagnosis was wrong. The actual root cause
was an `EmbeddingCache` disk-persistence bug — `save()` wrote orphaned
vector rows left over from duplicate-text batches (427 of 5,019 reviews
share identical short text), while `_load()` re-derives each key's index
positionally, desyncing the key→vector mapping on every reload for most of
the corpus. `cache.get(key)` silently returned a *different* review's real
embedding. Found by comparing cached vs. freshly re-encoded vectors row by
row while unblocking the E5-base/large/cross-encoder work below with a
fresh HF token. Fixed in `src/evidence/embeddings.py`; full writeup in
`STEP4A_VALIDATION.md` §0. The ~0.05 discrimination gap above is real (and
re-confirmed post-fix) but was never the dominant cause of the eval set's
near-zero score.

**What was built:**
- `src/evidence/bm25_retriever.py` — BM25+ index (k1=1.5, b=0.75, delta=1.0),
  Portuguese-aware tokenizer, bilingual stop-words, governed query expansion
  vocabulary (no LLM). Build: 36ms, query: 0.9ms.
- `src/evidence/retriever_interface.py` — EmbeddingProvider and Retriever
  protocols (injected, never hardcoded), RETRIEVAL_INSUFFICIENT sentinel.
- `src/evidence/dense_retriever.py` — DenseRetriever with E5EmbeddingProvider
  (model injected, supports E5-small/base/large via from_model_name()).
- `src/evidence/hybrid_retriever.py` — HybridRetriever (RRF, k=60),
  LexicalRetriever wrapper.
- `scripts/step4a_retrieval_benchmark.py` — full benchmark script.
- `tests/test_bm25.py` — 37 new tests.
- `STEP4_RETRIEVAL_DIAGNOSTIC.md` — concrete per-component audit.
- `STEP4A_VALIDATION.md` — this step's validation document.

**Benchmark results (6-query eval set, Oct-Nov 2017 corpus, corrected 2026-08-28
after the cache fix):**

| Method | P@5 | P@10 | MRR | Latency |
|---|---|---|---|---|
| Dense E5-small | 0.067 | 0.033 | 0.333 | ~1,087ms cold / ~20ms warm |
| Dense E5-base | 0.033 | 0.050 | 0.190 | ~28ms |
| Dense E5-large | 0.033 | 0.033 | 0.190 | ~45ms |
| **BM25** | **0.133** | **0.083** | 0.333 | **0.9ms** |
| **BM25 + expansion** | **0.133** | 0.083 | **0.389** | 1.0ms |
| Hybrid RRF | 0.067 | 0.083 | 0.296 | 14.9ms |
| Hybrid RRF + expand | 0.033 | 0.083 | 0.230 | 14.0ms |
| BM25+expand → CE rerank | 0.067 | 0.050 | 0.333 | 459.6ms |

*(Originally reported, superseded: "E5-small (Step 4)" 0.000/0.017/0.017 at
1,284ms and "Dense E5-small" 0.000/0.000/0.000 — both were reading a
corrupted embedding cache, see `STEP4A_VALIDATION.md` §0.)*

**Key finding (corrected):** BM25+expansion (MRR=0.389) outperforms dense
E5-small by +17%, not 22× — dense retrieval was never as broken as first
measured. Hybrid RRF still does NOT beat BM25-alone, even now that dense
has genuine signal — a more robust finding than the original explanation
assumed. E5-base/E5-large both score *below* E5-small (unexpected; may be
eval-set-size noise). Cross-encoder reranking ties E5-small's MRR at
450-500× the latency. **Recommended production retriever: BM25 + query
expansion (unchanged).**

547 tests pass (37 new in Step 4A + 2 new regression tests for the cache
bug, 0 regressions). Steps 2–3D unchanged.

Full detail: [STEP4A_VALIDATION.md](STEP4A_VALIDATION.md),
[STEP4_RETRIEVAL_DIAGNOSTIC.md](STEP4_RETRIEVAL_DIAGNOSTIC.md),
[reports/step4a_retrieval_benchmark.json](reports/step4a_retrieval_benchmark.json).

---

## Running list of things intentionally left undone (don't rediscover these as surprises)

- No profit/margin KPI — no cost-of-goods field exists anywhere in the source data.
- No marketing-attribution KPI — no channel/spend/campaign data exists.
- No true customer LTV — only 3.12% of unique customers repeat, and there's no
  margin data to net against revenue.
- Geolocation is not in the canonical layer (see Step 2).
- `order_status` default filtering for "recognized revenue" is an open question,
  deliberately exposed as a filter rather than decided (see Step 3A).
- No causal inference, RAG, LLM integration, agents, recommendations, or
  frontend exist anywhere in this repository yet.
- The KPI engine (Step 3B) cannot compute `repeat_purchase_rate` by cohort
  month (no ready query, by design) or `avg_review_score`'s `review_level_average`
  variant grouped by dimension (not built) — both raise explicit errors
  rather than approximate an answer.
- PVM decomposition (Step 3D) is Revenue-only — Price × Volume × Mix is only
  meaningful for a SUM-of-price KPI; generalizing it to other KPIs is future
  work.
- Neither the anomaly engine (3C) nor the driver decomposition engine (3D) has
  been wired *into* each other or into a single "investigate this movement"
  entry point yet — each is invoked independently today.

## How to pick this back up

1. Read this file top to bottom.
2. Read the most recent step's own validation doc in full (currently
   [STEP3D_VALIDATION.md](STEP3D_VALIDATION.md)).
3. Reproduce the current state if needed:
   ```bash
   python scripts/step2_04_build_canonical.py     # rebuild data/processed/
   python -m pytest tests/ scripts/test_profile_olist.py -q   # should show 354 passed
   python scripts/step3a_validate_semantic_layer.py
   python scripts/step3b_validate_engine.py        # Nov 2017 KPI numbers should match exactly
   python scripts/step3c_validate_engine.py        # Nov 2017 anomaly verdict should be CRITICAL
   python scripts/step3d_validate_engine.py        # Nov 2017 PVM numbers should match exactly
   ```
4. Update this file's "Where we are right now" section and add a new entry to
   the Timeline table at the end of whatever step comes next.
