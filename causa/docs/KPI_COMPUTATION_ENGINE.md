# KPI Computation Engine — Step 3B

Turns the governed contracts in `config/kpis.yaml` (Step 3A) into deterministic,
reproducible KPI values. This document explains the architecture, exactly which
parts of each calculation are read from the contract at runtime vs. written as
KPI-specific code, and every design decision that isn't obvious from the code.

**No anomaly detection, PVM, causal inference, RAG, or agents exist in this
module.** The only question this engine answers: *given a governed KPI
definition and a valid query, what is the deterministic KPI value and its
complete metadata?*

---

## 1. Architecture

```
KPIRequest (models.py)
    │
    ▼
SemanticRegistry.get(kpi_id)          -- the contract, unmodified
    │
    ▼
query_planner.plan()                   -- validates the request against the
    │                                     contract; raises a specific error
    │                                     (UnknownKPIError, UnsupportedDimension-
    │                                     Error, UnauthorizedDimensionError,
    │                                     InvalidFilterError, MissingParameter-
    │                                     Error) BEFORE any data is touched
    ▼
QueryPlan                              -- resolved dates, filters, dimensions,
    │                                     variant, source tables
    ▼
KPIEngine._compute_<kpi_id>()          -- reads data/processed/*.parquet via
    │                                     CanonicalDataStore, applies the plan
    ▼
KPIResult | list[KPIResult]            -- always the full contract in models.py,
                                           never a bare number
```

`ComputationCache` sits in front of `_compute_uncached()` inside
`KPIEngine.compute()` — every request is hashed and checked before any
computation happens.

## 2. What is contract-driven at runtime vs. what is engine code

**Read from `config/kpis.yaml` at runtime, on every call** (not copy-pasted into
the engine as constants): `source_tables`, `lineage.chain`, every dimension's
`source_table`/`source_column`/`supported`/`security_classification`, every
filter's `source_column`/`applied_by_default`/`default_value`, the mandatory
`delivery_data_quality_flag` filter value, `valid_time_window`'s four dates,
`data_quality_requirements.coverage_threshold_pct`, `aggregation_variants` (for
Average Review Score), and `base_grain`/`aggregation` type (used for validation,
not dispatch — see below).

**Written as KPI-specific engine code**: the actual pandas operations (which
table(s) to load, which columns to sum/mean/count, how to join a dimension's
column onto the base table). This is a deliberate choice, explained below, not
an oversight.

### Why not a single, fully generic rule interpreter?

A KPI's `aggregation` field (`SUM`, `COUNT_DISTINCT`, `MEAN`, `RATIO`,
`DERIVED_RATIO`) tells you the *shape* of the calculation, but not enough to
execute it safely for 10 structurally different real-world KPIs. Two concrete
reasons a naive "if aggregation == SUM: df[col].sum()" interpreter would be
wrong or dangerous here:

1. **Which table to load is itself a business decision, not inferable from
   `aggregation` alone.** Revenue and Orders are both computed over
   order-adjacent data, but Revenue must never touch `fact_payments` (the whole
   point of Step 2's anti-fan-out architecture) while other KPIs legitimately
   need `agg_order_payments`. A generic interpreter would need its own
   table-selection logic, which is exactly the kind of "independently invented
   definition" this task prohibits.
2. **AOV's denominator is deliberately not the same population as Orders'
   population** (§5 of the task, and `docs/KPI_SEMANTICS_PREVIEW.md`). This is
   a specific, non-generic business rule that must be encoded somewhere; putting
   it in the KPI-specific `_compute_aov` function, clearly commented and
   traceable to the contract's `ratio.denominator` text, is more honest and
   auditable than hiding it inside a generic engine's edge-case branch.

So the discipline this engine actually enforces is narrower and more checkable:
**every constant that determines correctness (which column, which filter value,
which table) is read from the contract**, and a governance test
(`tests/test_kpi_results.py::test_every_result_has_lineage_matching_the_contract`)
fails the build if a KPI's returned lineage ever diverges from
`config/kpis.yaml`'s declared chain — so even though the *code path* is
KPI-specific, drift between the contract and the engine's behavior is
mechanically caught.

## 3. The 10 KPIs, formula and canonical source

| kpi_id | Formula (as implemented) | Canonical source | Notes |
|---|---|---|---|
| `revenue` | `SUM(fact_order_items.price)` per order, then by dimension | `fact_order_items` ⋈ `fact_orders` (context only) | Never reads `fact_payments`/`agg_order_payments` — verified by a test that inspects `result.source`. |
| `orders` | `COUNT(DISTINCT fact_orders.order_id)` | `fact_orders` | Default = ALL `order_status` values. |
| `aov` | `SUM(agg_order_items.item_price_total) / COUNT(DISTINCT agg_order_items.order_id)` | `agg_order_items` ⋈ `fact_orders` (context) | Denominator excludes the 775 orders with no item data — NOT the Orders KPI's population. |
| `avg_delivery_days` | `MEAN(fact_orders.delivery_days)` WHERE `delivery_data_quality_flag == 'VALID'` | `fact_orders` | `excluded_invalid`/`excluded_missing` always disclosed. |
| `avg_review_score` | 3 variants, see §4 below | `agg_order_reviews` / `fact_reviews` | Default = order-level representative. |
| `freight_revenue` | `SUM(fact_order_items.freight_value)` | Same pattern as Revenue | Never touches `payment_value`. |
| `review_volume` | `COUNT(fact_reviews.review_row_id)` | `fact_reviews` | `distinct_orders_represented` also exposed, explicitly labeled as a different metric. |
| `on_time_delivery_rate` | `COUNT(delay<=0 AND VALID) / COUNT(VALID)` | `fact_orders` | Same VALID population as `avg_delivery_days`. |
| `quantity_sold` | `COUNT(fact_order_items.order_item_id)` | `fact_order_items` | See §5 — unit assumption verified against real data, not assumed. |
| `repeat_purchase_rate` | `COUNT(customer_unique_id, order_count>=2) / COUNT(customer_unique_id)` | `fact_orders.customer_unique_id` (denormalized) | Contract's `in_analytical_window` default is OFF for this KPI — see §6. |

## 4. Average Review Score — three variants, one engine

| `variant` | Source | Grain |
|---|---|---|
| `order_level_representative` (**default**) | `agg_order_reviews.latest_review_score` | order |
| `order_level_true_average` | `agg_order_reviews.avg_review_score` | order |
| `review_level_average` | `fact_reviews.review_score` (no dedup) | review |

`MAX(review_score)` is never called anywhere in `_compute_avg_review_score` —
enforced by a regression test that inspects the function's source code
directly, not just its output, because `docs/REVIEW_GOVERNANCE.md`
quantitatively rejected that strategy (bias +0.3763, cherry-picking) in Step 2.

## 5. Quantity Sold — the unit assumption, verified before implementing

Per this task's explicit instruction not to fabricate a quantity interpretation:
**the raw Olist schema (`order_items`) has no `quantity` column.** Before writing
`_compute_quantity_sold`, the following was checked against the real canonical
data:

```
order+product combinations with >1 order_item row: 7,088 of 102,425 (6.9%)

Example: order 0008288aa423d2a3f00fcb17cd7d8719, product 368c6c730842d78016ad
823897a372db appears as 2 separate order_item rows, both price=49.9.
```

This confirms: when a customer buys more than one unit of the same product in
one order, Olist represents each unit as its **own row** (its own
`order_item_id`, same `product_id`, repeated `price`) rather than one row with a
quantity multiplier. Therefore `COUNT(order_items rows)` legitimately equals
units sold — this is a verified fact about the data, not a silent
reinterpretation of row count as quantity. It is also why `SUM(price)` (Revenue)
is correct without multiplying by a quantity field: `price` is already a
per-unit price, and each unit has its own row.

## 6. Dimension engine

Every dimension request is validated against the contract before any data is
touched (`query_planner.plan()`). Three outcomes:

- **Declared + `supported: true` + within the requester's clearance** → the
  engine joins whatever table the dimension needs (`dim_product` for
  `product_category`, `dim_seller` for `seller_state`, `fact_orders` for
  `customer_state`/`order_status`) and groups by it.
- **Declared but `supported: false`** → `UnsupportedDimensionError`, carrying
  the contract's own documented reason (e.g. "order can span multiple
  sellers"). No attribution rule is ever invented to make it "work" anyway.
- **Declared, supported, but above the requester's clearance** (e.g. `seller`
  requires `INTERNAL`) → `UnauthorizedDimensionError`.

**A real bug this discipline caught during development**: grouping Revenue by
`product_category` initially undercounted the total by R$14,115.98, because
pandas' `groupby()` drops rows whose group key is `NaN` by default — and 610
products have a null category (per Step 1's audit). Every dimension-grouping
`groupby()` call in this engine now passes `dropna=False` explicitly, and
`tests/test_kpi_dimensions.py::test_grouped_results_sum_to_total_for_item_grain_kpis`
is the regression guard: any KPI's dimension-grouped results must sum back
exactly to its ungrouped total, or the test fails.

**Order-grain KPIs deliberately support fewer dimensions than item-grain
KPIs.** Revenue/Freight Revenue/Quantity Sold (item-grain, `SUM`/`COUNT` over
`order_items`) safely support `seller`/`product`/`product_category`/
`seller_state` because summing at item grain naturally attributes each row to
exactly the seller/product it belongs to. Orders/AOV/Delivery/Review
Score/On-Time Rate (order-grain, `COUNT DISTINCT`/`MEAN` over `orders`) do
**not** support those same dimensions — an order can span multiple items
(~9.86% of orders, per Step 1), and slicing an order-grain aggregate by an
item-grain attribute would need an attribution rule this engine refuses to
invent. This is enforced entirely in `config/kpis.yaml` (Step 3A), not
re-decided here — the engine just honors it.

**Per-group coverage is not computed for AOV / Average Review Score when
dimension-grouped** (each group's `KPIResult.coverage` is `None`,
`data_quality` is `"UNKNOWN"`, and a warning explains why). Computing a correct
per-group denominator (the eligible-population count *for that specific
group*) would need an additional groupby pass this implementation does not
perform; rather than silently report a wrong or misleading coverage number, the
engine discloses that it isn't computed. Revenue/Freight Revenue's
dimension-grouped results reuse the *overall* (ungrouped) coverage figure on
every group, explicitly labeled as such — an approximation, not a per-group
truth, and documented here so it isn't mistaken for one.

## 7. Time engine

`day` / `week` / `month` are not separate contract dimensions — each resolves
through the KPI's declared `"month"` dimension entry (same source column,
different pandas resample frequency: `strftime("%Y-%m-%d")` / `to_period("W-MON")`
/ `to_period("M")`). The contract decides *whether* time-bucketing this KPI is
safe at all (every KPI in this registry declares `month` as supported); the
grain (day/week/month) is an orthogonal engine-level choice layered on top.

**Analytical window default resolution** (`query_planner.plan()`): the window
filter's default (on/off) is resolved *first*, then the default date range is
derived from it — a request with no explicit dates defaults to the
contract's recommended window (`2017-01`–`2018-08`) **only if** the window
filter is actually being applied; otherwise it defaults to the full data range
(`2016-09`–`2018-10`). This matters concretely for `repeat_purchase_rate`,
whose contract turns the window filter off by default (a customer's orders can
straddle the window boundary) — without this coupling, a default
`repeat_purchase_rate` query would apply no window filter but still silently
restrict its date range to the recommended window, contradicting its own
default. `override_analytical_window=True` forces the full range even for
KPIs whose contract default is on.

**Nothing is ever deleted.** The window is applied as a boolean filter
(`fact_orders.in_analytical_window`) at query time; `data/processed/*.parquet`
still contains every row from every excluded month, queryable via
`override_analytical_window=True` or explicit out-of-window dates (see
`STEP3B_VALIDATION.md` §6 for a worked example: `orders` for September 2018
alone returns exactly 16, matching Step 1/Step 2's independent finding).

## 8. Comparison periods

`KPIEngine.compare_periods()` computes the *same* KPI over two periods via the
*exact same code path* as any other request (no separate "comparison formula"
to keep in sync) and returns a `ComparisonResult` with `current_value`,
`previous_value`, `absolute_change`, `percentage_change`. This is **deterministic
arithmetic only** — `ComparisonResult` has no `is_anomaly`, `significant`, or
threshold field of any kind (verified by a test that inspects the serialized
dict). Zero-previous-value is handled as `percentage_change = None` with a
warning, never as `inf` or a crash.

## 9. Data quality tiering

`coverage_threshold_pct` comes from the contract. The `HIGH`/`MEDIUM`/`LOW`
band width (15 percentage points) is a single constant
(`MEDIUM_BAND_WIDTH_PP` in `engine.py`) chosen to match **every** contract's own
`confidence_implications` text from Step 3A verbatim (e.g. Revenue: "≥95% HIGH;
80-95% MEDIUM; <80% LOW" — 95−15=80; Average Delivery Days: "≥90% HIGH; 75-90%
MEDIUM" — 90−15=75) — not a new rule invented for this engine, a formalization
of text already written and ratified in Step 3A.

## 10. Caching

`hash(kpi_id + date_range + dimensions(sorted) + filters(sorted) + variant +
override_analytical_window + requester_clearance)`, SHA-256 over a canonical
JSON encoding — see `cache.py`. In-memory only, no TTL, no invalidation beyond
`clear()`. Not an LLM/semantic cache: two requests only hit the same cache entry
if they mean *exactly* the same thing (verified: dimension/filter key order
never changes the hash; a different filter value always does).

## 11. Known limitations (disclosed, not hidden)

- `review_level_average` (Average Review Score's non-default variant) does not
  support dimension grouping — its time anchor (`review_creation_date`) and
  join requirements differ from the order-level variants', and this was not
  built out. Raises a clear, specific `KPIRequestError` if requested.
- `repeat_purchase_rate`'s `month` dimension is declared supported *at the data
  level* in the contract, with an explicit caveat that cohort-month bucketing
  has "no ready query implemented" (Step 3A's own documented unresolved
  decision). The engine raises a `KPIRequestError` citing this rather than
  computing a naive (and wrong) per-period slice.
- Dimension-grouped AOV and Average Review Score do not compute a correct
  per-group `coverage` (see §6) — disclosed via `data_quality: "UNKNOWN"` and an
  explicit warning on every affected result, never silently reported as `HIGH`.
