# Olist Data Dictionary

Status: generated and verified directly against the real dataset in `data/raw/olist/`
(source: `archive.zip`, the Kaggle "Brazilian E-Commerce Public Dataset by Olist," raw
file timestamps 2021-10-01) via `scripts/profile_olist.py` on **2026-08-26**. Every
Null % / Unique % value below is computed from the actual CSVs, not estimated.
Column *meanings* are sourced from Olist's published Kaggle documentation and are
marked "inferred" only where the source docs don't state them explicitly and the
description was reasoned from data behavior instead.

Source: https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce

## Table index

| Table | File | Grain (observed) | Rows | Cols |
|---|---|---|---|---|
| customers | `olist_customers_dataset.csv` | one row per order-scoped customer (see caveat below — **not** one row per real person) | 99,441 | 5 |
| orders | `olist_orders_dataset.csv` | one row per order | 99,441 | 8 |
| order_items | `olist_order_items_dataset.csv` | one row per order line item | 112,650 | 7 |
| order_payments | `olist_order_payments_dataset.csv` | one row per payment installment/method used on an order | 103,886 | 5 |
| order_reviews | `olist_order_reviews_dataset.csv` | intended: one row per review per order — **not actually clean**, 814 duplicate `review_id`s, 547 orders with >1 review row | 99,224 | 7 |
| products | `olist_products_dataset.csv` | one row per product SKU | 32,951 | 9 |
| sellers | `olist_sellers_dataset.csv` | one row per seller | 3,095 | 4 |
| geolocation | `olist_geolocation_dataset.csv` | many rows per zip-code prefix (raw lat/lng samples, not deduplicated — 26.2% exact-duplicate rows) | 1,000,163 | 5 |
| category_translation | `product_category_name_translation.csv` | one row per Portuguese category name | 71 | 2 |

---

## customers — `olist_customers_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| customer_id | string | Order-scoped customer key. **Inferred (confirmed by data):** re-issued per order, not per person. | `06b8999e2fba1a1fbc88172c00ba8bc7` | 0.0 | 100.0 | PK |
| customer_unique_id | string | Stable identifier for the real customer across orders. | `861eff4711a542e4b93843c6dd7febb0` | 0.0 | 96.64 | Candidate natural key (not unique per row — 99,441 rows map to 96,096 distinct values) |
| customer_zip_code_prefix | int | First 5 digits of the customer's zip code. | `14409` | 0.0 | 15.08 | FK candidate → geolocation (many-to-many after geolocation dedup) |
| customer_city | string | City name, free text (not standardized — see quality report on casing/accents). | `franca` | 0.0 | 4.14 | — |
| customer_state | string | 2-letter Brazilian state code. | `SP` | 0.0 | 0.03 | Categorical dimension (27 states) |

## orders — `olist_orders_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| order_id | string | Unique order identifier. | `e481f51cbdc54678b7cc49136f2d6af7` | 0.0 | 100.0 | PK |
| customer_id | string | FK to customers. | `9ef432eb6251297304e76186b10a928d` | 0.0 | 100.0 | FK → customers |
| order_status | string | Order lifecycle status; 8 distinct values observed (delivered 97.02%, shipped 1.11%, canceled 0.63%, unavailable 0.61%, invoiced 0.32%, processing 0.30%, created 0.01%, approved 0.00%). | `delivered` | 0.0 | 0.01 | Categorical dimension |
| order_purchase_timestamp | datetime | When the order was placed. Range: 2016-09-04 to 2018-10-17. | `2017-10-02 10:56:33` | 0.0 | 99.43 | Primary temporal anchor |
| order_approved_at | datetime | When payment was approved. | `2017-10-02 11:07:15` | 0.16 | 91.24 | — |
| order_delivered_carrier_date | datetime | Handoff to logistics carrier. | `2017-10-04 19:55:00` | 1.79 | 81.47 | — |
| order_delivered_customer_date | datetime | Actual delivery date/time. Null = not yet/never delivered (**expected**, correlates with non-`delivered` status). | `2017-10-10 21:25:13` | 2.98 | 96.20 | — |
| order_estimated_delivery_date | date | Estimate shown to the customer at purchase time. | `2017-10-18` | 0.0 | 0.46 | Used for on-time-delivery KPI |

## order_items — `olist_order_items_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| order_id | string | FK to orders. | `00010242fe8c5a6d1ba2dd792cb16214` | 0.0 | 87.59 | FK → orders; composite PK with order_item_id |
| order_item_id | int | Sequential line number within the order (1..21 observed). | `1` | 0.0 | 0.02 | Composite PK w/ order_id |
| product_id | string | FK to products. | `4244733e06e7ecb4970a6e2683c13e61` | 0.0 | 29.25 | FK → products |
| seller_id | string | FK to sellers. | `48436dade18ac8b2bce089ec2a041202` | 0.0 | 2.75 | FK → sellers |
| shipping_limit_date | datetime | Seller's shipping deadline. **Anomaly:** max value 2020-04-09, ~18 months past the last order in the dataset (2018-10-17) — 4 rows affected. | `2017-09-19 09:45:35` | 0.0 | 82.84 | — |
| price | float | Item price, **excludes freight**. Min 0.85, mean 120.65, median 74.99, max 6,735.00. No zero/negative values. | `58.90` | 0.0 | 5.30 | Revenue source of truth (see Data Quality Report §Revenue reconciliation) |
| freight_value | float | Shipping cost for this line item. Min 0.00 (free-shipping items exist), mean 19.99, median 16.26, max 409.68. | `13.29` | 0.0 | 6.21 | — |

## order_payments — `olist_order_payments_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| order_id | string | FK to orders; up to 29 payment rows for a single order (installments/split payment). | `b81ef226f3fe1789b1e8b2acac839d17` | 0.0 | 95.72 | FK → orders; composite PK with payment_sequential |
| payment_sequential | int | Sequence number when multiple payment rows exist for one order. | `1` | 0.0 | 0.03 | Composite PK w/ order_id |
| payment_type | string | credit_card (73.9%), boleto (19.0%), voucher (5.6%), debit_card (1.5%), not_defined (0.0%, 3 rows). | `credit_card` | 0.0 | 0.00 | Categorical dimension |
| payment_installments | int | Number of installments (0–24 observed). | `8` | 0.0 | 0.02 | — |
| payment_value | float | Amount for this payment record. Sum-per-order reconciles with `order_items` total within 1 cent for 99.61% of orders present in both (see Data Quality Report). 9 rows have `payment_value == 0`. | `99.33` | 0.0 | 27.99 | — |

## order_reviews — `olist_order_reviews_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| review_id | string | Review identifier. **Not a clean key** — 814 duplicate values. | `7bc2406110b926393aa56f80a40eba40` | 0.0 | 99.18 | Candidate PK, uniqueness NOT confirmed |
| order_id | string | FK to orders. | `73fc7af87114b39712e6da79b0a377eb` | 0.0 | 99.44 | FK → orders |
| review_score | int | 1–5 star rating. Distribution: 1★ 11.5%, 2★ 3.2%, 3★ 8.2%, 4★ 19.3%, 5★ 57.8%. | `4` | 0.0 | 0.01 | KPI source |
| review_comment_title | string | Optional free-text title. | `recomendo` | 88.34 | 4.56 | Unstructured field |
| review_comment_message | string | Optional free-text comment — **the only substantive unstructured field in this dataset.** 41.27% non-empty. See EDA_REPORT.md §Text/RAG feasibility. | `Recebi bem antes do prazo estipulado.` | 58.70 | 36.44 | Unstructured field |
| review_creation_date | date | When the review was submitted. | `2018-01-18` | 0.0 | 0.64 | — |
| review_answer_timestamp | datetime | When Olist/seller responded to the review. | `2018-01-18 21:46:59` | 0.0 | 99.02 | — |

## products — `olist_products_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| product_id | string | Unique product identifier. | `1e9e8ef04dbcff4541ed26657ea517e5` | 0.0 | 100.0 | PK |
| product_category_name | string | Portuguese category name (73 distinct values incl. 2 with no English translation). | `perfumaria` | 1.85 | 0.22 | FK → category_translation (imperfect, see Data Quality Report) |
| product_name_lenght | float | Character count of the product name. **Misspelling preserved from source** ("lenght", not "length") — do not silently rename. | `40.0` | 1.85 | 0.20 | — |
| product_description_lenght | float | Character count of the description. Same misspelling caveat. | `287.0` | 1.85 | 8.98 | — |
| product_photos_qty | float | Count of product photos. | `1.0` | 1.85 | 0.06 | — |
| product_weight_g | float | Product weight in grams. 4 rows have value 0 (likely data-entry error). | `225.0` | 0.01 | 6.69 | — |
| product_length_cm | float | | `16.0` | 0.01 | 0.30 | — |
| product_height_cm | float | | `10.0` | 0.01 | 0.31 | — |
| product_width_cm | float | | `14.0` | 0.01 | 0.29 | — |

## sellers — `olist_sellers_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| seller_id | string | Unique seller identifier. | `3442f8959a84dea7ee197c632cb2df15` | 0.0 | 100.0 | PK |
| seller_zip_code_prefix | int | First 5 digits of seller's zip code. | `13023` | 0.0 | 72.57 | FK candidate → geolocation |
| seller_city | string | | `campinas` | 0.0 | 19.74 | — |
| seller_state | string | 2-letter state code (23 distinct values — fewer than the 27 customer states). | `SP` | 0.0 | 0.74 | Categorical dimension |

## geolocation — `olist_geolocation_dataset.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| geolocation_zip_code_prefix | int | Zip-code prefix. **Not unique** — 19,015 distinct prefixes across 1,000,163 rows; many lat/lng samples per prefix, 26.2% of rows are exact full-row duplicates. | `1037` | 0.0 | 1.90 | No row-level key; must aggregate to zip-prefix grain before use as a joinable dimension |
| geolocation_lat | float | | `-23.5456...` | 0.0 | 71.72 | — |
| geolocation_lng | float | | `-46.6393...` | 0.0 | 71.75 | — |
| geolocation_city | string | | `sao paulo` | 0.0 | 0.80 | — |
| geolocation_state | string | | `SP` | 0.0 | 0.00 | — |

## category_translation — `product_category_name_translation.csv`

| Column | Type | Meaning | Example | Null % | Unique % | Key? |
|---|---|---|---|---|---|---|
| product_category_name | string | Portuguese category name. | `beleza_saude` | 0.0 | 100.0 | PK |
| product_category_name_english | string | English translation. | `health_beauty` | 0.0 | 100.0 | — |

---

## Confirmed findings (observations, not assumptions)

- **`customer_id` vs `customer_unique_id`**: 99,441 order-scoped `customer_id` values map to 96,096 distinct `customer_unique_id` values → confirms repeat customers exist. Always use `customer_unique_id` for customer-level analysis (LTV, repeat-purchase rate, cohorting).
- **`order_reviews.review_id` is not a clean key**: 814 duplicate `review_id` values, 547 orders with >1 review row. Any "one review per order" assumption is wrong for ~0.6% of orders.
- **Revenue reconciliation** (computed directly, not assumed): summing `order_items.price` per order and comparing to summed `order_payments.payment_value` per order matches within 1 cent for 98,284 of 98,665 orders present in both tables (99.61%). 381 orders mismatch by a mean of 8.58 (likely financing interest on installment payments, since `order_payments` includes interest and `order_items.price` does not). **`SUM(order_items.price)` is the correct, decomposable revenue source of truth** for Causa KPIs — `payment_value` is not, because it is not decomposable into price × quantity.
- **`shipping_limit_date` anomaly**: 4 rows have a shipping deadline (max 2020-04-09) far beyond the last recorded order (2018-10-17) — internally inconsistent, flagged LOW severity given the tiny row count, but a real data-quality defect, not fabricated.
- **Two product categories** (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`) exist in `products` but have no row in `category_translation` — English category name will be null for those products unless patched.
- **No direct PII columns exist** in this release (no name/email/phone/street address in any table) — confirmed by column enumeration and a regex sweep over all identifier-table text columns (0 matches). See Data Quality Report §Security/PII for the sensitivity classification of the ID/location fields that do exist.
