# Causa Data Model — Proposed (Draft, Olist Foundation)

Status: **draft, confirmed against `DATA_QUALITY_REPORT.md` findings from the dataset in
`data/raw/olist/`** (profiled 2026-08-25). This document proposes how the raw Olist
tables map to entities/grain for the future Causa data model and KPI layer. No
implementation (database, ETL, application code) happens in this milestone — this is a
design artifact only.

## Purpose

Once the Olist dataset is validated (see `DATA_QUALITY_REPORT.md`), this document
should describe the target logical model: fact tables, dimension tables, grain, and the
relationships between them, so a future milestone can implement the Causa data model
and KPI layer against it with confidence.

## Source tables recap

| Raw table | Proposed role |
|---|---|
| orders | Order fact anchor (order-level lifecycle & status) |
| order_items | Line-item fact (finest grain for revenue/product KPIs) |
| order_payments | Payment fact (order can have multiple payment rows) |
| order_reviews | Review fact (order can have multiple/duplicate reviews — TBD) |
| customers | Customer dimension (note: customer_id vs customer_unique_id) |
| products | Product dimension |
| sellers | Seller dimension |
| geolocation | Geography reference (zip-prefix level, needs aggregation) |
| category_translation | Category name lookup (PT -> EN) |

## Confirmed grain decisions (from EDA)

- **Order fact**: one row per `order_id` (from `orders`, 99,441 rows, clean PK), carrying status and lifecycle timestamps. Zero orphan `customer_id` references.
- **Order line item fact**: one row per (`order_id`, `order_item_id`) — 112,650 rows, clean composite PK — carrying price, freight, product_id, seller_id. This is the primary grain for revenue and product KPIs. Zero orphan `product_id`/`seller_id` references.
- **Payment fact**: one row per (`order_id`, `payment_sequential`) — 103,886 rows, clean composite PK. An order can have multiple payment rows (split payments/installments); aggregate to order-level total payment value for order-level KPIs. 9 rows have `payment_value == 0` — flag/investigate before use.
- **Review fact**: `review_id` is **not** a clean primary key — 814 duplicate `review_id` values and 547 orders with more than one review row were found. Decision: treat review as a fact keyed by (`review_id`, `order_id`) rather than assuming 1:1 with orders; when a single review-per-order is needed, deduplicate by keeping the row with the latest `review_answer_timestamp`.
- **Customer dimension**: keyed by `customer_unique_id` for true customer identity (96,096 distinct people across 99,441 order-scoped `customer_id` values — confirms repeat customers exist); `customer_id` is order-scoped and must not be used as the customer grain for LTV/repeat-purchase KPIs.
- **Product dimension**: keyed by `product_id` (32,951 rows, clean PK), enriched with English category name via `category_translation`. 610 products (1.85%) have null category — model as an explicit "uncategorized" bucket. 2 category names (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`) have no translation row — patch the lookup table or fall back to the Portuguese name.
- **Seller dimension**: keyed by `seller_id` (3,095 rows, clean PK).
- **Geography reference**: `geolocation` (1,000,163 rows) is 26.2% exact duplicates and has many lat/lng samples per zip prefix (19,015 distinct prefixes). Must aggregate to one row per zip-code-prefix (mean/median lat/lng, mode city/state) before use as a joinable dimension.

## Candidate entity relationship sketch (draft)

```
customers (dim, keyed by customer_unique_id)
    |
    | 1:many (a customer places many orders)
    v
orders (fact anchor, keyed by order_id) ---- FK customer_id --> customers
    |                                   \
    | 1:many                             \ 1:many
    v                                      v
order_items (fact, order_id+item_id)   order_payments (fact, order_id+seq)
    |        \                              order_reviews (fact, review_id -> order_id)
    |         \
    v          v
products     sellers
  (dim)        (dim)
    |
    v
category_translation (lookup)
```

*(This is a first-pass sketch, not final. Confirm cardinalities and any many-to-many
edge cases against `DATA_QUALITY_REPORT.md` before treating as authoritative.)*

## Candidate KPI directions this model should support (for future milestones — not built now)

- Revenue / GMV over time, by category, by seller, by state.
- Order fulfillment: on-time delivery rate (`order_delivered_customer_date` vs `order_estimated_delivery_date`).
- Customer behavior: repeat purchase rate, customer lifetime value (requires `customer_unique_id` grain).
- Payment behavior: distribution of payment types and installment counts.
- Review/satisfaction: average review score by category, seller, delivery performance.
- Logistics: freight cost as % of item price, delivery time distributions.

## Open design questions

- [ ] Should `order_payments` be pre-aggregated to one row per order before entering the model, or kept at native grain with a separate payment-method breakdown? (103,886 payment rows vs. 99,440 distinct orders paid — most orders have exactly one payment row, but a meaningful minority split across methods/installments.)
- [ ] How should the ~3% of orders with `order_status` other than "delivered" (625 canceled, 609 unavailable, 1,107 shipped, 314 invoiced, 301 processing, 5 created, 2 approved) be treated in revenue/KPI calculations?
- [ ] Is `geolocation` needed as a dimension at all for early KPIs, or can `customer_state`/`seller_state` suffice initially? (State-level data is already clean and directly usable with zero modeling overhead; zip-level geolocation requires the aggregation step noted above.)
- [ ] How to handle the 610 products (1.85%) with null `product_category_name`?
- [ ] What is the review dedup rule for the 547 orders with multiple review rows — latest `review_answer_timestamp`, highest score, or model as a proper 1:many fact?

## Next steps

Grain and referential integrity are now confirmed against the actual dataset (see
`DATA_QUALITY_REPORT.md`). Remaining work before this model is final is resolving the
open design questions above — none of them block starting KPI-layer design, but they
should be decided before implementation begins in a future milestone.
