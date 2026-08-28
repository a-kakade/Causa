# Evidence Fabric (Step 4)

## 1. Purpose and scope boundary

The Evidence Fabric is the governed boundary between Causa's deterministic
analytics (Steps 1-3D) and any future agentic/GenAI reasoning layer (Step 5+).
Its job is to **collect, normalize, secure, retrieve, structure, link, and
trace evidence** — nothing more.

This module NEVER:

- generates final business conclusions or executive narratives
- infers root causes or performs causal inference
- recommends actions
- decides whether a hypothesis is true
- lets an LLM override deterministic evidence
- lets review text execute as instructions
- calls an LLM at any point (zero LLM calls anywhere in `src/evidence/`)

Everything a future agent can cite must trace back to a governed
`EvidenceObject` — never straight to raw data, and never to an invented
number.

## 2. Evidence taxonomy

| Tier | Meaning | Populated in Step 4? |
|---|---|---|
| `T1_DESCRIPTIVE` | Observed movement or association | Yes |
| `T2_ARITHMETIC` | Deterministic mathematical decomposition | Yes |
| `T3_STATISTICAL` | Statistical/anomaly evidence | Yes |
| `T4_CAUSAL` | Validated causal inference | No — reserved |
| `T5_EXPERIMENTAL` | Experimental evidence | No — reserved |

Enforcement is mechanical, not just documentation: `evidence.models.POPULATED_IN_STEP4`
is a frozenset every adapter function checks before constructing an
`EvidenceObject` (`structured_adapter._assert_populated`). PVM/segment
contributions are always `T2_ARITHMETIC` — never labeled causal, per task
instructions.

## 3. Evidence types

`KPI_OBSERVATION`, `KPI_MOVEMENT`, `ANOMALY_SIGNAL`, `DRIVER_CONTRIBUTION`,
`SEGMENT_CONTRIBUTION`, `CONCURRENT_KPI`, `STATISTICAL_RESULT`,
`CUSTOMER_REVIEW` are populated. `EXTERNAL_CONTEXT`, `BUSINESS_RULE`,
`CAUSAL_RESULT`, `ACTION_RESULT` are declared for taxonomy extensibility but
never instantiated — no fake evidence was manufactured to fill them.

## 4. `EvidenceObject` schema

Defined in `src/evidence/schema.py` as a strict Pydantic model
(`model_config = ConfigDict(extra="forbid")`): `evidence_id`, `evidence_type`,
`evidence_tier`, `claim`, `value{value,unit}`, `time{start,end}`,
`dimensions`, `confidence`, `source{system,component,version}`, `lineage[]`,
`freshness{event_time,data_availability_time,processing_time,is_historical}`,
`quality{completeness,freshness,source_reliability,coverage,
historical_sufficiency,retrieval_quality}`,
`security{classification,trust_level,security_status,pii_detected,
pii_types,redaction_status}`, `relationships[]`, `metadata`, `created_at`.

Two design decisions worth calling out:

- **`claim` and `Claim.text` reject causal language** via a `field_validator`
  reusing the exact wordlist `tests/test_anomaly_engine.py` and
  `tests/test_driver_engine.py` already scan fixtures for. This makes "no
  causal claims" a construction-time guarantee, not just a test.
- **`metadata`/`dimensions` are bounded to flat dicts of primitives.**
  `extra="forbid"` only protects the top-level object; without this bound,
  `metadata` would be an escape hatch for smuggling an unvalidated nested
  object past the strict schema.

`evidence_id` is a deterministic content hash
(`"ev_" + sha256(canonical_json(...))[:16]`), computed in
`structured_adapter.py`/`review_ingestion.py` (not `schema.py`) — rerunning
an adapter on identical input reproduces identical IDs.

## 5. Structured evidence adapters — no recomputation

`src/evidence/structured_adapter.py` converts **already-computed** Step 3B/3C/3D
result objects (`KPIResult`, `ComparisonResult`, `AnomalyResult`,
`DriverDecompositionResult`) into `EvidenceObject`s. It never imports pandas,
never reads `data/processed/*.parquet`, and never calls `kpi.query_planner`
— enforced by an AST source-scan test
(`test_structured_adapter.py::test_adapter_module_has_no_pandas_import`).
Lineage/source/confidence are copied or trivially mapped from the source
dataclass's own fields; the one exception is `AnomalyResult`, which carries
no single top-level `.lineage` list of its own, so `anomaly_result_to_evidence`
assembles a short lineage trail from `baseline.baseline_method` and a pointer
back to the corresponding `KPI_OBSERVATION` evidence — documented in that
function's docstring as the one place this module builds rather than copies
lineage.

Tier assignment is a fixed lookup table
(`evidence.models.TIER_FOR_EVIDENCE_TYPE`): KPI observations/movements/
concurrent-KPI/review evidence are `T1_DESCRIPTIVE`; driver/segment
contributions are `T2_ARITHMETIC`; anomaly signal/statistical result are
`T3_STATISTICAL`.

## 6. Review pipeline

```
REVIEW TEXT → normalize → language detect → PII detect → prompt-injection
check → safety classify → embed → vector index → metadata filter →
semantic search → evidence object
```

Every stage is deterministic/statistical/regex-based — zero LLM calls
(`RetrievalTelemetry.llm_calls_made` is a hardcoded `0`, asserted by tests).

- **`review_ingestion.py`** — `normalize_review_row` concatenates
  title+message, strips/collapses whitespace, NFKC-normalizes; the original
  text is kept as `raw_text` alongside the normalized `text`, and the
  canonical `fact_reviews.parquet` file is never written to.
- **`language.py`** — `langdetect` (already a repo dependency), seeded
  deterministically (`DetectorFactory.seed = 0`), buckets into
  PT/EN/OTHER/UNKNOWN with a confidence; texts under 10 characters are
  honestly reported UNKNOWN rather than guessed. This is a *different*
  concern from the embedding model's own multilinguality — `langdetect`
  fills the `language` metadata field; `multilingual-e5-small`'s
  multilinguality is what avoids a separate translation step before
  semantic search. Neither replaces the other.
- **`pii.py`** — regex detectors for phone/email/URL/CEP-or-address, plus a
  conservative capitalized-token heuristic for possible names (no NER
  library is installed; this deliberately over-flags rather than
  under-flags). **Known corpus quirk**: some review text contains
  upstream-anonymized placeholder proper nouns styled as fictional house
  names (e.g. "targaryen", "lannister", "stark") — an Olist-side scrubbing
  artifact, not real PII. The name heuristic harmlessly flags these; that is
  the intended, safe failure mode.
- **`safety.py`** — deterministic regex/keyword prompt-injection
  classifier (`SAFE`/`SUSPICIOUS`/`BLOCKED`). `BLOCKED` is a flag only: no
  code path in this package ever deletes a review because of it.
- **`embeddings.py`** — `intfloat/multilingual-e5-small` via
  `sentence-transformers`, pinned to Hugging Face revision
  `614241f622f53c4eeff9890bdc4f31cfecc418b3` (`config/embedding.yaml`),
  384-dim, `"query: "`/`"passage: "` prefixes per E5 convention. Disk cache
  keyed by `sha256(normalized_text|model|embedding_version)` in one `.npz`
  file. **This environment's cached Hugging Face auth token happens to be
  expired**, which makes authenticated Hub calls fail with 401 even for this
  fully public model — every Hub call in this module passes `token=False`
  for anonymous access rather than depending on ambient `HF_TOKEN` state.
- **`vector_index.py`** — a numpy brute-force cosine-similarity flat index,
  not FAISS. The indexed corpus (tens of thousands of short vectors) is
  small enough that a single matrix multiply is fast and exact; FAISS
  remains an acceptable future upgrade (task spec: "acceptable", not
  "required") if the corpus grows past what brute force can serve quickly.
  The index is **not** the source of truth — `data/processed/fact_reviews.parquet`
  is — and is fully rebuildable deterministically.

### Category/seller attribution — a non-governed join

`review_ingestion.build_review_order_join()` joins
`fact_reviews → fact_orders → fact_order_items → dim_product/dim_seller` to
attach each review to a product category / seller / seller state. This is
**explicitly not a governed KPI dimension** — `config/kpis.yaml` and
`src/kpi/query_planner.py` deliberately refuse `product_category`/`seller` as
review dimensions, since a review attaches to an *order* and ~9.86% of orders
span multiple items/categories/sellers. This module tags every review with a
`category_attribution_method`:

- `single_item_order` — the order has exactly one item; category/seller are
  unambiguous.
- `single_category_order` — multiple items, but all the same category and
  seller.
- `multi_item_order_ambiguous` — genuinely ambiguous; category/seller are
  left `None`, never guessed.
- `no_items_on_order` — the order has no item rows at all.

This join lives only in `src/evidence/` and is never imported by
`src/kpi/`, `src/anomaly/`, or `src/drivers/`.

### Corpus scope used by tests and the November package

Running the full pipeline (language/PII/safety detection, mostly bottlenecked
on `langdetect`) over the entire 99,224-row `fact_reviews` table takes a few
minutes. Test fixtures (`tests/conftest.py`) and `src/evidence/engine.py`'s
`build_november_2017_evidence_package()` both scope the review pipeline to
the **October-November 2017 investigation window** (~12,160 review rows,
~5,000 with non-empty text) — exactly the scope the investigation needs
anyway, and a real (not synthetic) slice of the corpus. A full-corpus build
is possible by passing a wider `months` set to
`evidence.engine.build_review_index()`.

## 7. Known limitations

- `data_availability_time` in `FreshnessInfo` is `None` for every evidence
  object — canonical build date isn't tracked per-row in
  `data/processed/*.parquet` today. Rather than fake a timestamp, this is
  left `None` and documented.
- The capitalized-token PII heuristic has no true NER model behind it (none
  is installed) and will both over-flag common capitalized words and
  under-flag lowercase names.
- **Retrieval precision on this corpus is measurably weak** (see
  `docs/RAG_GOVERNANCE.md` §6 and `reports/retrieval_evaluation.json`).
  Olist reviews are very short and informal (median well under 15 words);
  `multilingual-e5-small`'s embedding similarity clusters generic
  positive-sentiment reviews close to topic-specific queries on this kind of
  text. Structured pre-filtering substantially narrows the candidate pool
  before semantic search ever runs, which is the main mitigation this
  prototype applies; semantic top-K precision itself remains an honestly
  disclosed weakness, not one this build attempts to hide.
- Reviews attributed to a specific seller (the large majority —
  `single_item_order`/`single_category_order`, ~97% of the test window) are
  classified `INTERNAL`, matching the `seller` dimension's classification
  elsewhere in the system. A `PUBLIC_ANALYTICAL` caller therefore sees a
  much smaller slice of the review corpus than an `INTERNAL` caller.
