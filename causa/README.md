# Causa — Olist Data Foundation

Causa is a KPI Decision Intelligence project, built step by step. This repo does
**not** touch agents, backend architecture, frontend, RAG, PostgreSQL, or LLM
workflows yet. **See [PROJECT_JOURNEY.md](PROJECT_JOURNEY.md) for the running,
always-up-to-date log of every step** — start there. Completed so far:

- **Step 1 — EDA + Repository/Data Foundation Audit**: understand and validate the
  [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).
  See [DATA_FOUNDATION_REPORT.md](DATA_FOUNDATION_REPORT.md) and
  [REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md).
- **Step 2 — Canonical Data Model + Controlled Cleaning Layer**: transform the raw
  data into a safe, reproducible analytical layer (`data/processed/`) with explicit
  grains, a documented revenue definition, review governance, and structural
  anti-fan-out protection. See [STEP2_VALIDATION.md](STEP2_VALIDATION.md).
- **Step 3A — KPI Semantic Layer**: 10 governed, machine-readable KPI contracts
  (`config/kpis.yaml`) defining what each KPI means, its grain, dimensions,
  drivers, and data-quality rules. See
  [docs/KPI_SEMANTIC_LAYER.md](docs/KPI_SEMANTIC_LAYER.md).
- **Step 3B — Deterministic KPI Computation Engine**: `src/kpi/engine.py` turns
  the Step 3A contracts into actual KPI values, with full lineage/coverage/
  data-quality metadata on every result. See
  [STEP3B_VALIDATION.md](STEP3B_VALIDATION.md).
- **Step 3C — Materiality / Anomaly Detection Engine**: `src/anomaly/`
  decides whether a KPI movement is statistically unusual and economically
  material enough to warrant investigation — deterministic/statistical only,
  no causal claims. See [STEP3C_VALIDATION.md](STEP3C_VALIDATION.md).
- **Step 3D — Driver Decomposition Engine**: `src/drivers/` mathematically
  decomposes a Revenue movement into Price/Volume/Mix effects plus
  category/seller/geographic contribution, with a reconciliation guard on
  every result. See [STEP3D_VALIDATION.md](STEP3D_VALIDATION.md).

No causal inference, RAG, agents, LLM workflows, recommendations, or frontend
exist yet — those are future steps.

## Scope covered so far

- Load and inspect every Olist CSV table; profile schema, nulls, cardinality,
  referential integrity (Step 1).
- Run temporal/KPI, text/entity-linkage, join-fanout, PVM-decomposition, and
  anomaly/contradiction analysis — all against the real data, nothing simulated
  (Step 1 EDA).
- Independently re-verify every Step 1 EDA claim from scratch, plus file
  encoding/delimiter/BOM checks (Step 1 audit).
- Build a canonical, versioned, anti-fan-out-by-construction data model with
  explicit grains, a data-driven analytical time window, a reconciled revenue
  definition, and use-case-specific review governance — all covered by an
  automated test suite (Step 2).

## Repository structure

```
causa/
├── README.md
├── REPOSITORY_AUDIT.md              # Step 1: repo structure, reusable code, tech debt
├── DATA_FOUNDATION_REPORT.md        # Step 1: raw-data audit, key/relationship integrity, final decision
├── STEP2_VALIDATION.md              # Step 2: canonical model validation, row counts, test results
├── data/
│   ├── raw/olist/                   # raw Olist CSVs (not committed — see Getting the data) — NEVER modified
│   └── processed/                   # canonical layer (Parquet, not committed — regenerate via scripts/step2_04_*)
├── notebooks/
│   └── 01_olist_eda.ipynb          # exploratory data analysis
├── scripts/
│   ├── lib/raw_loader.py           # the one place raw CSVs are read from (Step 2+)
│   ├── profile_olist.py            # schema/null/key/FK/cardinality/date profiling (Step 1)
│   ├── audit_raw_data.py           # independent Step 1 audit (encoding, keys, relationships, language, PII)
│   ├── kpi_temporal_eda.py         # KPI time series, revenue reconciliation, sparse-history, segmentation
│   ├── text_and_entity_eda.py      # review text quality, entity linkage, PII/injection scan
│   ├── join_driver_anomaly_eda.py  # join fan-out demo, PVM decomposition, contradiction scan
│   ├── extra_plots.py              # supplementary plots for the above
│   ├── step2_01_window_analysis.py         # analytical time window, data-driven
│   ├── step2_02_revenue_reconciliation.py  # CAUSA_REVENUE definition, fresh reconciliation
│   ├── step2_03_review_dedup_evaluation.py # 4 review dedup strategies, quantitatively compared
│   ├── step2_04_build_canonical.py         # builds data/processed/*.parquet
│   └── step2_05_validation_report.py       # runs tests/, writes reports/step2_validation.json
├── tests/                           # Step 2 automated test suite (pytest, 62 tests)
│   ├── conftest.py, test_keys.py, test_relationships.py, test_fanout.py
│   └── test_revenue.py, test_reviews.py, test_delivery.py
├── eda_plots/                      # all generated EDA plots (PNG)
├── reports/                        # machine-readable profiling/validation JSON + CSV
├── docs/
│   ├── EDA_REPORT.md               # Step 1 EDA entry point — summary, scoring, recommendation
│   ├── DATA_DICTIONARY.md, DATA_QUALITY_REPORT.md, RELATIONSHIP_GRAPH.md, DATA_LINEAGE.md
│   ├── KPI_CANDIDATES.md, INVESTIGATION_SCENARIOS.md, DATA_MODEL.md   # Step 1 EDA docs
│   ├── CANONICAL_DATA_MODEL.md     # Step 2: grains, diagram, anti-fan-out architecture
│   ├── ANALYTICAL_WINDOW.md        # Step 2: data-driven time window decision
│   ├── KPI_SEMANTICS_PREVIEW.md    # Step 2: CAUSA_REVENUE definition (not the KPI engine)
│   ├── REVIEW_GOVERNANCE.md        # Step 2: review dedup/aggregation decision, quantified
│   ├── GEOLOCATION_DECISION.md     # Step 2: why geolocation is excluded, how to add it later
│   ├── DATA_LINEAGE_V2.md          # Step 2: field-by-field lineage for every canonical column
│   ├── KPI_SEMANTIC_LAYER.md       # Step 3A: human-readable rendering of the KPI contracts
│   ├── KPI_COMPUTATION_ENGINE.md   # Step 3B: KPIEngine architecture and design rationale
│   ├── MATERIALITY_ENGINE.md       # Step 3C: anomaly/materiality decision model, design rationale
│   └── DRIVER_DECOMPOSITION.md     # Step 3D: PVM + contribution decomposition, design rationale
├── config/
│   └── kpis.yaml                   # Step 3A: the 10 governed KPI contracts (the semantic layer itself)
├── schemas/
│   └── kpi_contract.schema.json    # Step 3A: JSON Schema every KPI contract must satisfy
├── src/kpi/
│   ├── semantic_registry.py        # Step 3A: loads + validates contracts — computes NO KPI values
│   ├── models.py                   # Step 3B: KPIRequest / KPIResult / ComparisonResult
│   ├── query_planner.py            # Step 3B: validates requests against contracts before any data is touched
│   ├── cache.py                    # Step 3B: deterministic hash-based computation cache
│   └── engine.py                   # Step 3B: KPIEngine — the actual deterministic calculations
├── src/anomaly/
│   ├── baseline.py                 # Step 3C: baseline methods + entity->category->regional->global fallback
│   ├── statistics.py               # Step 3C: z-score / robust z-score / percentile, with documented assumptions
│   ├── materiality.py              # Step 3C: the materiality decision model (magnitude/statistical/business-impact)
│   ├── semantic.py                 # Step 3C: reads config/kpis.yaml's materiality thresholds
│   └── engine.py                   # Step 3C: orchestrator — AnomalyResult, never a causal claim
├── src/drivers/
│   ├── pvm.py                      # Step 3D: Revenue Price/Volume/Mix bridge
│   ├── contribution.py             # Step 3D: category/seller/geographic additive decomposition
│   ├── ranking.py                  # Step 3D: deterministic absolute-contribution ranking
│   └── engine.py                   # Step 3D: orchestrator + reconciliation guard
├── STEP3B_VALIDATION.md             # Step 3B final validation summary
├── STEP3C_VALIDATION.md             # Step 3C final validation summary
├── STEP3D_VALIDATION.md             # Step 3D final validation summary
├── PROJECT_JOURNEY.md               # running log of every step — read this first
└── requirements.txt
```

## Getting the data

1. Download the Olist dataset from Kaggle: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce
2. Extract the CSV files into `data/raw/olist/`. Expected files:
   - `olist_customers_dataset.csv`
   - `olist_orders_dataset.csv`
   - `olist_order_items_dataset.csv`
   - `olist_order_payments_dataset.csv`
   - `olist_order_reviews_dataset.csv`
   - `olist_products_dataset.csv`
   - `olist_sellers_dataset.csv`
   - `olist_geolocation_dataset.csv`
   - `product_category_name_translation.csv`

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
```

## Usage

**Step 1 — EDA and audit** (writes to `reports/` and/or `eda_plots/`):

```bash
python scripts/profile_olist.py
python scripts/kpi_temporal_eda.py
python scripts/text_and_entity_eda.py
python scripts/join_driver_anomaly_eda.py
python scripts/extra_plots.py
python scripts/audit_raw_data.py
```

**Step 2 — build the canonical layer and validate it** (run in this order):

```bash
python scripts/step2_01_window_analysis.py
python scripts/step2_02_revenue_reconciliation.py
python scripts/step2_03_review_dedup_evaluation.py
python scripts/step2_04_build_canonical.py       # writes data/processed/*.parquet
python -m pytest tests/ -v                        # 62 tests
python scripts/step2_05_validation_report.py       # writes reports/step2_validation.json
```

**Step 3A — validate the KPI semantic layer** (definitions only, no calculation):

```bash
python scripts/step3a_validate_semantic_layer.py   # loads config/kpis.yaml, validates, writes
                                                     # reports/kpi_semantic_validation.json
python -m pytest tests/test_kpi_contracts.py -v     # 30 tests
```

**Step 3B — compute KPI values via the deterministic engine:**

```bash
python scripts/step3b_validate_engine.py            # reproduces the Oct/Nov 2017 validation
                                                      # numbers live, writes reports/step3b_validation.json
python -m pytest tests/test_kpi_engine.py tests/test_kpi_dimensions.py tests/test_kpi_results.py -v  # 122 tests
```

```python
# quick interactive example
from kpi.engine import KPIEngine
from kpi.models import KPIRequest

engine = KPIEngine()
result = engine.compute(KPIRequest(kpi_id="revenue", start_date="2017-11-01", end_date="2017-11-30"))
print(result.value, result.coverage, result.data_quality)
```

Then explore interactively in `notebooks/01_olist_eda.ipynb`.

## Deliverables

**Step 1:**
- [x] `REPOSITORY_AUDIT.md`, `DATA_FOUNDATION_REPORT.md` — independent repo + raw-data audit
- [x] `docs/EDA_REPORT.md` — entry point: executive summary, suitability score, final recommendation
- [x] `docs/DATA_DICTIONARY.md`, `DATA_QUALITY_REPORT.md`, `RELATIONSHIP_GRAPH.md`, `DATA_LINEAGE.md`, `KPI_CANDIDATES.md`, `INVESTIGATION_SCENARIOS.md`, `DATA_MODEL.md`
- [x] `eda_plots/`, `reports/eda_master_profile.json`, `reports/raw_data_profile.json`

**Step 2:**
- [x] `data/processed/` — 10 canonical tables (Parquet): `dim_customer`, `dim_product`,
      `dim_seller`, `fact_orders`, `fact_order_items`, `fact_payments`, `fact_reviews`,
      `agg_order_items`, `agg_order_payments`, `agg_order_reviews`
- [x] `docs/CANONICAL_DATA_MODEL.md`, `ANALYTICAL_WINDOW.md`, `KPI_SEMANTICS_PREVIEW.md`,
      `REVIEW_GOVERNANCE.md`, `GEOLOCATION_DECISION.md`, `DATA_LINEAGE_V2.md`
- [x] `tests/` — 62 automated tests (keys, relationships, fan-out, revenue, reviews, delivery)
- [x] `reports/step2_*.json` — machine-readable window/revenue/dedup/build/validation output
- [x] `STEP2_VALIDATION.md` — final validation summary

**Step 3A:**
- [x] `config/kpis.yaml` — 10 governed KPI contracts (5 primary, 5 supporting) — definitions only
- [x] `schemas/kpi_contract.schema.json` — JSON Schema every contract is validated against
- [x] `src/kpi/semantic_registry.py` — loader/validator, computes no KPI values
- [x] `docs/KPI_SEMANTIC_LAYER.md`, `tests/test_kpi_contracts.py` (30 tests), `reports/kpi_semantic_validation.json`

**Step 3B:**
- [x] `src/kpi/engine.py`, `models.py`, `query_planner.py`, `cache.py` — deterministic computation engine
- [x] `docs/KPI_COMPUTATION_ENGINE.md` — architecture, contract-vs-code discipline, known limitations
- [x] `tests/test_kpi_engine.py`, `test_kpi_dimensions.py`, `test_kpi_results.py` — 122 tests
- [x] `reports/step3b_validation.json` — live-computed Oct/Nov 2017 validation
- [x] `STEP3B_VALIDATION.md` — final validation summary

**Ongoing:**
- [x] `PROJECT_JOURNEY.md` — running log of every step (updated at the end of each)
