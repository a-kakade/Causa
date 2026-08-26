# STEP 3B VALIDATION — Deterministic KPI Computation Engine

Every number in this document is computed live by `src/kpi/engine.py` against
`data/processed/*.parquet` (via `scripts/step3b_validate_engine.py`) — none are
hardcoded constants. Full machine-readable output: `reports/step3b_validation.json`.
Architecture and design rationale: `docs/KPI_COMPUTATION_ENGINE.md`.

---

## 1. KPI implementation status

All 10 KPIs from `config/kpis.yaml` are implemented and passing validation.

| kpi_id | Status |
|---|---|
| revenue | ✅ Implemented, validated exactly |
| orders | ✅ Implemented, validated exactly |
| aov | ✅ Implemented |
| avg_delivery_days | ✅ Implemented |
| avg_review_score | ✅ Implemented, all 3 variants |
| freight_revenue | ✅ Implemented |
| review_volume | ✅ Implemented |
| on_time_delivery_rate | ✅ Implemented |
| quantity_sold | ✅ Implemented, unit assumption verified |
| repeat_purchase_rate | ✅ Implemented |

## 2. Formula used (as implemented, matching config/kpis.yaml exactly)

| kpi_id | Formula |
|---|---|
| revenue | `SUM(order_items.price)`, pre-aggregated to order grain, then by dimension |
| orders | `COUNT(DISTINCT order_id)`, all order_status values by default |
| aov | `SUM(agg_order_items.item_price_total) / COUNT(DISTINCT agg_order_items.order_id)` |
| avg_delivery_days | `MEAN(delivery_days)` WHERE `delivery_data_quality_flag = 'VALID'` |
| avg_review_score | 3 variants — see §6 |
| freight_revenue | `SUM(order_items.freight_value)`, same pattern as revenue |
| review_volume | `COUNT(fact_reviews rows)` — review-level, not order-level |
| on_time_delivery_rate | `COUNT(delay<=0 AND VALID) / COUNT(VALID)` |
| quantity_sold | `COUNT(order_items rows)` — verified 1 row = 1 unit, see §6 |
| repeat_purchase_rate | `COUNT(customer_unique_id, orders>=2) / COUNT(customer_unique_id)` |

## 3. Canonical source

| kpi_id | Tables read |
|---|---|
| revenue | `fact_order_items`, `fact_orders` (context only — never `fact_payments`/`agg_order_payments`) |
| orders | `fact_orders` |
| aov | `agg_order_items`, `fact_orders` (context) |
| avg_delivery_days | `fact_orders` |
| avg_review_score | `agg_order_reviews` (order-level variants) or `fact_reviews` (review-level variant) |
| freight_revenue | `fact_order_items`, `fact_orders` (context) |
| review_volume | `fact_reviews`, `fact_orders` (context) |
| on_time_delivery_rate | `fact_orders` |
| quantity_sold | `fact_order_items` |
| repeat_purchase_rate | `fact_orders` (customer_unique_id denormalized from `dim_customer` at build time) |

Verified programmatically (`test_revenue_has_no_payment_dependency`): Revenue's
and Freight Revenue's `source` field never contains `fact_payments` or
`agg_order_payments`.

## 4. Supported dimensions (enforced, not just declared)

| kpi_id | Supported | Rejected (with reason) |
|---|---|---|
| revenue, freight_revenue, quantity_sold (item-grain) | month, product_category, customer_state, seller_state, seller, product | — (all 6 supported) |
| orders, aov, avg_delivery_days, on_time_delivery_rate (order-grain) | month, customer_state | product, seller, product_category, seller_state — order can span multiple items |
| avg_review_score | month, customer_state (order-level variants only) | product, seller, product_category, seller_state; review_level_average variant does not support grouping |
| review_volume | month, customer_state | product, seller, product_category, seller_state |
| repeat_purchase_rate | — (month declared but engine refuses — see §9) | customer_state, product, seller, product_category, seller_state |

Every rejection raises a specific, named exception
(`UnsupportedDimensionError` / `UnauthorizedDimensionError`) carrying the
contract's own documented reason — never a generic failure, never a silently
invented attribution rule.

**Grouped results are additive** for item-grain KPIs — verified:
`revenue` grouped by `product_category`/`customer_state`/`product`/`seller`
each sum back exactly to the ungrouped total for November 2017
(R$1,010,271.37). This is the regression test that caught a real bug during
development (see §8).

## 5. November 2017 validation — reproduces exactly, computed live

| Metric | Computed | Required | Match |
|---|---|---|---|
| Revenue, October 2017 | R$664,219.43 | R$664,219.43 | ✅ |
| Revenue, November 2017 | R$1,010,271.37 | R$1,010,271.37 | ✅ |
| Revenue change | +R$346,051.94 | +R$346,051.94 | ✅ |
| Revenue % change | +52.1% | +52.1% | ✅ |
| Orders, October 2017 | 4,631 | 4,631 | ✅ |
| Orders, November 2017 | 7,544 | 7,544 | ✅ |
| Orders % change | +62.9% | +62.9% | ✅ |

**All 7 checks pass, computed via `KPIEngine.compute()` and
`KPIEngine.compare_periods()` against the real canonical Parquet tables** — not
copied from any prior step's report. Reproduce:

```bash
python scripts/step3b_validate_engine.py
```

## 6. Data-quality behavior

Every `KPIResult` exposes `sample_size`, `coverage`, `data_quality`, and
`warnings`. November 2017 samples (computed live):

| kpi_id | Value | Sample size | Coverage | Data quality |
|---|---|---|---|---|
| aov | 135.59 | 7,451 orders | 98.77% | HIGH |
| avg_delivery_days | 15.16 days | 7,288 orders | 96.61% | HIGH — 256 rows excluded (missing/invalid timestamps) |
| avg_review_score (default) | 3.91 | 7,480 orders | 99.15% | HIGH |
| freight_revenue | R$168,872.40 | 8,665 items | 98.77% | HIGH |
| review_volume | 4,786 reviews | 4,786 | 100% | HIGH |
| on_time_delivery_rate | 85.69% | 7,288 orders | 96.61% | HIGH |
| quantity_sold | 8,665 units | 8,665 | 100% | HIGH |
| repeat_purchase_rate (full range) | 3.12% | 96,096 customers | 100% | HIGH — matches Step 2's independently-verified 2,997/96,096 exactly |

**Delivery days matches the prior EDA's independently-reported figure**
(`docs/INVESTIGATION_SCENARIOS.md`: Nov 2017 ≈ 15.16 days) — a third independent
computation (Step 1 EDA → Step 2 canonical build → Step 3B engine) agreeing
exactly.

**NULL, never zero**, verified: a zero-orders scope (e.g. January 2010) returns
`value: None` for AOV, Average Delivery Days, and On-Time Delivery Rate, each
with an explicit warning ("... is NULL, not 0"), not `0.0` and not a crash.

**Excluded rows are always disclosed.** Example (Average Delivery Days,
November 2017): `excluded_invalid` + `excluded_missing` + `sample_size` =
`total_in_scope` exactly (7,544), verified by a test — no row silently
vanishes from the accounting.

## 7. Comparison-period behavior

`compare_periods()` returns `current_value`, `previous_value`,
`absolute_change`, `percentage_change` — deterministic arithmetic only, over
the exact same code path as a single-period request. Verified: the serialized
`ComparisonResult` contains no `is_anomaly`/`significant`/threshold field of
any kind. A zero (or NULL) previous value produces `percentage_change = None`
with an explicit warning, never `inf` or a crash.

## 8. Unsupported-query behavior

| Rejection | Example | Exception |
|---|---|---|
| Unknown KPI | `kpi_id="profit_margin"` | `UnknownKPIError` |
| Unsupported dimension | `orders` + `product` dimension | `UnsupportedDimensionError`, carries the contract's documented reason |
| Unauthorized dimension | `revenue` + `seller` dimension without `INTERNAL` clearance | `UnauthorizedDimensionError` |
| Invalid filter name | `revenue` + `{"nonexistent_filter": "x"}` | `InvalidFilterError` |
| Invalid filter value | `{"order_status": "bogus_status"}` | `InvalidFilterError`, lists valid values |
| Missing required parameter | `kpi_id=""`, or `start_date` without `end_date` | `MissingParameterError` |

**A real bug found and fixed during this step**: the first implementation of
dimension grouping silently **undercounted** Revenue by R$14,115.98 when
grouped by `product_category`, because pandas' `groupby()` drops rows whose
group key is `NaN` by default (610 products have no category, per Step 1).
Fixed by passing `dropna=False` to every dimension-grouping `groupby()` call;
the regression test (`test_grouped_results_sum_to_total_for_item_grain_kpis`)
now guards against this permanently. Documented in full in
`docs/KPI_COMPUTATION_ENGINE.md` §6 — flagged here rather than omitted, since a
silent undercount is exactly the class of error this whole project has been
built to prevent.

## 9. Test results

**231 tests pass across the entire repository** (Step 1: 17, Step 2: 62, Step
3A: 30, Step 3B: 122), reproduced from a clean state:

```bash
python -m pytest tests/ scripts/test_profile_olist.py -q
# 231 passed
```

Step 3B's 122 tests break down as:

| File | Count | Covers |
|---|---|---|
| `tests/test_kpi_engine.py` | 33 | Revenue/Orders exact values, AOV denominator, delivery exclusions, review variants, repeat purchase, freight/quantity/review-volume/on-time, comparison periods, rejection |
| `tests/test_kpi_dimensions.py` | 37 | Supported dimensions succeed, additive grouping, unsupported dimensions fail (16 parametrized combinations), clearance enforcement |
| `tests/test_kpi_results.py` | 52 | Result-object completeness (parametrized over all 10 KPIs × several checks), lineage matches contract, coverage/DQ metadata, window enforcement, caching |

## 10. Remaining semantic questions (surfaced, not hidden)

Carried forward from Step 3A (`config/kpis.yaml`'s `unresolved_semantic_decisions`),
plus new ones this step's implementation surfaced:

- **Order-status default for "recognized revenue"** (Revenue/AOV/Freight
  Revenue/Quantity Sold) remains an explicit, off-by-default filter — the
  engine does not decide this, per Step 3A.
- **`repeat_purchase_rate`'s month/cohort dimension**: the engine explicitly
  refuses rather than computing a naive, wrong per-period slice — a real
  cohort-bucketing implementation is future work, not attempted here.
- **`review_level_average`'s dimension support**: not implemented (its time
  anchor and join requirements differ from the order-level variants) — raises
  a clear, specific error if requested with dimensions.
- **Per-group coverage for dimension-grouped AOV and Average Review Score**:
  not computed (would require an additional groupby pass); every such result
  is explicitly marked `data_quality: "UNKNOWN"` with a warning, rather than a
  silently wrong or approximated number presented as trustworthy.
- **Dimension-grouped Revenue/Freight Revenue's per-group coverage** reuses the
  overall (ungrouped) figure on every group, explicitly labeled — a documented
  approximation, not a true per-group coverage computation.
- **Cache invalidation**: the `ComputationCache` has no way to detect that
  `data/processed/*.parquet` changed underneath it; a caller who rebuilds the
  canonical layer mid-session must construct a fresh `KPIEngine` (or call
  `cache.clear()`). Not automated in this step.

---

## STOP CONDITION MET

No anomaly detection, PVM, statistics beyond deterministic aggregation, RAG,
agents, or LLMs exist anywhere in `src/kpi/`. Every KPI value returned by this
engine traces to a raw CSV column through the exact lineage chain declared in
its Step 3A contract, verified by an automated test for all 10 KPIs. The
November 2017 validation numbers required by this task's §20 reproduce exactly,
computed live, not hardcoded.

**Step 3B is complete. Step 3C (or any anomaly/PVM/causal/RAG/agent work) has
not been started.**
