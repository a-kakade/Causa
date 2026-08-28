# RAG Governance (Step 4)

Governs how the review-retrieval pipeline (`src/evidence/retrieval.py`,
`reranking.py`) may be queried, and the security posture review text is held
to throughout.

## 1. Structured-first retrieval mandate

**Never**: `semantic query → entire review corpus`.
**Always**: `structured filter → candidate reviews → semantic retrieval → rerank → top-K`.

`retrieval.retrieve()` enforces this as actual control flow, not convention:

1. `validate_structured_filters()` — reject anything not a governed KPI
   dimension or a recognized review-pipeline key.
2. `apply_structured_filters()` — narrow the vector index to candidate
   **positions** (never text, never vectors) by `structured_filters`,
   `time_range`, and clearance (seller-bearing rows excluded below `INTERNAL`,
   `BLOCKED` rows always excluded).
3. Semantic search (`FlatCosineIndex.search`) runs **only** over that
   candidate subset when a `semantic_query` is given — `test_retrieval.py`
   asserts `candidates_after_filter < len(index)` whenever a real filter
   narrows the query, i.e. the semantic step never sees the unfiltered index.
4. Results below `minimum_relevance` are dropped.
5. `reranking.py` (MMR, or a metadata-diversity fallback with no semantic
   query) picks the final top-K.
6. Each surviving row is wrapped into an `EvidenceResult` — PII redaction is
   applied at this exact step (§4).

## 2. `EvidenceQuery` / `EvidenceResult` contracts

`EvidenceQuery` (`schema.py`): `investigation_id`, `question`, `kpi_id`,
`time_range`, `dimensions`, `structured_filters`, `semantic_query`, `top_k`
(1-100), `minimum_relevance` (0-1), `requester_clearance`.

`structured_filters` keys are validated two ways in
`retrieval.validate_structured_filters`:

- **Governed KPI dimensions** (`month`, `category → product_category`,
  `seller`, `customer_state`, `seller_state`) are checked against
  `SemanticRegistry.get_dimension("revenue", dimension_name)` — the
  `revenue` contract is used as the reference because it is the one contract
  that supports every dimension a review can be filtered by (`avg_review_score`'s
  own contract explicitly refuses `product_category`/`seller`/`seller_state`
  as dimensions — this validation doesn't imply reviews are joined at
  revenue's grain, only that revenue's contract is the governed source of
  dimension-level security classifications). A requester below the
  dimension's `security_classification` gets `UnauthorizedFilterError`.
- **Review-pipeline-only keys** (`language`, `security_status`,
  `category_attribution_method`, `review_score_min`, `review_score_max`) are
  checked against an explicit `ALLOWED_REVIEW_FILTER_KEYS` whitelist, since
  they don't exist in `config/kpis.yaml`.

Anything else raises `UnsupportedFilterError`. This is the concrete
mechanism behind "do not allow a caller to bypass governed KPI dimensions."

`EvidenceResult`: `evidence_id`, `evidence_type`, `claim`, `content`,
`retrieval{rank,score,method}`, `source{review_id,order_id}`, `metadata`,
`evidence_tier`, `security`, `lineage`. Never a bare string — every result
carries retrieval provenance and a lineage trail back to
`data/processed/fact_reviews.parquet` and the raw CSV.

## 3. Security model

- `trust_level = UNTRUSTED_DATA` on every `CUSTOMER_REVIEW` evidence object,
  unconditionally — review text is never treated as instructions, regardless
  of its `security_status`.
- `security_status ∈ {SAFE, SUSPICIOUS, BLOCKED}` — a deterministic
  regex/keyword classification (`safety.py`), never an LLM judgment.
  `BLOCKED` is a **flag only**: no code path in this package deletes a
  review from `fact_reviews.parquet` or the vector index because of it;
  `retrieval.apply_structured_filters` simply excludes `BLOCKED` rows from
  normal query results by default.
- Access control (`access_control.py`) reuses the exact
  `PUBLIC_ANALYTICAL`/`INTERNAL`/`RESTRICTED` scale and rank ordering already
  established in `config/kpis.yaml`/`src/kpi/query_planner.py`. Restricted
  content is filtered by actually removing nodes/rows (never by hiding a
  display label), aggregate counts (`safe_node_count`/`safe_edge_count`) are
  computed *after* filtering, and `redact_error_message()` scrubs
  identifier-shaped tokens out of exception text before it reaches a caller
  below `INTERNAL`.
- `customer_id`/`customer_unique_id` are hardcoded to **never** appear in any
  node/edge attribute this fabric returns, at any clearance level — there is
  no legitimate consumer of this graph that needs them.

### Synthetic security fixtures (task §26)

`data/evidence/security_fixtures/prompt_injection_fixtures.json` holds 4
synthetic prompt-injection strings, kept fully outside `data/raw/` and
`data/processed/`. `tests/test_security.py` verifies: they are classified
`SUSPICIOUS`/`BLOCKED`, they never appear in the real review corpus, trust
level stays `UNTRUSTED_DATA`, and no code under `src/evidence/` contains an
`eval`/`exec`/`subprocess` call site (a static AST scan) — proving injection
text can never become an executed instruction.

## 4. PII detection and redaction

`pii.py` detects phone/email/URL/CEP-or-address via regex, plus a weak
capitalized-token name heuristic (no NER library is installed — documented
as over-flagging by design; see `docs/EVIDENCE_FABRIC.md` §7). Detection
only — `pii_detected`/`pii_types` are recorded on the `EvidenceObject`, but
the underlying text is never mutated.

**Redaction happens at retrieval, not at ingestion**: `retrieval.retrieve()`
calls `pii.redact_pii(text, pii_types)` when constructing each
`EvidenceResult.content`, replacing matched spans with
`[REDACTED_<TYPE>]`. The source `EvidenceObject.metadata["text"]` is never
touched — `test_retrieval.py::test_pii_redaction_applied_to_content_not_underlying_evidence`
asserts the underlying evidence's text is unchanged while the result's
content is redacted.

## 5. Reranking methodology

`reranking.mmr_rerank(vectors, scored_candidates, k, lambda_param=0.7)` —
standard Maximal Marginal Relevance:

```
mmr_score(c) = λ · relevance(c) − (1−λ) · max_{s ∈ selected} cosine_sim(c, s)
```

Greedy, deterministic (ties broken by original candidate order, never
randomly). `λ=1.0` degenerates to pure relevance order (tested explicitly).
When there's no `semantic_query` (nothing to compute pairwise similarity
from), `reranking.deterministic_metadata_diversity_rerank` round-robins
candidates across a metadata key (category) instead, so a purely structured
query still returns a diverse top-K rather than K near-duplicate rows.
Relevance stays the primary objective in both — diversity only breaks ties.

## 6. Retrieval evaluation methodology

**This is a small, manually curated engineering evaluation set — not a
statistically representative benchmark** (`data/evidence/eval/retrieval_eval_set.json`,
6 categories × 1 query each: delivery complaint, product quality complaint,
low satisfaction, positive experience, shipping delay, category-specific
complaint). Curated by keyword-anchored pre-filtering over the real
October-November 2017 corpus (e.g. `atras|demor` for delivery) and hand-picking
on-topic `review_row_id`s from the top hits.

`scripts/step4_retrieval_eval.py` computes Precision@5, Precision@10, MRR,
candidate counts before/after structured filtering, an irrelevant-retrieval-rate,
and latency per query, writing `reports/retrieval_evaluation.json`.

**Measured result (corrected 2026-08-28)**: mean P@5 = 0.067, mean P@10 =
0.033, mean MRR = 0.333, mean irrelevant-retrieval-rate = 0.97, mean
latency ≈ 57ms. The numbers originally recorded here (P@5=0.0, MRR=0.017)
turned out to be mostly an artifact of an `EmbeddingCache` disk-persistence
bug that silently swapped cached embeddings between reviews sharing
duplicate text, not a genuine `multilingual-e5-small` limitation — see
`STEP4A_VALIDATION.md` §0 for the root-cause writeup and fix. The
underlying observation that motivated the original investigation is still
real, just smaller than first measured: inspecting top-ranked results for
the delivery-complaint query still shows on-topic and generic
positive-sentiment reviews ("bom vendedor", "tudo certo recebi o produto")
landing within a similarly narrow cosine band (~0.84-0.92) — the model's
discriminative power genuinely is weaker on this corpus's very short,
informal text than on longer documents, it just isn't the near-total
failure the corrupted cache made it look like. Structured pre-filtering
(which the eval also reports — see `candidates_before_filter`/
`candidates_after_filter` per query) remains the primary mitigation this
prototype applies for candidate-pool size; it does not fully compensate
for semantic top-K imprecision on short text. This residual gap is
reported as a known limitation, not corrected by adjusting the eval set to
flatter the model.

## 7. Telemetry and zero-LLM-calls guarantee

Every `retrieval.retrieve()` call returns a `RetrievalTelemetry`:
`candidates_before_filter`, `candidates_after_filter`,
`vector_searches_performed`, `embedding_cache_hits/misses`,
`structured_filter_latency_ms`, `semantic_search_latency_ms`,
`reranking_latency_ms`, `total_latency_ms`, `estimated_embedding_cost_usd`
(always `0.0` — self-hosted model, no API calls), and `llm_calls_made`
(hardcoded `0`, asserted by `test_retrieval.py`).
