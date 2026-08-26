# Olist Data Quality Report

Status: populated from the dataset in `data/raw/olist/` (extracted from `archive.zip`)
on **2026-08-26**, via `scripts/profile_olist.py`, `scripts/kpi_temporal_eda.py`,
`scripts/text_and_entity_eda.py`, and `scripts/join_driver_anomaly_eda.py`. Every
number in this report was computed from the real CSVs in this run — none are carried
over unverified from prior sessions. Regenerate with:

```bash
python scripts/profile_olist.py
python scripts/kpi_temporal_eda.py
python scripts/text_and_entity_eda.py
python scripts/join_driver_anomaly_eda.py
```

Machine-readable outputs: `data/raw/olist/_profile_summary.json`,
`reports/kpi_eda_summary.json`, `reports/text_eda_summary.json`,
`reports/join_driver_anomaly_summary.json`.

Each finding below is classified **CRITICAL / HIGH / MEDIUM / LOW** by analytical
consequence, not by percentage alone.

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

## 2. CRITICAL — Temporal coverage collapses at both edges of the date range

The raw `order_purchase_timestamp` spans 2016-09-04 to 2018-10-17, but **volume is not
usable across that entire span**:

| Month | Orders | Revenue (order_items.price) |
|---|---|---|
| 2016-09 | 4 | 267.36 |
| 2016-10 | 324 | 49,507.66 |
| 2016-11 | 0 | — |
| 2016-12 | 1 | 10.90 |
| 2017-01 → 2018-08 | 800 – 7,544 per month | 120K – 1.01M per month |
| 2018-09 | 16 | 145.00 |
| 2018-10 | 4 | — |

**Consequence:** a naive trend/anomaly/YoY analysis over the full date range would
report a ~99.8% "collapse" in Sept–Oct 2018 and a ~7,900% "surge" out of the 2016
ramp — both spurious, driven by dataset extraction boundaries (the pull was made
in mid-October 2018; platform launch was Sept 2016 with negligible early volume),
not real business events. **Every temporal/KPI/anomaly analysis in this project
must restrict its reliable window to 2017-01 through 2018-08** (17,443 → the bulk
of full months) and explicitly exclude 2016-09 through 2016-12 and 2018-09 onward,
or clearly flag them as partial/ramp periods if included. This is the single
most consequential data-quality finding for Causa's temporal-EDA and anomaly-detection
requirements.

## 3. Null / missing values

Only columns with non-zero null rates are listed; all others are 0%. Full table in
`DATA_DICTIONARY.md`.

| Table | Column | Null rate | Severity | Consequence |
|---|---|---|---|---|
| orders | order_approved_at | 0.16% | LOW | Negligible; a handful of orders never had approval logged |
| orders | order_delivered_carrier_date | 1.79% | LOW | Expected for non-delivered orders |
| orders | order_delivered_customer_date | 2.98% | MEDIUM | Blocks delivery-time KPI for those rows; correlates with non-`delivered` status, so **not missing at random with respect to order outcome** — excluding them from a delivery-time KPI is correct, but averaging only over completed deliveries will understate real-world delivery friction (cancellations/failures are silently dropped) |
| order_reviews | review_comment_title | 88.34% | LOW (structural) | Optional field; most reviewers skip a title |
| order_reviews | review_comment_message | 58.70% | HIGH for RAG | Only 41.27% of reviews carry retrievable free text — caps the maximum unstructured-evidence coverage for any KPI investigation at ~41% of reviewed orders, and reviews themselves cover only ~99% of orders (547 orders duplicate, 759 orders have no review at all when joined through items — see §8) |
| products | product_category_name (+3 dependent cols) | 1.85% (610 rows) | LOW | Handle as explicit "uncategorized" bucket |
| products | product_weight_g/length/height/width | 0.01% (4 rows) | LOW | Negligible; exclude from logistics KPIs |

## 4. Duplicates

| Table | Full-row duplicates | Primary-key duplicates | Severity | Notes |
|---|---|---|---|---|
| customers | 0 | 0 | — | Clean |
| orders | 0 | 0 | — | Clean |
| order_items | 0 | 0 | — | Clean |
| order_payments | 0 | 0 | — | Clean |
| order_reviews | 0 | **814** | MEDIUM | `review_id` is not a clean PK; 547 orders have >1 review row — dedup/aggregation rule required before modeling review as a fact table (see `RELATIONSHIP_GRAPH.md`) |
| products | 0 | 0 | — | Clean |
| sellers | 0 | 0 | — | Clean |
| geolocation | **261,831 / 1,000,163 (26.2%)** | n/a | MEDIUM if used | Must aggregate to one row per zip prefix before joining |
| category_translation | 0 | 0 | — | Clean |

## 5. Referential integrity (orphan foreign keys)

| Child.column | Parent.column | Orphan keys | Orphan rows | Severity |
|---|---|---|---|---|
| orders.customer_id | customers.customer_id | 0 | 0 | — |
| order_items.order_id | orders.order_id | 0 | 0 | — |
| order_items.product_id | products.product_id | 0 | 0 | — |
| order_items.seller_id | sellers.seller_id | 0 | 0 | — |
| order_payments.order_id | orders.order_id | 0 | 0 | — |
| order_reviews.order_id | orders.order_id | 0 | 0 | — |
| products.product_category_name | category_translation.product_category_name | 2 (2.74% of distinct) | 13 rows (0.04%) | LOW |

The core order → customer/item/payment/review/product/seller graph has **zero
orphans**. The only integrity gap is the category-translation lookup (2 missing
categories: `pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`).

**However**, referential integrity does not mean every order participates in every
table: **775 of 99,441 orders (0.78%) have zero `order_items` rows**, and 1 order has
no `order_payments` row. These are not orphans (no dangling FK) but they are
**structurally missing facts** — see §6.

## 6. HIGH — Revenue source-of-truth reconciliation

Computed directly (not assumed) by summing `order_items.price + freight_value` per
order and comparing to summed `order_payments.payment_value` per order:

| Metric | Value |
|---|---|
| Orders with `order_items` rows | 98,666 |
| Orders with `order_payments` rows | 99,440 |
| Orders present in both | 98,665 |
| Orders with items but no payment row | 1 |
| Orders with a payment row but no items | 775 |
| Matched within 1 cent | 98,284 (99.61% of the 98,665 in both) |
| Mismatched (>1 cent) | 381 (mean diff 8.58, max 182.81) |

**Consequence:** `SUM(order_items.price)` is the correct, PVM-decomposable revenue
source of truth (see `KPI_CANDIDATES.md`); `order_payments.payment_value` is close
(99.6% agreement) but includes financing/installment interest not present in item
price, so it is **not** decomposable into price × quantity and should be used only
for payment-method/financing analysis, not as the primary revenue KPI. The 775
orders with payments but zero items (mostly non-`delivered`/`canceled`/`unavailable`
statuses — not independently re-verified row-by-row here) must be explicitly
excluded from any item-level revenue or PVM calculation, or Causa will silently
undercount payment activity that has no attributable line items.

## 7. HIGH — Join fan-out / revenue-multiplication risk (verified, not hypothetical)

Naively joining `orders ⋈ order_items ⋈ order_payments ⋈ order_reviews` and then
summing `price` **inflates total revenue by 4.04%** (13,591,643.70 real vs.
14,141,001.32 naive) purely from row multiplication — order_payments has up to 29
rows for a single order (installments) and order_reviews up to 3. Concrete
reproduced example: order `03ecec245220b63fd7f68c1737ba99ba` has 2 items (true price
total 298.90) and 2 payment rows; joining items×payments before summing yields 4 rows
and a summed price of 597.80 — exactly 2× inflation. **Rule for all Causa KPI
calculations: aggregate `order_items` to one row per `order_id` (sum price/freight,
count items) BEFORE joining to `order_payments` or `order_reviews`.** Full detail
and diagram in `RELATIONSHIP_GRAPH.md`.

## 8. Date validation

| Column | Min | Max | Severity | Notes |
|---|---|---|---|---|
| order_purchase_timestamp | 2016-09-04 21:15:19 | 2018-10-17 17:30:18 | — | See §2 for usable-window caveat |
| order_delivered_carrier_date | 2016-10-08 10:34:01 | 2018-09-11 19:48:28 | — | |
| order_delivered_customer_date | 2016-10-11 13:46:32 | 2018-10-17 13:22:46 | — | |
| order_estimated_delivery_date | 2016-09-30 | 2018-11-12 | — | Extends past last actual delivery, expected |
| **order_items.shipping_limit_date** | 2016-09-19 00:15:34 | **2020-04-09 22:35:08** | **LOW** | 4 rows have a shipping deadline ~18 months after the last order in the dataset — internally inconsistent, real defect, tiny volume |

No delivery-before-purchase cases found (basic logical-consistency check passes).

## 9. Categorical / value distributions

**`order_status`** (n=99,441): delivered 96,478 (97.02%), shipped 1,107 (1.11%),
canceled 625 (0.63%), unavailable 609 (0.61%), invoiced 314 (0.32%), processing 301
(0.30%), created 5 (0.01%), approved 2 (0.00%). KPI logic must explicitly decide
inclusion/exclusion of the ~3% non-delivered orders per KPI (exclude from
revenue-realized KPIs, include in funnel/operational KPIs).

**`payment_type`** (n=103,886): credit_card 76,795 (73.9%), boleto 19,784 (19.0%),
voucher 5,775 (5.6%), debit_card 1,529 (1.5%), not_defined 3 (0.0%).

**`review_score`** (n=99,224): 1★ 11,424 (11.5%), 2★ 3,151 (3.2%), 3★ 8,179 (8.2%),
4★ 19,142 (19.3%), 5★ 57,328 (57.8%). Strongly right-skewed toward 5-star.

**Geography**: seller base is more concentrated than the customer base — top seller
state SP holds ~61% of item-level revenue (8.51M of 13.9M); top 20 sellers alone
account for 21.28% of all revenue. Customer states: SP 40,501 orders, RJ 12,350, MG
11,354 — long tail down to AP (67) and RR (41).

## 10. Outliers and anomalies

- `order_items.price`: mean 120.65, median 74.99, max 6,735.00, min 0.85 — no
  zero/negative values.
- `order_items.freight_value`: mean 19.99, median 16.26, max 409.68, min 0.00 (some
  free-shipping line items exist) — no negatives.
- `order_payments.payment_value`: mean 154.10, median 100.00, max 13,664.08. **9 rows
  have `payment_value == 0`** — worth investigating (possibly fully-voucher-covered
  orders) before treating `payment_value` as a revenue proxy.
- `products`: 4 rows have `product_weight_g == 0` (likely data-entry error);
  negligible volume, exclude from logistics KPIs.

## 11. Text quality (order_reviews.review_comment_message)

See `EDA_REPORT.md` §Text/RAG feasibility and `reports/text_eda_summary.json` for
full detail. Headline numbers: 41.27% of reviews have message text; 91.8%
Portuguese-likely by a crude stopword/diacritic heuristic (not a validated
classifier — flagged as needing a real language detector before RAG build);
14.59% of non-empty messages are exact-duplicate boilerplate ("Muito bom" appears
230 times); max message length 208 characters / 45 words (source field is
effectively capped, not organically short); **0 rows matched the prompt-injection
regex sweep and 0 email-pattern matches** — reported as a genuine negative finding,
not omitted.

## 12. Known dataset caveats (from Olist/Kaggle docs + observed here)

- `customer_id` is per-order, not per-person; 99,441 values map to only 96,096
  distinct `customer_unique_id` values — repeat customers exist; use
  `customer_unique_id` for any customer-level KPI.
- `product_name_lenght` / `product_description_lenght` are misspelled in the source
  data (kept as-is; do not silently rename without updating every downstream
  reference).
- `geolocation` is not deduplicated (26.2% exact-duplicate rows) and has many samples
  per zip prefix — must aggregate (mean/median lat/lng, mode city) before use as a
  join-able dimension.
- `order_reviews.review_id` is not a clean primary key (814 duplicates, 547
  multi-review orders) — dedup rule required (e.g., keep latest by
  `review_answer_timestamp`).
- 2 product categories are missing from `category_translation` — patch the lookup
  or handle nulls gracefully in the English name.
- Dataset is pre-anonymized: no name/email/phone/address fields exist in any table
  (confirmed by column enumeration + zero regex matches, not merely assumed from
  documentation).

## 13. Severity summary

| Issue | Severity | Blocking for KPI/temporal work? |
|---|---|---|
| Temporal edge collapse (2016 ramp, Sept–Oct 2018 cutoff) | **CRITICAL** | **Yes** — must restrict analysis window to 2017-01–2018-08 or every trend/anomaly claim is at risk of being an artifact |
| Naive multi-table join inflates revenue 4.04% | **HIGH** | Yes — must aggregate order_items before joining to payments/reviews |
| Revenue source-of-truth ambiguity (items vs payments, 99.61% agreement) | **HIGH** | Yes — must standardize on `SUM(order_items.price)` as the KPI definition |
| `order_reviews.review_id` not unique (814 dupes, 547 multi-review orders) | MEDIUM | Yes, if modeling review as a 1:1 fact — needs an explicit dedup rule |
| `geolocation` not deduplicated | MEDIUM if used | Yes, if geolocation is used — must aggregate first |
| Only 41.27% of reviews carry usable free text | HIGH for RAG scope | No for structured KPIs; yes for unstructured-evidence coverage claims |
| 775 orders with payments but no items | MEDIUM | Yes for revenue reconciliation — must be explicitly excluded, not zero-filled |
| `order_delivered_customer_date` null correlates with non-delivered status | MEDIUM | Yes — delivery-time KPI implicitly survivorship-biases toward successful deliveries |
| 2 missing category translations | LOW | No |
| 610 products with null category | LOW | No — "uncategorized" bucket |
| 9 payments with value 0 | LOW | No — flag/exclude |
| 4 products with zero weight | LOW | No |
| `shipping_limit_date` 4 rows past last order date | LOW | No |
| ~3% of orders not `delivered` | LOW–MEDIUM | No, but needs explicit inclusion/exclusion rule per KPI |

**Bottom line:** the core relational graph is genuinely clean (zero FK orphans, zero
duplicate order/item/payment PKs). The issues that matter are not row-level defects —
they are **temporal-window validity** and **revenue-definition/aggregation-order**
issues that would silently produce wrong or misleading KPI numbers if not handled
explicitly in Causa's KPI layer. Both are addressed with concrete rules above.

## 14. Next steps

- [x] Run `scripts/profile_olist.py` against the full real dataset.
- [x] Confirm referential integrity across all declared foreign keys.
- [x] Confirm date range and lifecycle timestamp sanity.
- [x] Reconcile `order_items` totals against `order_payments` totals per order.
- [x] Quantify the join fan-out risk with a concrete example.
- [x] Identify and bound the usable temporal window.
- [ ] Decide and encode the review dedup rule in the eventual data model.
- [ ] Decide the geolocation aggregation approach if geography is used beyond
      state-level (state-level needs no geolocation join at all — it's already on
      customers/sellers).
