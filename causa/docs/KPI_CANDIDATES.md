# KPI Candidates

Every KPI below was computed against the reliable window (**2017-01 to 2018-08** —
see `DATA_QUALITY_REPORT.md` §2) using `scripts/kpi_temporal_eda.py`. Historical
depth given is measured, not assumed. "Reliability" reflects whether the KPI's
inputs are complete/clean enough to trust, per the quality audit.

| KPI | Definition | Formula (verified against schema) | Source | Grain | Historical depth | Reliability |
|---|---|---|---|---|---|---|
| Orders | Count of orders placed | `COUNT(DISTINCT order_id)` | orders | Daily/Weekly/Monthly | 20 reliable months | High — order_id has 0 nulls, 0 dupes |
| Revenue | Sum of line-item price | `SUM(order_items.price)` grouped to order, then summed by period | order_items | Daily/Weekly/Monthly, by category/state | 20 reliable months | High — 99.61% reconciles with order_payments; excludes the 775 orders with payments but no items (by design, not oversight) |
| Freight | Sum of shipping cost | `SUM(order_items.freight_value)` | order_items | Same as Revenue | 20 reliable months | High |
| GMV | Revenue + Freight | `SUM(price) + SUM(freight_value)` | order_items | Same as Revenue | 20 reliable months | High |
| Average Order Value (AOV) | Revenue per order | `Revenue / Orders` (period) | derived | Daily/Weekly/Monthly | 20 reliable months | High, but sensitive to the 0.78% zero-item orders being excluded from the denominator correctly |
| Quantity | Count of line items sold | `COUNT(order_items.order_item_id)` | order_items | Same as Revenue | 20 reliable months | High |
| Avg Delivery Time | Days from purchase to customer delivery | `AVG(order_delivered_customer_date - order_purchase_timestamp)` | orders | Daily/Weekly/Monthly | 20 reliable months, `delivered` orders only | Medium — survivorship-biased toward completed deliveries (2.98% of orders have no delivery date and are necessarily excluded) |
| On-Time Delivery Rate | % delivered on/before estimate | `AVG(order_delivered_customer_date <= order_estimated_delivery_date)` | orders | Monthly | 20 reliable months | Medium — same survivorship caveat |
| Avg Review Score | Mean star rating | `AVG(review_score)`, deduped to last review per order by `review_answer_timestamp` | order_reviews | Daily/Weekly/Monthly, by category/state | 20 reliable months | Medium — 0.77% of orders have no review; 0.55% have a dedup rule applied (not raw) |
| Review Volume | Count of reviews | `COUNT(review_score)` (post-dedup) | order_reviews | Daily/Weekly/Monthly | 20 reliable months | High |
| Seller Revenue Concentration | Share of revenue from top-N sellers | `SUM(price) for top-20 sellers / total SUM(price)` | order_items + sellers | Monthly, by state | 20 reliable months | High — measured at 21.28% for top 20 of 3,095 sellers |
| Repeat Purchase Rate | % of unique customers with >1 order | `COUNT(customer_unique_id with order_count > 1) / COUNT(DISTINCT customer_unique_id)` | orders + customers | Cohort/monthly | 20 reliable months | Medium — requires `customer_unique_id`, not `customer_id`; only 3.12% of unique customers repeat in this dataset, which itself is a finding (see `EDA_REPORT.md`) |

## What was explicitly checked, not assumed

- **Revenue formula** — verified `SUM(order_items.price)` reconciles with
  `order_payments.payment_value` for 99.61% of orders present in both, and verified
  the naive multi-table join inflates it 4.04% (`RELATIONSHIP_GRAPH.md`). Only after
  that check was `SUM(order_items.price)` adopted as the definition.
- **AOV, Freight, Quantity** — all derived from the same reconciled `order_items`
  aggregation, so they inherit the same reliability.
- **Delivery-time KPIs** — checked for delivery-before-purchase logical violations
  (none found) and for null-rate correlation with order status (confirmed: nulls
  concentrate in non-delivered orders, which is the expected mechanism, not a data
  defect, but does mean the KPI only describes successful deliveries).
- **Review KPIs** — checked `review_id` uniqueness (not unique; 814 dupes) and
  applied an explicit "last review by answer timestamp per order" dedup rule before
  computing any review KPI; the KPI values above use that dedup, not raw
  `AVG(review_score)` over all 99,224 rows (which would double-count 547 orders).

## KPI definition template applied per candidate (Revenue example, per the brief)

1. **What does it measure?** Total realized transaction value at the item-price
   grain, before financing/interest, before freight.
2. **Natural grain:** order → item → category/seller/state/day, fully additive up the
   hierarchy (verified: SUM(item price) per order, summed again by any of those
   dimensions, is consistent because the source is one flat fact table with no
   double-counting once order_items is pre-aggregated — see fan-out rule).
3. **Explanatory dimensions:** product_category_name, seller_state/seller_id,
   customer_state, payment_type (via order_payments, joined carefully), order month.
4. **Deterministic drivers:** Price (avg item price), Volume (item count), Mix
   (category revenue share shift) — see PVM decomposition in
   `INVESTIGATION_SCENARIOS.md`. All computed directly from `order_items` +
   `products`, no external data needed.
5. **Statistically-inferred drivers:** none required for the core PVM bridge — it is
   fully deterministic arithmetic, not a regression. Statistical treatment (e.g.,
   confidence intervals on month-over-month changes, seasonality decomposition)
   would strengthen but is not required to defend the base decomposition.
6. **Missing data:** no promotional/list-price field to separate discounting from
   organic price change within a category (see `RELATIONSHIP_GRAPH.md` /
   `DATA_LINEAGE.md`); no marketing spend to attribute demand growth to a channel.

## KPIs considered and rejected as NOT currently defensible

- **Customer Lifetime Value (LTV)** — computable in principle from
  `customer_unique_id`, but with only 3.12% of unique customers repeating within
  this ~2-year window and no cost/margin data (only price, not cost of goods),
  a genuine LTV (revenue net of cost, projected) **cannot be defended** — only a
  simple historical revenue-per-customer figure can, and it should be labeled as
  such, not as "LTV."
- **Profit / Margin** — **not supported at all.** No cost-of-goods, commission-rate,
  or fee-schedule field exists anywhere in the dataset. Any "profit" or "margin" KPI
  would be fabricated. Revenue and GMV are the ceiling of what this data supports.
- **Marketing-attributed Revenue** — **not supported.** No channel/campaign/spend
  data exists. Do not claim any KPI movement is "driven by marketing" from this
  dataset alone.
- **Return / Refund Rate** — **not supported.** `order_status` includes `canceled`
  and `unavailable`, which are adjacent concepts, but there is no explicit
  return/refund event or reason-code field.
