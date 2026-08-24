# Olist Data Quality Report

Status: populated from the dataset present in `data/raw/olist/` on 2026-08-25, via
`scripts/profile_olist.py` and manual checks in `notebooks/01_olist_eda.ipynb`. Regenerate
with the command below if the raw data changes.

```bash
python scripts/profile_olist.py
```

This writes `data/raw/olist/_profile_summary.json` (machine-readable) and prints a
human-readable summary to stdout.

---

## 1. Row counts and shape

| Table | Rows | Columns |
|---|---|---|
| customers | 99,441 | 5 |
| orders | 99,441 | 8 |
| order_items | 112,650 | 7 |
| order_payments | 103,886 | 5 |
| order_reviews | 99,224 | 7 |
| products | 32,951 | 9 |
| sellers | 3,095 | 4 |
| geolocation | 1,000,163 | 5 |
| category_translation | 71 | 2 |

## 2. Null / missing values

Only columns with non-zero null rates are listed; all others are 0%.

| Table | Column | Null rate | Notes |
|---|---|---|---|
| orders | order_approved_at | 0.16% | Small number of orders never had payment approval logged |
| orders | order_delivered_carrier_date | 1.79% | Orders not yet/never shipped (canceled, unavailable, etc.) |
| orders | order_delivered_customer_date | 2.98% | Expected — undelivered orders (shipped, canceled, unavailable, processing, etc.) |
| order_reviews | review_comment_title | 88.34% | Optional free text — most reviews skip a title |
| order_reviews | review_comment_message | 58.70% | Optional free text — majority skip a written comment |
| products | product_category_name | 1.85% (610 rows) | No category assigned |
| products | product_name_lenght | 1.85% | Null wherever category is null |
| products | product_description_lenght | 1.85% | Null wherever category is null |
| products | product_photos_qty | 1.85% | Null wherever category is null |
| products | product_weight_g / length / height / width | 0.01% (a handful of rows) | Distinct from the category-null rows — separate small gap |

**Note:** column names `product_name_lenght` and `product_description_lenght` are
misspelled in the raw source data (kept as-is for fidelity; do not "fix" without
updating all downstream references).

## 3. Duplicates

| Table | Full-row duplicates | Primary-key duplicates | Notes |
|---|---|---|---|
| customers | 0 | 0 | `customer_id` is a clean PK |
| orders | 0 | 0 | `order_id` is a clean PK |
| order_items | 0 | 0 | `(order_id, order_item_id)` is a clean PK |
| order_payments | 0 | 0 | `(order_id, payment_sequential)` is a clean PK |
| order_reviews | 0 | **814** | `review_id` is **not** a clean primary key — see §8 |
| products | 0 | 0 | `product_id` is a clean PK |
| sellers | 0 | 0 | `seller_id` is a clean PK |
| geolocation | **261,831 / 1,000,163 (26.2%)** | n/a (no single-row PK) | Expected — many lat/lng samples share a zip prefix; must aggregate before use as a dimension |
| category_translation | 0 | 0 | `product_category_name` is a clean PK |

## 4. Referential integrity (orphan foreign keys)

| Child table.column | Parent table.column | Orphan count | Orphan rate | Notes |
|---|---|---|---|---|
| orders.customer_id | customers.customer_id | 0 | 0.00% | Clean |
| order_items.order_id | orders.order_id | 0 | 0.00% | Clean |
| order_items.product_id | products.product_id | 0 | 0.00% | Clean |
| order_items.seller_id | sellers.seller_id | 0 | 0.00% | Clean |
| order_payments.order_id | orders.order_id | 0 | 0.00% | Clean |
| order_reviews.order_id | orders.order_id | 0 | 0.00% | Clean |
| products.product_category_name | category_translation.product_category_name | **2** | 2.74% | Two Portuguese category names (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`) exist in `products` but have no row in the translation table — English name will be missing for products in these categories unless patched |

Overall: the core order → customer/item/payment/review/product/seller graph is fully
intact with **zero orphans**. The only integrity gap is the category translation lookup.

## 5. Date range and time coverage

| Column | Min | Max | Notes |
|---|---|---|---|
| order_purchase_timestamp | 2016-09-04 21:15:19 | 2018-10-17 17:30:18 | ~2 years of data; volume before 2017 is negligible (dataset effectively starts ramping in 2017) |
| order_delivered_carrier_date | 2016-10-08 10:34:01 | 2018-09-11 19:48:28 | |
| order_delivered_customer_date | 2016-10-11 13:46:32 | 2018-10-17 13:22:46 | |
| order_estimated_delivery_date | 2016-09-30 | 2018-11-12 | Estimates extend slightly past the last actual delivery, as expected |

- **No orders found with delivery timestamp before purchase timestamp** — passes the basic logical-consistency check.
- Order volume by month should still be plotted (see notebook §7) to confirm there are no unexpected gaps or spikes; a known characteristic of this dataset is very low volume in the first few months (late 2016) before the marketplace scaled up in 2017–2018.

## 6. Categorical / value distributions

**`order_status`** (n=99,441):

| Status | Count | % |
|---|---|---|
| delivered | 96,478 | 97.02% |
| shipped | 1,107 | 1.11% |
| canceled | 625 | 0.63% |
| unavailable | 609 | 0.61% |
| invoiced | 314 | 0.32% |
| processing | 301 | 0.30% |
| created | 5 | 0.01% |
| approved | 2 | 0.00% |

The dataset is overwhelmingly `delivered`. KPI logic should explicitly decide how to
treat the ~3% of non-delivered orders (exclude from revenue-realized KPIs vs. include
in funnel/operational KPIs).

**`payment_type`** (n=103,886):

| Type | Count | % |
|---|---|---|
| credit_card | 76,795 | 73.9% |
| boleto | 19,784 | 19.0% |
| voucher | 5,775 | 5.6% |
| debit_card | 1,529 | 1.5% |
| not_defined | 3 | 0.0% |

**`review_score`** (n=99,224):

| Score | Count | % |
|---|---|---|
| 1 | 11,424 | 11.5% |
| 2 | 3,151 | 3.2% |
| 3 | 8,179 | 8.2% |
| 4 | 19,142 | 19.3% |
| 5 | 57,328 | 57.8% |

Distribution is strongly right-skewed toward 5-star — typical for e-commerce review data.

**`customer_state`** top states: SP (41,746), RJ (12,852), MG (11,635), RS (5,466), PR (5,045) — heavily concentrated in São Paulo.

**`seller_state`** top states: SP (1,849 of 3,095 sellers, ~60%), PR (349), MG (244), SC (190), RJ (171) — seller base is even more concentrated in SP than customers.

## 7. Outliers and anomalies

- **`order_items.price`**: mean 120.65, median 74.99, max 6,735.00 (min 0.85). Right-skewed with a long tail of high-value items; no zero/negative prices found.
- **`order_items.freight_value`**: mean 19.99, median 16.26, max 409.68, min 0.00 (some free-shipping line items exist). No negative values.
- **`order_payments.payment_value`**: mean 154.10, median 100.00, max 13,664.08. **9 rows have `payment_value == 0`** — worth investigating (possibly fully-voucher-covered orders or data entry gaps) before using payment_value as a revenue proxy.
- **`products`**: 4 products have `product_weight_g == 0` — likely data entry errors; negligible in volume (4 of 32,951) but should be excluded or flagged in any weight/logistics KPI.
- Item-level price/freight and payment-level totals have not yet been reconciled against each other per order — recommended as a follow-up check (sum of `order_items.price + freight_value` per order vs. sum of `order_payments.payment_value` per order) before finalizing revenue KPI logic.

## 8. Known dataset caveats (from Olist/Kaggle documentation + observed)

- `customer_id` is per-order, not per-person; **99,441 customer_id values map to only 96,096 distinct `customer_unique_id` values**, confirming repeat customers exist in the raw data and that `customer_unique_id` must be used for any customer-level KPI (repeat purchase rate, LTV, cohort analysis).
- `product_name_lenght` / `product_description_lenght` columns are misspelled in the source data (kept as-is for fidelity to raw source; do not silently rename without updating everywhere).
- `geolocation` is not deduplicated — 26.2% of rows are exact duplicates, and many more rows share a zip-code prefix with differing lat/lng (multiple samples per prefix). Must aggregate (e.g., mean/median lat/lng, mode city) to one row per zip prefix before use as a join-able dimension.
- **`order_reviews.review_id` is not a clean primary key**: 814 duplicate review_id values found, and 547 orders have more than one review row. Any model treating "one review per order" as an assumption will be wrong for ~0.6% of orders; dedupe/aggregation strategy needed (e.g., keep latest by `review_answer_timestamp`, or model review as a proper 1:many fact).
- 2 product categories (`pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`) are missing from `category_translation` — patch the lookup table or handle nulls gracefully in the English category name.

## 9. Summary of blocking issues vs. cosmetic issues

| Issue | Severity | Blocking for data model? |
|---|---|---|
| `order_reviews.review_id` not unique (814 dupes, 547 multi-review orders) | Medium | Yes — must define review grain/dedup rule before modeling review fact |
| `geolocation` not deduplicated / many rows per zip prefix | Medium | Yes, if geolocation is used — must aggregate before joining |
| 2 missing category translations | Low | No — patch lookup or fallback to null English name |
| 610 products with null category | Low | No — handle as "uncategorized" bucket |
| 9 payments with `payment_value == 0` | Low | No — flag/exclude from revenue KPIs, investigate later |
| 4 products with zero weight | Low | No — negligible volume, exclude from logistics KPIs |
| ~3% of orders not in `delivered` status | Low–Medium | No, but requires an explicit inclusion/exclusion rule in KPI definitions |
| Order lifecycle timestamp nulls (approved/carrier/delivered dates) | Low | No — expected consequence of non-delivered order statuses |

**No issues found that block proceeding to data modeling.** The core order/customer/item/
payment/product/seller relationships are fully referentially intact. The two items that
need explicit design decisions before modeling are the review grain (duplicate review_id)
and the geolocation aggregation strategy — both are addressed as open questions in
`DATA_MODEL.md`.

## 10. Next steps

- [x] Run `scripts/profile_olist.py` against the full dataset.
- [x] Confirm referential integrity across all declared foreign keys.
- [x] Confirm date range and lifecycle timestamp sanity (no delivery-before-purchase cases).
- [ ] Decide and document the review dedup rule, then encode it in `DATA_MODEL.md`.
- [ ] Decide the geolocation aggregation approach, then encode it in `DATA_MODEL.md`.
- [ ] Reconcile `order_items` (price+freight) totals against `order_payments` totals per order.
