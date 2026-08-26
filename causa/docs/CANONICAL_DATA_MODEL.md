# Canonical Data Model

Built by `scripts/step2_04_build_canonical.py`. Every table is written to
`data/processed/*.parquet`. Raw CSVs in `data/raw/olist/` are never read for
anything except loading (via `scripts/lib/raw_loader.py`) — never written to.

## Design principle

**No fact or aggregate table carries a measure that belongs to a different grain
without an explicit, separately-named, separately-built aggregation step.**
`fact_orders` has no `revenue` column — there is nothing to accidentally multiply
by joining it to a multi-row child table, because the revenue number simply does
not live there. It lives in `agg_order_items`, already reduced to one row per
order, before any downstream join can touch it. This is what makes the classic
"orders × items × payments × reviews" fan-out mistake **structurally difficult**,
not just documented against — see §Anti-fan-out below and `tests/test_fanout.py`.

## The 10 canonical tables and their grain

| Table | Grain | Rows | PK |
|---|---|---|---|
| `dim_customer` | 1 row per `customer_id` (order-scoped identity — **not** deduplicated to 1 row per person) | 99,441 | `customer_id` |
| `dim_product` | 1 row per `product_id` | 32,951 | `product_id` |
| `dim_seller` | 1 row per `seller_id` | 3,095 | `seller_id` |
| `fact_orders` | 1 row per `order_id` — **all** orders, regardless of window/completeness | 99,441 | `order_id` |
| `fact_order_items` | 1 row per `order_item_id` within `order_id` — native line-item grain, never pre-aggregated | 112,650 | `(order_id, order_item_id)` |
| `fact_payments` | 1 row per payment record | 103,886 | `(order_id, payment_sequential)` |
| `fact_reviews` | 1 row per **raw review record** — genuine review grain, including all 814 duplicate `review_id`s and all 547 multi-review orders | 99,224 | `review_row_id` (synthetic surrogate — `review_id` is not unique, verified in Step 1) |
| `agg_order_items` | 1 row per order **that has ≥1 item** (absent, not zero, otherwise) | 98,666 | `order_id` |
| `agg_order_payments` | 1 row per order **that has ≥1 payment** (absent, not zero, otherwise) | 99,440 | `order_id` |
| `agg_order_reviews` | 1 row per order **that has ≥1 review** (absent, not zero, otherwise) | 98,673 | `order_id` |

## Model diagram

```
                         dim_customer (99,441)
                                │  customer_id  (1:1, verified)
                                ▼
                          fact_orders (99,441)
              (ALL orders; no revenue/payment/review measure lives here)
                    │            │            │            │
      1:0..21 items │   1:0..29  │  1:0..3    │  denormalized customer_state/
                     │  payments │  reviews   │  city/unique_id (attributes,
                     ▼           ▼            ▼  not measures -- safe)
        fact_order_items   fact_payments  fact_reviews
        (112,650, native)  (103,886,      (99,224, native
              │  │           native grain)  grain, review_row_id
   ┌──────────┘  └──────┐                   surrogate PK)
   ▼                    ▼
dim_product         dim_seller
(32,951)            (3,095)

   ── separately, explicit order-grain aggregates (never implicit) ──

fact_order_items ──groupby(order_id)──▶ agg_order_items   (98,666: CAUSA_REVENUE lives here)
fact_payments    ──groupby(order_id)──▶ agg_order_payments (99,440)
fact_reviews     ──groupby(order_id)──▶ agg_order_reviews  (98,673: avg/min/max + latest_review_score)
```

Every arrow into an `agg_*` table is a `groupby(order_id)` — a many-to-one
reduction — computed once, in one place (`scripts/step2_04_build_canonical.py`),
never inline in a downstream query. A future KPI engine (Step 3) should read from
`agg_order_items`/`agg_order_payments`/`agg_order_reviews`, not re-derive them from
the `fact_*` tables, precisely so the aggregation logic — and its documented
business decisions (e.g. the review dedup rule) — isn't silently reimplemented
differently in a second place.

## fact_orders — full field list and where each comes from

| Field | Source | Notes |
|---|---|---|
| `order_id`, `customer_id`, `order_status` | raw `orders`, unchanged | |
| `purchase_timestamp` ← `order_purchase_timestamp` | raw `orders`, renamed | |
| `approved_timestamp` ← `order_approved_at` | raw `orders`, renamed | |
| `carrier_delivery_timestamp` ← `order_delivered_carrier_date` | raw `orders`, renamed | |
| `customer_delivery_timestamp` ← `order_delivered_customer_date` | raw `orders`, renamed | |
| `estimated_delivery_timestamp` ← `order_estimated_delivery_date` | raw `orders`, renamed | |
| `customer_unique_id`, `customer_state`, `customer_city` | denormalized from `dim_customer` via `customer_id` join | attributes of the customer, not measures — safe to denormalize |
| `delivery_days`, `carrier_days`, `delivery_delay_days` | derived, see §Delivery below | |
| `delivery_data_quality_flag`, `has_delivery_data` | derived, see §Delivery below | |
| `has_items`, `has_payment`, `has_review` | derived: `order_id` presence-check against `agg_order_items`/`agg_order_payments`/`agg_order_reviews` | booleans, not measures |
| `in_analytical_window` | derived: `purchase_timestamp`'s month ∈ [2017-01, 2018-08] | see `docs/ANALYTICAL_WINDOW.md` |

**No `revenue`, `payment_total`, or `review_score` column exists on `fact_orders`.**
This is deliberate — see the design principle above.

## Delivery fields — rules and quality flag

```
delivery_days        = customer_delivery_timestamp − purchase_timestamp   (days)
carrier_days          = carrier_delivery_timestamp  − purchase_timestamp   (days)
delivery_delay_days   = customer_delivery_timestamp − estimated_delivery_timestamp (days)
```

Missing timestamps produce `NULL` durations, **never 0** (verified by
`tests/test_delivery.py::test_missing_dates_produce_null_not_zero`).

`delivery_data_quality_flag` (priority order, highest wins):

1. **`INVALID_SEQUENCE`** — `delivery_days < 0` or `carrier_days < 0` (a delivery
   timestamp precedes the purchase timestamp). **166 orders** (0.17%), genuinely
   investigated, not silently dropped — see finding below.
2. **`MISSING_CUSTOMER_DATE`** — `customer_delivery_timestamp` is null. **2,964
   orders.**
3. **`MISSING_CARRIER_DATE`** — `carrier_delivery_timestamp` is null (and the above
   two don't apply). **1 order.**
4. **`VALID`** — none of the above. **96,310 orders** (96.85%).

`has_delivery_data` is `True` exactly when the flag is `VALID`.

### Investigated finding: the 166 `INVALID_SEQUENCE` orders

All 166 have `carrier_days < 0` (the customer-delivery leg is always logically
sound where present — `delivery_days` is never negative in this dataset). Breaking
down the magnitude:

- **121 of 166 (73%)** are within 1 hour of zero (e.g. −0.017 to −0.065 days,
  i.e. carrier date is recorded 1–90 minutes before the purchase timestamp) —
  consistent with clock-synchronization noise between whatever subsystems log
  "order placed" vs. "handed to carrier," not a business-logic error.
- **2 of 166** are more than a day off, including one extreme outlier
  (`7c48bb55e8e4f7e56d412e9653db37bc`: carrier date **2018-01-26**, purchase
  timestamp **2018-07-16** — 171 days apart), which is not plausibly clock skew
  and is most likely a genuine data-entry error in the source system. Not
  corrected here — reported and flagged, per this task's explicit instruction not
  to silently remove negative durations.

These 166 rows remain in `fact_orders` with the `INVALID_SEQUENCE` flag; a Step 3
KPI engine should exclude them from any *carrier*-time-specific metric while they
may still be safely included in delivery-day metrics (which are unaffected).

## Product category resolution (dim_product)

`category_translation` is joined with a **LEFT** join (verified: `dim_product` has
exactly 32,951 rows in and out — a join can only add or leave unchanged, never
drop, a row count for this to hold).

| `category_resolution_status` | Count | Meaning |
|---|---|---|
| `TRANSLATED` | 32,328 | Category present and found in `category_translation` |
| `NULL_CATEGORY` | 610 | `product_category_name` itself is null in the raw data |
| `UNTRANSLATED` | 13 | Category name present (2 distinct values: `pc_gamer`,
`portateis_cozinha_e_preparadores_de_alimentos`) but absent from `category_translation` |

`category_name_en` is `NULL` for both `NULL_CATEGORY` and `UNTRANSLATED` rows —
never silently filled with a placeholder string.

## Customer identity (dim_customer)

`customer_id` (order-scoped, 100% unique in `dim_customer` by construction — it's
the raw grain) and `customer_unique_id` (person-level, 96,096 distinct values
across 99,441 rows) are **both preserved as separate columns**. `dim_customer` is
**not** reduced to one row per person — doing so would destroy the ability to see
which order-scoped IDs belong to the same repeat customer. `fact_orders` denormalizes
`customer_unique_id` for convenience (verified consistent with `dim_customer` by
`tests/test_keys.py::test_fact_orders_customer_unique_id_denormalization_matches_dim_customer`),
but any customer-level (not order-level) analysis must `groupby("customer_unique_id")`
explicitly — there is no shortcut table that pre-collapses this.

## Anti-fan-out architecture

The risk (demonstrated concretely in Step 1's `RELATIONSHIP_GRAPH.md` and
re-verified independently again here): `order_payments` and `order_reviews` are
each **one-to-many** from `orders`. Joining two such one-to-many children directly
to each other (e.g. `order_items ⋈ order_payments`) before aggregating produces a
join that is many-to-many between the two children, and summing a line-item
measure afterward multiplies it.

**Structural safeguard:** the *only* place any cross-table sum happens in the
canonical layer is inside `build_agg_order_items` / `build_agg_order_payments` /
`build_agg_order_reviews` — each does exactly one `groupby(order_id).agg(...)`
against **one raw table**, never a join of two multi-row tables followed by a sum.
`fact_orders` (the join hub) carries **only pre-reduced, order-grain values** as
denormalized attributes (customer state/city) or booleans (`has_items`, etc.) —
never a raw sum that could be re-multiplied downstream.

**Proof, not just architecture:** `tests/test_fanout.py` actually performs the
naive join (`order_items ⋈ order_payments`, summed after joining) and asserts the
result is different from — specifically, larger than — the canonical
`agg_order_items` total, reproducing the exact same concrete example order
(`03ecec245220b63fd7f68c1737ba99ba`) found independently in both Step 1 passes.
It also asserts that re-joining the *already-aggregated* `agg_order_items` to the
multi-row `fact_payments`/`fact_reviews` tables and taking one row per order
(the correct pattern) reproduces the exact baseline total, while naively summing
after that same join does not — proving the aggregate-first architecture is what
prevents the bug, not mere convention.

## What is explicitly out of scope for this table set

No KPI, PVM, anomaly-detection, RAG, or agent logic reads or writes anything here.
`agg_order_items.item_price_total` is a *definition* (see
`docs/KPI_SEMANTICS_PREVIEW.md`), not a KPI computation — no rolling averages,
month-over-month deltas, or dashboards exist in `data/processed/`.
