# Olist Data Dictionary

Status: **verified against the dataset in `data/raw/olist/`** via `scripts/profile_olist.py`
and `notebooks/01_olist_eda.ipynb` (profiled 2026-08-25). Column definitions are sourced
from the Olist Kaggle dataset documentation and confirmed against the actual data.

Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

## Table index

| Table | File | Grain | Row count |
|---|---|---|---|
| customers | `olist_customers_dataset.csv` | one row per order-customer | 99,441 |
| orders | `olist_orders_dataset.csv` | one row per order | 99,441 |
| order_items | `olist_order_items_dataset.csv` | one row per order line item | 112,650 |
| order_payments | `olist_order_payments_dataset.csv` | one row per payment installment/method per order | 103,886 |
| order_reviews | `olist_order_reviews_dataset.csv` | one row per review (not strictly 1:1 with order — see notes) | 99,224 |
| products | `olist_products_dataset.csv` | one row per product | 32,951 |
| sellers | `olist_sellers_dataset.csv` | one row per seller | 3,095 |
| geolocation | `olist_geolocation_dataset.csv` | one row per zip-code-prefix/lat/lng sample (many-to-one to zip prefix; 26.2% exact duplicates) | 1,000,163 |
| category_translation | `product_category_name_translation.csv` | one row per category name | 71 |

---

## customers — `olist_customers_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| customer_id | string (PK) | Key linking to `orders.customer_id`; unique per order, not per person | |
| customer_unique_id | string | Stable identifier for the actual customer across orders | Use this for customer-level KPIs (repeat rate, LTV) |
| customer_zip_code_prefix | string | First 5 digits of zip code | Joins to `geolocation.geolocation_zip_code_prefix` |
| customer_city | string | City name | |
| customer_state | string | 2-letter state code | |

## orders — `olist_orders_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| order_id | string (PK) | Unique order identifier | |
| customer_id | string (FK -> customers) | | |
| order_status | string | e.g. delivered, shipped, canceled, unavailable | Categorical — enumerate all values found |
| order_purchase_timestamp | datetime | When the order was placed | |
| order_approved_at | datetime | When payment was approved | Nullable |
| order_delivered_carrier_date | datetime | When handed to logistics partner | Nullable |
| order_delivered_customer_date | datetime | Actual delivery date | Nullable — null for undelivered orders |
| order_estimated_delivery_date | datetime | Estimated delivery date shown to customer | Used for on-time-delivery KPI |

## order_items — `olist_order_items_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| order_id | string (FK -> orders) | | Composite PK with order_item_id |
| order_item_id | int | Sequential line item number within the order | |
| product_id | string (FK -> products) | | |
| seller_id | string (FK -> sellers) | | |
| shipping_limit_date | datetime | Seller's shipping deadline | |
| price | float | Item price | Excludes freight |
| freight_value | float | Shipping cost for this item | |

## order_payments — `olist_order_payments_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| order_id | string (FK -> orders) | | Composite PK with payment_sequential |
| payment_sequential | int | Sequence number when multiple payment methods used | |
| payment_type | string | credit_card, boleto, voucher, debit_card, not_defined | |
| payment_installments | int | Number of installments | |
| payment_value | float | Amount for this payment record | Sum per order should reconcile with order total |

## order_reviews — `olist_order_reviews_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| review_id | string | Review identifier | Verify uniqueness — known to have some duplicates |
| order_id | string (FK -> orders) | | An order can have more than one review |
| review_score | int | 1–5 | |
| review_comment_title | string | Optional free text | High null rate expected |
| review_comment_message | string | Optional free text | High null rate expected |
| review_creation_date | datetime | | |
| review_answer_timestamp | datetime | When Olist/seller responded | |

## products — `olist_products_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| product_id | string (PK) | | |
| product_category_name | string (FK -> category_translation) | Portuguese category name | Nullable for some products |
| product_name_lenght | int | Character count of product name | Note: source dataset misspells "length" |
| product_description_lenght | int | Character count of description | Note: source misspelling preserved |
| product_photos_qty | int | | |
| product_weight_g | float | | |
| product_length_cm | float | | |
| product_height_cm | float | | |
| product_width_cm | float | | |

## sellers — `olist_sellers_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| seller_id | string (PK) | | |
| seller_zip_code_prefix | string | | Joins to `geolocation` |
| seller_city | string | | |
| seller_state | string | | |

## geolocation — `olist_geolocation_dataset.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| geolocation_zip_code_prefix | string | Not unique — many lat/lng samples per prefix | Aggregate (e.g. mean/median) before joining |
| geolocation_lat | float | | |
| geolocation_lng | float | | |
| geolocation_city | string | | |
| geolocation_state | string | | |

## category_translation — `product_category_name_translation.csv`

| Column | Type | Description | Notes |
|---|---|---|---|
| product_category_name | string (PK) | Portuguese name | Joins to `products.product_category_name` |
| product_category_name_english | string | English translation | |

---

## Findings from EDA (previously open questions)

- **`customer_id` vs `customer_unique_id`**: 99,441 order-scoped `customer_id` values map to 96,096 distinct `customer_unique_id` values — confirms repeat customers exist; always use `customer_unique_id` for customer-level analysis.
- **`order_reviews.review_id` duplicates**: 814 duplicate `review_id` values found; 547 orders have more than one review row. Not a clean 1:1 with orders — see `DATA_MODEL.md` for the proposed dedup rule.
- **`order_status` distinct values** (8 total): delivered (97.0%), shipped (1.1%), canceled (0.6%), unavailable (0.6%), invoiced (0.3%), processing (0.3%), created (0.0%), approved (0.0%). Full breakdown in `DATA_QUALITY_REPORT.md`.
- **`payment_value` vs `price + freight_value` reconciliation**: not yet reconciled per order — remains an open follow-up (see `DATA_QUALITY_REPORT.md` §10). 9 payment rows have `payment_value == 0`.
- **`product_category_name` null rate**: 1.85% (610 of 32,951 products) — handle as an explicit "uncategorized" bucket. Additionally, 2 category names present in `products` are missing from `category_translation` (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`).
