# Data Lineage V2 — Canonical Layer

Every field in every canonical table traces to a raw table, a raw column, and an
explicit transformation. If a field is not listed here, it should not exist in
`data/processed/` — this document is the contract. Built by
`scripts/step2_04_build_canonical.py`.

Legend for **Transformation**: `PASSTHROUGH` = copied unchanged; `RENAME` = column
renamed only; `DERIVED` = computed from other fields; `JOIN` = brought in via a join
to another raw/canonical table; `SURROGATE` = newly generated, has no raw source.

## dim_customer ← `olist_customers_dataset.csv`

| Canonical field | Raw source | Transformation |
|---|---|---|
| customer_id | customers.customer_id | PASSTHROUGH |
| customer_unique_id | customers.customer_unique_id | PASSTHROUGH |
| customer_zip_code_prefix | customers.customer_zip_code_prefix | PASSTHROUGH |
| customer_city | customers.customer_city | PASSTHROUGH |
| customer_state | customers.customer_state | PASSTHROUGH |
| customer_identity_valid | customers.customer_id, customers.customer_unique_id | DERIVED: `customer_id.notna() & customer_unique_id.notna()` |

## dim_product ← `olist_products_dataset.csv` ⋈ `product_category_name_translation.csv`

| Canonical field | Raw source | Transformation |
|---|---|---|
| product_id | products.product_id | PASSTHROUGH |
| category_name_pt | products.product_category_name | RENAME |
| category_name_en | category_translation.product_category_name_english | JOIN (LEFT, on product_category_name = category_translation.product_category_name; utf-8-sig encoding, see §16) |
| category_resolution_status | products.product_category_name (null check) + join match indicator | DERIVED: NULL_CATEGORY if source category is null; UNTRANSLATED if non-null but no translation row matched; else TRANSLATED |
| product_name_lenght | products.product_name_lenght | PASSTHROUGH (source misspelling of "length" preserved, per Step 1 finding — not silently corrected) |
| product_description_lenght | products.product_description_lenght | PASSTHROUGH (same misspelling note) |
| product_photos_qty | products.product_photos_qty | PASSTHROUGH |
| product_weight_g | products.product_weight_g | PASSTHROUGH |
| product_length_cm | products.product_length_cm | PASSTHROUGH |
| product_height_cm | products.product_height_cm | PASSTHROUGH |
| product_width_cm | products.product_width_cm | PASSTHROUGH |

## dim_seller ← `olist_sellers_dataset.csv`

| Canonical field | Raw source | Transformation |
|---|---|---|
| seller_id | sellers.seller_id | PASSTHROUGH |
| seller_zip_code_prefix | sellers.seller_zip_code_prefix | PASSTHROUGH |
| seller_city | sellers.seller_city | PASSTHROUGH |
| seller_state | sellers.seller_state | PASSTHROUGH |

## fact_orders ← `olist_orders_dataset.csv` ⋈ `olist_customers_dataset.csv` (+ has_/in_window flags derived against agg_* tables)

| Canonical field | Raw source | Transformation |
|---|---|---|
| order_id | orders.order_id | PASSTHROUGH |
| customer_id | orders.customer_id | PASSTHROUGH |
| order_status | orders.order_status | PASSTHROUGH |
| purchase_timestamp | orders.order_purchase_timestamp | RENAME |
| approved_timestamp | orders.order_approved_at | RENAME |
| carrier_delivery_timestamp | orders.order_delivered_carrier_date | RENAME |
| customer_delivery_timestamp | orders.order_delivered_customer_date | RENAME |
| estimated_delivery_timestamp | orders.order_estimated_delivery_date | RENAME |
| customer_unique_id | customers.customer_unique_id | JOIN (on customer_id, LEFT — verified 100% match rate in Step 1, so LEFT vs INNER is moot here but LEFT is used defensively) |
| customer_state | customers.customer_state | JOIN (same) |
| customer_city | customers.customer_city | JOIN (same) |
| delivery_days | purchase_timestamp, customer_delivery_timestamp | DERIVED: `(customer_delivery_timestamp − purchase_timestamp).days`; NULL if either input is NULL |
| carrier_days | purchase_timestamp, carrier_delivery_timestamp | DERIVED: same pattern |
| delivery_delay_days | customer_delivery_timestamp, estimated_delivery_timestamp | DERIVED: same pattern |
| delivery_data_quality_flag | delivery_days, carrier_days, carrier_delivery_timestamp (null check), customer_delivery_timestamp (null check) | DERIVED: priority rule, see `CANONICAL_DATA_MODEL.md` §Delivery |
| has_delivery_data | delivery_data_quality_flag | DERIVED: `== "VALID"` |
| has_items | order_id existence in agg_order_items | DERIVED (JOIN presence-check) |
| has_payment | order_id existence in agg_order_payments | DERIVED (JOIN presence-check) |
| has_review | order_id existence in agg_order_reviews | DERIVED (JOIN presence-check) |
| in_analytical_window | purchase_timestamp (month) | DERIVED: month ∈ [2017-01, 2018-08], per `reports/step2_window_analysis.json` |

## fact_order_items ← `olist_order_items_dataset.csv`

| Canonical field | Raw source | Transformation |
|---|---|---|
| order_id, order_item_id, product_id, seller_id, price, freight_value | order_items.* (same names) | PASSTHROUGH |
| shipping_limit_date | order_items.shipping_limit_date | PASSTHROUGH (parsed to datetime at load time) |

## fact_payments ← `olist_order_payments_dataset.csv`

| Canonical field | Raw source | Transformation |
|---|---|---|
| order_id, payment_sequential, payment_type, payment_installments, payment_value | order_payments.* (same names) | PASSTHROUGH |

## fact_reviews ← `olist_order_reviews_dataset.csv`

| Canonical field | Raw source | Transformation |
|---|---|---|
| review_row_id | *(none)* | SURROGATE: 0-indexed row number, added because `review_id` is not unique (814 duplicates, verified Step 1) |
| review_id, order_id, review_score, review_comment_title, review_comment_message, review_creation_date, review_answer_timestamp | order_reviews.* (same names) | PASSTHROUGH |
| has_text | review_comment_message | DERIVED: `.fillna("").str.strip() != ""` |

## agg_order_items ← `olist_order_items_dataset.csv`, `groupby(order_id)`

| Canonical field | Raw source | Transformation |
|---|---|---|
| order_id | order_items.order_id | GROUP KEY |
| item_count | order_items.order_item_id | DERIVED: `count()` per order |
| item_price_total | order_items.price | DERIVED: `sum()` per order — **this is CAUSA_REVENUE, see `KPI_SEMANTICS_PREVIEW.md`** |
| item_freight_total | order_items.freight_value | DERIVED: `sum()` per order |
| item_gmv_total | item_price_total, item_freight_total | DERIVED: `item_price_total + item_freight_total` |
| distinct_product_count | order_items.product_id | DERIVED: `nunique()` per order |
| distinct_seller_count | order_items.seller_id | DERIVED: `nunique()` per order |

Orders absent from this table (775 of 99,441) have zero `order_items` rows in the
raw data — they are **absent**, not present with zero values. Detect via
`fact_orders.has_items == False`.

## agg_order_payments ← `olist_order_payments_dataset.csv`, `groupby(order_id)`

| Canonical field | Raw source | Transformation |
|---|---|---|
| order_id | order_payments.order_id | GROUP KEY |
| total_payment_value | order_payments.payment_value | DERIVED: `sum()` per order |
| payment_count | order_payments.payment_sequential | DERIVED: `count()` per order |
| payment_types | order_payments.payment_type | DERIVED: sorted, comma-joined set of distinct values per order (e.g. an order paid partly by voucher and partly by credit_card shows `"credit_card,voucher"`) |
| max_installments | order_payments.payment_installments | DERIVED: `max()` per order |

Orders absent from this table (1 of 99,441) have zero payment rows in the raw
data — absent, not zero-filled. Detect via `fact_orders.has_payment == False`.

## agg_order_reviews ← `olist_order_reviews_dataset.csv`, `groupby(order_id)` + one dedup pass

| Canonical field | Raw source | Transformation |
|---|---|---|
| order_id | order_reviews.order_id | GROUP KEY |
| review_count | order_reviews.review_id | DERIVED: `count()` per order |
| avg_review_score | order_reviews.review_score | DERIVED: `mean()` per order (true aggregate over ALL reviews, not a dedup) |
| min_review_score / max_review_score | order_reviews.review_score | DERIVED: `min()` / `max()` per order |
| latest_review_score | order_reviews.review_score | DERIVED: score of the row with `max(review_answer_timestamp)` per order — the chosen dedup strategy, see `REVIEW_GOVERNANCE.md` |
| latest_review_id | order_reviews.review_id | DERIVED: `review_id` of that same latest-by-answer-timestamp row — traceability pointer back into `fact_reviews` |
| has_review_text | order_reviews.review_comment_message | DERIVED: `any()` of non-empty message across all of that order's reviews |
| first_review_creation_date | order_reviews.review_creation_date | DERIVED: `min()` per order |
| last_review_answer_timestamp | order_reviews.review_answer_timestamp | DERIVED: `max()` per order |

Orders absent from this table (768 of 99,441) have zero review rows in the raw
data — absent, not zero/null-score-filled. Detect via
`fact_orders.has_review == False`.

## Example trace (worked, per this task's standard)

**Claim:** "Order `03ecec245220b63fd7f68c1737ba99ba` has CAUSA_REVENUE of R$298.90."

```
data/processed/agg_order_items.parquet
  → row where order_id == "03ecec245220b63fd7f68c1737ba99ba"
  → item_price_total == 298.90
      ↑ DERIVED: sum(price) grouped by order_id
data/raw/olist/olist_order_items_dataset.csv
  → rows where order_id == "03ecec245220b63fd7f68c1737ba99ba"
  → 2 rows, price column sums to 298.90
```

Every canonical field in this document can be traced the same way — raw table,
raw column, one named transformation, no unexplained step in between.
