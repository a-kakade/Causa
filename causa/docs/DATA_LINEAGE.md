# Data Lineage & Multi-Grain / Multi-Cadence Analysis

## 1. What this dataset actually is

The Olist Brazilian E-Commerce dataset is a **single relational export** — 9 CSV
files, all snapshotted at the same extraction time (file timestamps: 2021-10-01;
data content spans 2016-09 to 2018-10), from what is functionally **one transactional
system** (orders + line items + payments + reviews + a product/seller/customer
master). It is **not** multiple independently-sourced systems with genuinely
different refresh cadences — there is one true event stream (the order) observed
through several child tables.

This matters directly for the Round 2 brief's "heterogeneous sources with different
grains/cadences" requirement: **the raw data as-is does not satisfy that requirement
in the way the brief implies (e.g., a daily ops feed + a monthly finance close + a
weekly marketing spend file from genuinely separate systems).** What the dataset does
give us is several different **natural grains within one source**, which is a real
but weaker form of multi-grain heterogeneity. Both are documented below so the
distinction isn't glossed over.

## 2. Grains and cadences actually present

| Source (table) | Natural grain | Native cadence | Timestamp field | Freshness (relative to extraction) | Joinable dimensions |
|---|---|---|---|---|---|
| orders | 1 row = 1 order (event) | Event-level, irregular arrival | order_purchase_timestamp | Historical, ends 2018-10-17 | customer_id, order_status |
| order_items | 1 row = 1 line item (event) | Event-level | shipping_limit_date (not a business event date, a deadline) | Same window as orders | order_id, product_id, seller_id |
| order_payments | 1 row = 1 payment/installment (event) | Event-level | *(no payment timestamp column — see gap below)* | Same window (inferred from order) | order_id, payment_type |
| order_reviews | 1 row = 1 review (event) | Event-level, lagged after delivery | review_creation_date, review_answer_timestamp | Same window, review dates trail order dates by the review-request delay | order_id |
| products | 1 row = 1 SKU (entity/master) | Slowly-changing entity attributes (dimension, no history) | none | Static snapshot, no effective-dated versions | product_id, product_category_name |
| sellers | 1 row = 1 seller (entity/master) | Dimension, no history | none | Static snapshot | seller_id, seller_state |
| customers | 1 row = 1 order-scoped customer (entity/master) | Dimension, no history | none | Static snapshot | customer_id, customer_unique_id |
| geolocation | many rows = zip-prefix samples (reference) | Reference table, no time dimension at all | none | Static, undated | zip_code_prefix (after dedup) |
| category_translation | 1 row = 1 category (lookup) | Static lookup | none | Static | product_category_name |

**Derived/aggregate grains Causa can legitimately build on top (all deterministic,
verified in `scripts/kpi_temporal_eda.py`):**

| Derived grain | Cadence | Built from | Verified row counts |
|---|---|---|---|
| Order-fact (1 row/order, revenue+delivery+review joined) | Event-level | orders + order_items (aggregated) + reviews (last by answer date) | 99,441 |
| Daily KPI series | Daily | Order-fact resampled | 774 calendar days with ≥1 order |
| Weekly KPI series | Weekly (W-MON) | Order-fact resampled | ~111 weeks |
| Monthly KPI series | Monthly | Order-fact resampled | 26 months (2016-09 → 2018-10), only 2017-01 → 2018-08 (20 months) are volume-reliable — see Data Quality Report §2 |
| Category-month | Monthly × category | order_items + products, resampled | up to 73 categories × 20 reliable months |
| State-month | Monthly × seller_state or customer_state | order_items/orders + sellers/customers, resampled | up to 23–27 states × 20 reliable months |

## 3. Explicit gaps versus the brief's multi-cadence requirement

- **No independent marketing-spend, ad-impression, or campaign-calendar source.**
  Any "marketing driver" claim in Causa would be **unsupported by this dataset** —
  there is no spend, channel, or campaign data at all.
- **No macroeconomic, weather, holiday-calendar, or competitor-pricing source.**
  Seasonality can be *observed* in the order time series but cannot be *explained*
  by an external calendar without adding one.
- **No payment timestamp** in `order_payments` — only `order_approved_at` on
  `orders` anchors payment timing, so payment-cadence analysis (e.g., time-to-pay)
  is not possible at the payment-row grain, only at the order grain.
- **No slowly-changing dimension history** — `products`/`sellers`/`customers` are
  static snapshots with no effective-dated price/attribute changes, so "was this
  product's price always X" cannot be answered; only the price actually charged on
  each order_item is known.

## 4. Recommendation

The dataset genuinely supports **multi-grain analysis within one source** (event →
daily → weekly → monthly → category-month → state-month), which is real and
demonstrable (see `reports/kpi_timeseries_monthly.csv` and `kpi_timeseries_weekly.csv`).
It does **not** genuinely support **multi-cadence, multi-system reconciliation**
(e.g., reconciling a daily ops number against a monthly finance close from a
separate ledger) without adding at least one real external source. The minimum
external addition that would make that requirement genuinely satisfiable without
fabrication: a real Brazilian public holiday/Black-Friday calendar (freely
available, e.g. from Brazilian government sources) to reconcile against the observed
Nov 2017 order spike — see `INVESTIGATION_SCENARIOS.md`. Do not fabricate a
marketing-spend or finance-close file to satisfy this requirement; if the judges
require literal multi-system reconciliation, say so explicitly rather than
simulating it.

## 5. Source-to-KPI lineage (deterministic path only)

```
olist_order_items_dataset.csv (price, freight_value)
        │  groupby(order_id).sum()
        ▼
order-grain revenue, freight, quantity
        │  join order_status == 'delivered' filter (business rule, not automatic)
        │  join order_purchase_timestamp
        ▼
Daily/Weekly/Monthly KPI series (orders, revenue, AOV, freight, quantity)
        │  join products.product_category_name
        ▼
Category-month revenue / PVM decomposition inputs
        │  join sellers.seller_state / customers.customer_state
        ▼
State-month revenue, seller concentration

olist_orders_dataset.csv (order_purchase_timestamp, order_delivered_customer_date)
        │  subtract
        ▼
delivery_days (order-grain)
        │  resample
        ▼
Monthly avg delivery time KPI

olist_order_reviews_dataset.csv (review_score)
        │  groupby(order_id), last by review_answer_timestamp (dedup rule)
        │  resample
        ▼
Monthly avg review score / review volume KPI
```

Every arrow above is a real, reproducible pandas operation executed in
`scripts/kpi_temporal_eda.py` and `scripts/join_driver_anomaly_eda.py` — none of
this lineage is hypothetical.
