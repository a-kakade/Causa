# KPI Semantic Layer — Step 3A

**This document, `config/kpis.yaml`, and `schemas/kpi_contract.schema.json`
together are the governed source of truth for what a KPI means in Causa.** A
future LLM/agent layer must read from here, not invent a definition. No KPI
value is computed anywhere in this step — see `STRICT RULE` at the end.

Built on top of, and consistent with, everything ratified in Step 1 and Step 2:
`DATA_FOUNDATION_REPORT.md`, `STEP2_VALIDATION.md`, `docs/CANONICAL_DATA_MODEL.md`,
`docs/DATA_LINEAGE_V2.md`, `docs/KPI_SEMANTICS_PREVIEW.md`,
`docs/REVIEW_GOVERNANCE.md`, `docs/ANALYTICAL_WINDOW.md`.

---

## 1. What's in the semantic layer

| File | Role |
|---|---|
| `schemas/kpi_contract.schema.json` | The JSON Schema every KPI contract must satisfy — structural governance, machine-enforced. |
| `config/kpis.yaml` | The 10 KPI contracts themselves. This is the actual semantic layer content. |
| `src/kpi/semantic_registry.py` | Loads and validates the contracts; exposes read-only accessors (`get`, `get_dimension`, `get_lineage_chain`, …). Contains zero KPI-calculation logic. |
| `tests/test_kpi_contracts.py` | 30 tests enforcing both generic governance rules and the specific rules this task requires (Revenue's source, Repeat Purchase's identity column, Delivery's exclusions, Review's governance). |
| `reports/kpi_semantic_validation.json` | Machine-readable validation output — contract validity, test results, per-KPI summary. |

## 2. The 10 KPIs

| kpi_id | Name | Category | Grain | Aggregation | Dimensions supported | Security |
|---|---|---|---|---|---|---|
| `revenue` | Revenue | primary | order (pre-aggregated) | SUM | 6/6 | PUBLIC_ANALYTICAL |
| `orders` | Orders | primary | order | COUNT_DISTINCT | 3/7 | PUBLIC_ANALYTICAL |
| `aov` | Average Order Value | primary | order | DERIVED_RATIO | 2/6 | PUBLIC_ANALYTICAL |
| `avg_delivery_days` | Average Delivery Days | primary | order | MEAN | 2/6 | PUBLIC_ANALYTICAL |
| `avg_review_score` | Average Review Score | primary | order (default variant) | MEAN | 2/6 | PUBLIC_ANALYTICAL |
| `freight_revenue` | Freight Revenue | supporting | order (pre-aggregated) | SUM | 6/6 | PUBLIC_ANALYTICAL |
| `review_volume` | Review Volume | supporting | review | COUNT | 2/6 | PUBLIC_ANALYTICAL |
| `on_time_delivery_rate` | On-Time Delivery Rate | supporting | order | RATIO | 2/6 | PUBLIC_ANALYTICAL |
| `quantity_sold` | Quantity Sold | supporting | order_item | COUNT | 6/6 | PUBLIC_ANALYTICAL |
| `repeat_purchase_rate` | Repeat Purchase Rate | supporting | customer_unique_id | RATIO | 1/6 | PUBLIC_ANALYTICAL |

Every KPI's `kpi_classification` is `PUBLIC_ANALYTICAL` at the *aggregate value*
level — none expose an individual record. Underlying identifiers (`seller_id`,
`customer_id`, `customer_unique_id`) that participate in a KPI's calculation are
separately classified `INTERNAL`/`RESTRICTED` at the dimension level and are never
themselves surfaced as queryable values — see §6.

**Why dimension-support varies so much (1/6 to 6/6) — this is a feature, not a
gap.** It reflects a real structural fact about the canonical grain, checked KPI
by KPI rather than assumed: **item-grain KPIs** (Revenue, Freight Revenue,
Quantity Sold — anything that is a `SUM`/`COUNT` over `order_items`) can safely
slice by `seller`, `product`, `product_category`, and `seller_state`, because
summing at item grain naturally attributes each item to exactly the
seller/product/category it belongs to. **Order-grain KPIs** (Orders, AOV,
Average Delivery Days, Average Review Score, On-Time Delivery Rate — anything
that is a `COUNT DISTINCT`/`MEAN` over `orders`) *cannot* safely make that claim,
because ~9.86% of orders span multiple items and can therefore touch multiple
sellers/products/categories — slicing an order-grain count or mean by an
item-grain dimension would require an attribution rule this contract does not
define, so those dimensions are explicitly marked unsupported, each with a
documented reason, rather than silently offered and quietly wrong. This is the
single most important structural decision in this semantic layer.

## 3. Required definitions — as specified in the brief

### Revenue

```
CAUSA_REVENUE = SUM(order_items.price)
```

Aggregated to order grain (`agg_order_items.item_price_total`) **before** any
join to `order_payments` or `order_reviews` — the contract's `source_tables`
list only `agg_order_items`/`fact_order_items`, and a governance test
(`test_revenue_explicitly_uses_order_items_price_not_payment_value`) fails the
build if `order_payments`/`payment_value` ever appear as a Revenue source.
Drivers: **Volume, Price, Mix** — exactly the graph specified, each a
`deterministic_decomposition`, none a causal claim.

### Orders

```
COUNT(DISTINCT order_id)
```

**Default scope is ALL orders** (all 8 `order_status` values), matching
`fact_orders`'s canonical grain of 99,441 rows exactly — this is stated
explicitly in the contract (`business_definition`), not left implicit, per the
brief's instruction. `order_status` is exposed as an off-by-default filter for
anyone who needs a "completed orders only" slice.

### AOV

```
Revenue / Orders(with item data)
```

**Never** computed by averaging `order_items.price` directly — the contract's
`ratio.numerator` is Revenue and `ratio.denominator` is explicitly `COUNT(DISTINCT
agg_order_items.order_id)`, **not** the `orders` KPI's population — a documented,
deliberate choice, because including the 775 orders with no item data in the
denominator (while they contribute 0 to the numerator) would silently dilute
AOV. `zero_denominator_behavior`: **NULL/undefined**, never 0 or infinity.

### Average Delivery Days

```
MEAN(customer_delivery_timestamp − purchase_timestamp), VALID rows only
```

Gated by a **mandatory** default filter on `delivery_data_quality_flag = 'VALID'`
— 96,310 of 99,441 orders (96.86%) qualify. The exclusion is disclosed, not
hidden: `invalid_data_treatment` states the exact **166** `INVALID_SEQUENCE`
exclusions (with the Step 2 finding that 121 are within an hour, plausible
clock-sync noise, and 2 are multi-day outliers) alongside the 2,964
`MISSING_CUSTOMER_DATE` and 1 `MISSING_CARRIER_DATE` exclusions. `null_behavior`
confirms missing dates are NULL, never coerced to 0.

### Average Review Score

Two explicitly distinct concepts, neither confused with the other (per
`docs/REVIEW_GOVERNANCE.md`):

| Variant | Grain | Source | Default? |
|---|---|---|---|
| `order_level_representative` | order (98,673) | `agg_order_reviews.latest_review_score` | **Yes** — executive reporting default |
| `order_level_true_average` | order (98,673) | `agg_order_reviews.avg_review_score` | No — recommended for distributional use |
| `review_level_average` | review (99,224, no dedup) | `fact_reviews.review_score` | No — a genuinely different, review-weighted statistic |

The default explicitly cites `docs/REVIEW_GOVERNANCE.md`'s ratified strategy
(latest by `review_answer_timestamp`, bias −0.0734) and a governance test
(`test_avg_review_score_does_not_silently_choose_highest_score`) fails the build
if `MAX(review_score)` — the strategy quantitatively rejected in Step 2 for its
+0.3763 cherry-picking bias — ever appears in this KPI's formula.

### Repeat Purchase Rate

```
COUNT(DISTINCT customer_unique_id WHERE order_count >= 2) / COUNT(DISTINCT customer_unique_id)
```

Uses **`customer_unique_id`**, never `customer_id` — enforced by a governance
test. `base_grain` is literally `customer_unique_id`-prefixed, and the contract's
`business_definition` explicitly states that using `customer_id` would produce a
0.00% repeat rate by construction (a category error, not a finding), since
`customer_id` is re-issued per order.

## 4. Driver graphs (analytical hypotheses, not causal claims)

Every driver in every KPI contract carries `is_causal_claim: false`, enforced
structurally by the JSON Schema (`const: false`) and re-checked by a governance
test.

```
Revenue                          Average Delivery Days             Average Review Score
├── volume (deterministic)       ├── carrier_days (deterministic)  ├── score_distribution (statistical)
├── price (deterministic)        ├── fulfillment_delay              ├── low_score_share (statistical)
└── mix (deterministic)          │     (deterministic)              └── review_text_evidence (qualitative)
                                  └── estimated_vs_actual_delay
                                        (deterministic)
```

Every other KPI also declares its own driver graph (see `config/kpis.yaml`) —
e.g. Orders' `order_status_mix` / `new_vs_repeat_customer_mix` /
`temporal_seasonality`, or Repeat Purchase Rate's `customer_tenure` (flagged as a
**censoring effect**, not a behavior change, since the dataset's 2018-10 cutoff
right-truncates every cohort's opportunity to place a 2nd order).

## 5. Materiality contract — configuration, not implementation

Every KPI declares a materiality config block:

```json
{
  "absolute_threshold": ..., "relative_threshold": ..., "statistical_threshold": ...,
  "minimum_observations": ..., "minimum_business_impact": ..., "persistence_periods": ...,
  "implemented": false
}
```

`implemented` is `false` for all 10 KPIs, enforced by both the JSON Schema
(`const: false`) and a governance test — **no anomaly engine exists in this
repository.** Values are informed starting defaults derived from Step 1's
exploratory materiality scan (`docs/INVESTIGATION_SCENARIOS.md`'s 15%
month-over-month threshold), not statistically tuned. `repeat_purchase_rate`
uses a higher `minimum_observations` (100 vs. the standard 30) because it's a
rare-event rate off a 3.12% baseline and needs a larger sample to move reliably.

## 6. Security classification

| Classification | Meaning | Examples in this registry |
|---|---|---|
| `PUBLIC_ANALYTICAL` | Safe to expose as an aggregate KPI value or a dimension slice value (e.g. "SP", "beleza_saude") | All 10 KPI values; `month`, `customer_state`, `product`, `product_category`, `seller_state` dimensions |
| `INTERNAL` | Business-sensitive but not personal — competitive/operational detail | `seller` (`seller_id`) dimension, wherever it's supported |
| `RESTRICTED` | Individual identifiers — never surfaced to a future LLM/agent context | `customer_id`, `customer_unique_id` values (used internally to *compute* `repeat_purchase_rate`, never exposed as a queryable dimension in any contract) |

A governance test
(`test_customer_and_seller_identifier_dimensions_are_not_public`) verifies no
contract exposes a raw customer identifier as a dimension, and that `seller` is
never classified `PUBLIC_ANALYTICAL`. This directly satisfies the brief's rule:
*"Do not expose customer identifiers to the future LLM layer unless required."*
None of the 10 KPIs require it.

## 7. Lineage — every field traceable to raw

Every contract's `lineage.chain` walks:

```
kpi → semantic_definition → canonical_table_field → raw_table_column
```

Example (Revenue):

```
revenue
  → docs/KPI_SEMANTICS_PREVIEW.md#causa_revenue
  → agg_order_items.item_price_total
  → order_items.price
```

`lineage.traceable_to_raw` is `true` (schema-enforced `const`) for all 10 —
consistent with `docs/DATA_LINEAGE_V2.md`'s worked example for this exact KPI.

## 8. Supported analytical methods (declared, not built)

Each KPI declares which future methods its shape is compatible with —
`time_series_aggregation`, `period_over_period_change`,
`segmentation_by_declared_dimension`, plus KPI-specific ones like
`deterministic_pvm_decomposition` (Revenue, AOV, Quantity Sold) or
`cohort_analysis` (Repeat Purchase Rate). **None of these methods are
implemented anywhere in this repository** — `supported_methods` is a
compatibility declaration for whoever builds Step 3B+, not a working feature.
Notably absent from every KPI: `anomaly_detection`, `causal_inference`, `rag`,
`llm_reasoning` — none of those exist yet, and this document does not claim they
do.

## 9. Unresolved semantic decisions (surfaced, not hidden)

Pulled directly from `reports/kpi_semantic_validation.json`:

- **Revenue / AOV / Freight Revenue / Quantity Sold**: whether `order_status`
  should be filtered to exclude `canceled`/`unavailable` by default for a
  "recognized revenue" view is not decided — exposed as an explicit, off-by-default
  filter (quantified impact: −0.72% of unfiltered revenue, R$97.2K of R$13.59M,
  if excluded).
- **Orders**: whether a "completed orders" variant should become a second,
  separately-named KPI rather than a filter on this one is not decided.
- **Repeat Purchase Rate**: cohort-month bucketing (grouping customers by
  first-order month) is declared supported at the data level but no ready query
  is implemented; whether canceled orders should count toward a customer's
  `order_count` is not decided (currently they do, by default).

None of these block the contracts from validating — they are documented open
questions for whoever builds the query/calculation layer next, exactly as this
task requires ("report unresolved semantic decisions").

---

## STRICT RULE — respected

**No KPI value is calculated anywhere in this repository as of Step 3A.**
`src/kpi/semantic_registry.py` contains no pandas aggregation, no read of
`data/processed/*.parquet`, and no arithmetic beyond validating contract
structure. Verify: `grep -rn "read_parquet\|\.sum()\|\.mean()\|groupby" src/kpi/`
returns nothing. This document, `config/kpis.yaml`, and the schema are
definitions — a governed contract for what Step 3B (not built here) must
implement faithfully.
