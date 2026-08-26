# Relationship Graph

All numbers computed by `scripts/profile_olist.py` (relationship cardinality) and
`scripts/join_driver_anomaly_eda.py` (fan-out demo) against the real dataset,
**2026-08-26**. See `data/raw/olist/_profile_summary.json` and
`reports/join_driver_anomaly_summary.json`.

## Entity relationship diagram (observed, not assumed)

```
customers_unique (96,096)
      │ 1
      │ (customer_unique_id)
      ▼ 1..17   (avg 1.03, median 1, 3.12% of customers place >1 order)
   customers (99,441 rows = 1 per order-scoped customer_id)
      │ 1
      │ (customer_id)
      ▼ exactly 1  (0 orphans, every order has exactly one customer_id)
    orders (99,441)
      │
      ├── 1:0..21 ──▶ order_items (112,650)   [avg 1.13/order, median 1, 9.86% multi-item,
      │                  │                       0.78% of orders (775) have ZERO items]
      │                  ├── N:1 ──▶ products (32,951)      [avg 3.42 items/product, median 1,
      │                  │                                    45.02% of products appear >1×]
      │                  └── N:1 ──▶ sellers (3,095)        [avg 36.40 items/seller, median 8,
      │                                                       83.55% of sellers appear >1×]
      │
      ├── 1:0..29 ──▶ order_payments (103,886) [avg 1.04/order, median 1, 2.98% multi-payment
      │                                          (installments/split payment), 0% zero-payment
      │                                          orders, but 1 order has a payment row with no
      │                                          matching order in this join direction]
      │
      └── 1:0..3  ──▶ order_reviews (99,224)   [avg 0.998/order, median 1, 0.77% of orders have
                                                  no review, 0.55% have >1 review — review_id is
                                                  NOT globally unique: 814 duplicate review_id
                                                  values, 547 orders with >1 review row]

products (32,951) ──N:1──▶ category_translation (71)  [2 orphan category names in products:
                                                          'pc_gamer', 'portateis_cozinha_e_...']

customers.customer_zip_code_prefix ──?:N──▶ geolocation.geolocation_zip_code_prefix
sellers.seller_zip_code_prefix     ──?:N──▶ geolocation.geolocation_zip_code_prefix
   [geolocation has no row-level key; 26.2% exact-duplicate rows; must aggregate to
    one row per zip prefix before this becomes a usable join — NOT evaluated as a
    clean join here because the raw table cannot be joined 1:1 without that step]
```

## Join coverage table

For every proposed join: left rows, right rows, matched rows, unmatched rows,
match %, and multiplicity — computed directly, not estimated.

| Join | Left rows | Right rows | Matched (left rows with ≥1 match) | Unmatched left | Match % | Multiplicity |
|---|---|---|---|---|---|---|
| orders ⟕ order_items | 99,441 | 112,650 | 98,666 | 775 (0.78%) | 99.22% | 1 : 0..21 |
| orders ⟕ order_payments | 99,441 | 103,886 | 99,441 | 0 | 100.00% | 1 : 1..29 |
| orders ⟕ order_reviews | 99,441 | 99,224 | 98,673 | 768 (0.77%) | 99.23% | 1 : 0..3 |
| customers_unique ⟕ orders | 96,096 | 99,441 | 96,096 | 0 | 100.00% | 1 : 1..17 |
| products ⟕ order_items | 32,951 | 112,650 | 32,951 | 0 | 100.00% | 1 : 0..527 (735 products have 0 delivered transactions — see `INVESTIGATION_SCENARIOS.md` §Sparse history) |
| sellers ⟕ order_items | 3,095 | 112,650 | 3,095 | 0 | 100.00% | 1 : 0..2,033 |
| products ⟕ category_translation | 32,951 | 71 | 32,339 (98.15%, excl. 610 null-category products) | 13 rows / 2 categories orphaned | 99.96% (by row) | N : 1 |

## Fan-out / revenue-multiplication risk — concretely demonstrated

Because `order_payments` and `order_reviews` both have a **1-to-many** relationship
with `orders` (not 1-to-1), joining them alongside `order_items` before aggregating
multiplies fact rows and, if a measure like `price` is summed after the join, inflates
the total.

**Measured effect on this exact dataset:**

| | Total revenue (SUM order_items.price) |
|---|---|
| Correct (aggregate order_items to order grain first) | 13,591,643.70 |
| Naive (join orders ⋈ items ⋈ payments ⋈ reviews, then sum price) | 14,141,001.32 |
| Inflation | **+4.04%** |

**Concrete single-order example:** order `03ecec245220b63fd7f68c1737ba99ba` has 2
order_items (true price total = 298.90) and 2 order_payments rows. Joining
items × payments before aggregating produces 4 rows; summing `price` over those 4
rows yields 597.80 — exactly 2× the true value, because the payment row count (2)
multiplied the item rows.

**Rule for Causa's deterministic KPI layer:** always aggregate `order_items` to one
row per `order_id` (`SUM(price)`, `SUM(freight_value)`, `COUNT(order_item_id)`)
**before** joining to `order_payments` or `order_reviews`. Never sum a
line-item-grain measure after a join to a table with 1:many cardinality relative to
the order.

## Relationship type summary

| Relationship | Type | Notes |
|---|---|---|
| customers_unique → customers | 1 : many | A real customer can have multiple order-scoped `customer_id`s |
| customers → orders | 1 : 1 | Confirmed: every `customer_id` appears exactly once in `customers`, and `orders.customer_id` has zero orphans against it |
| orders → order_items | 1 : many (0..21) | 0.78% of orders have zero items — must not be zero-filled, must be excluded from item-level revenue |
| orders → order_payments | 1 : many (1..29) | Every order has ≥1 payment row |
| orders → order_reviews | 1 : many (0..3), intended 1:1 | review_id not globally unique — needs an explicit dedup rule to be treated as 1:1 |
| order_items → products | many : 1 | |
| order_items → sellers | many : 1 | |
| products → category_translation | many : 1 | Imperfect: 2 categories unmatched |
| order_items ↔ order_payments (via order) | many : many | Never join these two directly without pre-aggregating one side — this is the fan-out risk above |
