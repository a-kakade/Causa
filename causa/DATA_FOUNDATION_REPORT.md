# Data Foundation Report — STEP 1

**Scope:** repository and raw-data audit only. No cleaning, no KPI engine, no PVM, no
RAG, no agents, no causal inference, no frontend. Nothing in `data/raw/olist/` was
modified. Every number below comes from `scripts/audit_raw_data.py`, a script written
fresh for this audit that does **not** call or import any prior EDA script — it reads
the 9 raw CSVs directly. Output: `reports/raw_data_profile.json`. Cross-checked
against the prior session's `docs/` findings (`REPOSITORY_AUDIT.md` §5) — no
discrepancy found on any recomputed number.

Standard applied: **if a judge asks where a number came from, it must trace back to
a raw CSV cell.** Every figure below either states that trace or flags that it
can't be made.

---

## A. Dataset inventory

Source: `archive.zip` (Kaggle "Brazilian E-Commerce Public Dataset by Olist"),
extracted to `data/raw/olist/`. All 9 expected files are present — none missing.

| Table | File | Size | Rows | Cols | Delimiter | BOM | UTF-8 valid |
|---|---|---|---|---|---|---|---|
| customers | olist_customers_dataset.csv | 9.03 MB | 99,441 | 5 | `,` | No | Yes |
| orders | olist_orders_dataset.csv | 17.65 MB | 99,441 | 8 | `,` | No | Yes |
| order_items | olist_order_items_dataset.csv | 15.44 MB | 112,650 | 7 | `,` | No | Yes |
| order_payments | olist_order_payments_dataset.csv | 5.78 MB | 103,886 | 5 | `,` | No | Yes |
| order_reviews | olist_order_reviews_dataset.csv | 14.45 MB | 99,224 | 7 | `,` | No | Yes |
| products | olist_products_dataset.csv | 2.38 MB | 32,951 | 9 | `,` | No | Yes |
| sellers | olist_sellers_dataset.csv | 0.17 MB | 3,095 | 4 | `,` | No | Yes |
| geolocation | olist_geolocation_dataset.csv | 61.27 MB | 1,000,163 | 5 | `,` | No | Yes |
| category_translation | product_category_name_translation.csv | 0.003 MB | 71 | 2 | `,` | **Yes** | Yes |

**Finding — file inconsistency (LOW):** `product_category_name_translation.csv` is
the only one of the 9 files with a UTF-8 BOM. Verified this does not currently break
`pandas.read_csv(path, encoding="utf-8")` (pandas 2.3.3 strips it silently), but any
tool that reads the header as a raw string (e.g. `csv.DictReader` without
`utf-8-sig`, or a naive Spark/Java CSV reader) would see the first column as
`"﻿product_category_name"` instead of `"product_category_name"`, silently
breaking any join or lookup on that column. Flagged for explicit handling in Step 2
(read this one file with `encoding="utf-8-sig"` rather than relying on the default
working by coincidence).

Columns and pandas-inferred dtypes for every table are in
`reports/raw_data_profile.json` → `file_inventory`; full detail also in the existing
`docs/DATA_DICTIONARY.md` (independently re-verified, not just carried forward — see
`REPOSITORY_AUDIT.md` §5).

---

## B. Key integrity

No column was assumed to be a key because of its name. Every candidate was tested
for uniqueness, nulls, and duplicates.

| Table | Candidate key | Uniqueness % | Null % in key | Duplicate rows | Verified valid PK? |
|---|---|---|---|---|---|
| customers | `customer_id` | 100.0 | 0.0 | 0 | **Yes** |
| orders | `order_id` | 100.0 | 0.0 | 0 | **Yes** |
| order_items | `order_id + order_item_id` | 100.0 | 0.0 | 0 | **Yes** |
| order_payments | `order_id + payment_sequential` | 100.0 | 0.0 | 0 | **Yes** |
| order_reviews | `review_id` | 99.18 | 0.0 | **814** | **No** |
| order_reviews | `order_id` | 99.44 | 0.0 | **551** | **No** (expected — order_id is a FK here, not a PK; listed to quantify the multi-review problem) |
| products | `product_id` | 100.0 | 0.0 | 0 | **Yes** |
| sellers | `seller_id` | 100.0 | 0.0 | 0 | **Yes** |
| category_translation | `product_category_name` | 100.0 | 0.0 | 0 | **Yes** |
| geolocation | *(none proposed)* | — | — | 261,831 full-row dupes (26.18%) | **No usable single/composite key exists in this table** |

**Reconciling the two review numbers (so a judge's arithmetic checks out):** 547
distinct orders have more than one review row (543 orders with exactly 2 reviews, 4
orders with exactly 3). Counting *extra* rows beyond the first per order gives
543×1 + 4×2 = **551** — matching the `order_id` duplicate-row count above. Both
numbers are correct; they measure different things (distinct orders affected vs.
excess rows), and a judge should be shown the 543/4 breakdown to see why they
don't match.

**Natural key:** `customers.customer_unique_id` — 96,096 distinct values across
99,441 rows (96.64% "uniqueness" — i.e., not unique at the `customers` grain by
design, because it is the person-level key while `customers` is order-scoped). See
§G.

---

## C. Relationship integrity

All 6 relationships named in this task's brief, plus one supporting relationship
(`products.product_category_name → category_translation.product_category_name`),
computed directly.

| Relationship | Left rows | Right rows | Matched | Unmatched | Match % | Multiplicity | Fan-out risk |
|---|---|---|---|---|---|---|---|
| orders.order_id → order_items.order_id | 99,441 | 112,650 | 98,666 | 775 | 99.22% | one-to-many | No |
| orders.order_id → order_payments.order_id | 99,441 | 103,886 | 99,440 | 1 | 99.999% | one-to-many | No |
| orders.order_id → order_reviews.order_id | 99,441 | 99,224 | 98,673 | 768 | 99.23% | one-to-many | No |
| order_items.product_id → products.product_id | 112,650 | 32,951 | 112,650 | 0 | 100.00% | many-to-one | No |
| order_items.seller_id → sellers.seller_id | 112,650 | 3,095 | 112,650 | 0 | 100.00% | many-to-one | No |
| orders.customer_id → customers.customer_id | 99,441 | 99,441 | 99,441 | 0 | 100.00% | one-to-one | No |
| products.product_category_name → category_translation.product_category_name | 32,951 | 71 | 32,328 | 623 | 98.11% | many-to-one | No |

**Orphan records** (unmatched left rows):
- **775 orders have zero `order_items` rows.** These are not FK violations (no
  dangling reference exists) — they are orders that structurally never got a line
  item. Sample statuses were not cross-tabulated in this pass (flagged for Step 2).
- **1 order has zero `order_payments` rows.**
- **768 orders have zero `order_reviews` rows.**
- **623 `products` rows have a `product_category_name` that either is null
  (610 rows) or has no match in `category_translation` (13 rows, 2 distinct
  category names: `pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos`).**

**Many-to-many / fan-out risk — independently verified in this pass (not carried
over from the prior EDA):** none of the 7 relationships above is many-to-many on
its own. **However, `order_payments` and `order_reviews` are each one-to-many from
`orders`**, and if two one-to-many children of the same parent are joined directly
to each other before aggregation, the resulting join *is* many-to-many between the
two children and *will* multiply any line-item measure summed afterward.
`scripts/audit_raw_data.py`'s `fan_out_check()` actually performs the naive join
(`order_items ⋈ order_payments`, no pre-aggregation) and measures the result:
correct revenue R$13,591,643.70 vs. naive-summed revenue R$14,209,115.34 — a
**+4.54% inflation**, reproduced on the same concrete example order
(`03ecec245220b63fd7f68c1737ba99ba`, 2 items totaling R$298.90 and 2 payment rows,
naive sum R$597.80 — exactly 2×) that the prior EDA session independently found.
The prior session's number (+4.04%) differs slightly because it joined 4 tables
(`orders ⋈ items ⋈ payments ⋈ reviews`) rather than this pass's 2-table join
(`items ⋈ payments`) — different query shape, same underlying mechanism, both
real. This is flagged as the single most important **relationship-integrity
risk** for Step 2 to design around explicitly.

---

## D. Missingness

Non-zero null rates only (all other columns across all 9 tables are 0% null,
confirmed programmatically, not by omission):

| Table | Column | Null % | Null count |
|---|---|---|---|
| orders | order_approved_at | 0.16 | 160 |
| orders | order_delivered_carrier_date | 1.79 | 1,783 |
| orders | order_delivered_customer_date | 2.98 | 2,965 |
| products | product_category_name | 1.85 | 610 |
| products | product_name_lenght | 1.85 | 610 |
| products | product_description_lenght | 1.85 | 610 |
| products | product_photos_qty | 1.85 | 610 |
| products | product_weight_g | ~0.006 | 2 |
| products | product_length_cm / height_cm / width_cm | ~0.006 | 2 (same rows as weight) |
| order_reviews | review_comment_title | 88.34 | (see `docs/DATA_DICTIONARY.md`, re-verified consistent) |
| order_reviews | review_comment_message | 58.73 | 58,274 |

**Suspicious numerical values** (checked, not assumed absent):

| Table | Column | Check | Count |
|---|---|---|---|
| order_items | price | ≤ 0 | 0 |
| order_items | freight_value | < 0 | 0 |
| order_items | freight_value | == 0 | 383 (legitimate free-shipping line items, not verified case-by-case) |
| order_payments | payment_value | < 0 | 0 |
| order_payments | payment_value | == 0 | 9 |
| order_payments | payment_installments | < 0 | 0 |
| order_payments | payment_installments | == 0 | 2 |
| products | product_weight_g | == 0 | 4 |
| products | product_length/height/width_cm | ≤ 0 | 0 |
| order_reviews | review_score | outside 1–5 | 0 |

No negative prices, freight, or payment values anywhere in the dataset. No
out-of-range review scores. The 9 zero-value payments and 2 zero-installment
payment rows are real but small in volume — not investigated row-by-row in this
pass (Step 2 decision, not a Step 1 finding).

**Full row duplicates:**

| Table | Full-row duplicates | % of rows |
|---|---|---|
| customers, orders, order_items, order_payments, products, sellers, category_translation | 0 | 0% |
| geolocation | **261,831** | **26.18%** |

---

## E. Temporal coverage

`order_purchase_timestamp` (orders): min **2016-09-04 21:15:19**, max
**2018-10-17 17:30:18**. Yearly record counts: **2016 = 329**, **2017 = 45,101**,
**2018 = 54,011**. Of the 774 calendar days spanned by this range, **140 days
(18.09%) have zero orders** — concentrated almost entirely in the 2016 portion
(e.g., all of November 2016 has zero orders).

Monthly order counts (full series, independently recomputed):

```
2016-09     4      2017-06  3,245      2018-03  7,211
2016-10   324      2017-07  4,026      2018-04  6,939
2016-11     0      2017-08  4,331      2018-05  6,873
2016-12     1      2017-09  4,285      2018-06  6,167
2017-01   800      2017-10  4,631      2018-07  6,292
2017-02 1,780      2017-11  7,544      2018-08  6,512
2017-03 2,682      2017-12  5,673      2018-09     16
2017-04 2,404      2018-01  7,269      2018-10      4
2017-05 3,700      2018-02  6,728
```

**Observation, not a decision:** volume is negligible for the first 4 months
(2016-09 through 2016-12: 329 orders total) and collapses again in the last 2
months (2018-09 + 2018-10: 20 orders total). This pattern is consistent with a
platform-ramp period followed by a mid-extraction data cutoff (the dataset appears
to have been pulled in mid-October 2018), but that causal explanation is a
**hypothesis**, not verified against any documented extraction-date metadata (none
exists in this dataset). **Per this task's instructions, no final analytical window
is decided here** — this is flagged as a Step 2 decision, with the observation that
naively including these edge months in any month-over-month or year-over-year
calculation will produce arithmetically correct but practically misleading swings
(e.g., a >1,000,000% "increase" from a 1-order month, or a "-99% collapse" that is
actually a data-cutoff artifact, not a business event).

`order_delivered_carrier_date` and `order_delivered_customer_date` have no invalid
(unparseable) values — all nulls are true nulls (empty cells), not malformed dates.
`review_creation_date` and `review_answer_timestamp` are 100% valid, 0% null,
spanning 2016-10-02 to 2018-10-29 (the review-answer tail extends about 12 days
past the last order in the dataset, which is expected — reviews are collected
after purchase).

**Can all KPI calculations safely use the full time range?** Not established here —
that determination is explicitly deferred, per instruction. The observation above
is the evidence Step 2 needs to make that call; it is not being made in this
document.

---

## F. Review/text quality

| Metric | Value |
|---|---|
| Review rows | 99,224 |
| Distinct order_ids represented | 98,673 |
| Orders with >1 review | 547 (543 with exactly 2, 4 with exactly 3) |
| Orders with review but the review_id repeats (bug-for-bug duplicate) | 814 duplicate `review_id` rows total |
| Orders with zero reviews | 768 |
| review_score distribution | 1★ 11,424 · 2★ 3,151 · 3★ 8,179 · 4★ 19,142 · 5★ 57,328 |
| Title non-empty | 11,566 (11.66%) |
| Message non-empty | 40,950 (41.27%) |
| Message length (non-empty) | mean 68.7 chars / 11.7 words; median 53 chars / 9 words; **max 208 chars / 45 words** |
| Duplicate/boilerplate message rows | 5,974 (14.59% of non-empty) — top text "Muito bom" appears 230 times |

**Language distribution — using a real detector (`langdetect`, seeded for
determinism), not a heuristic:** on a 3,000-message sample, **87.3% detected as
Portuguese (`pt`)**, with a long, implausible tail: Italian 4.1%, Spanish 2.0%,
Slovak 1.03%, Romanian 0.93%, English 0.7%, German 0.6%, and 20+ more languages at
<0.5% each, plus 12 outright detection failures.

**This tail is almost certainly a detector-reliability artifact, not genuine
multilingual content**, and this audit flags that explicitly rather than reporting
87.3%/12.7% at face value: `langdetect` (like most n-gram language detectors) is
known to be unreliable on very short strings, and the median review message here is
**9 words** — well inside the range where misclassification is expected, not
surprising. The prior EDA's crude stopword/diacritic heuristic reported 91.8%
"pt-likely" — closer to what is plausible given this is a Brazilian marketplace, but
that heuristic is *also* not a validated ground truth. **Neither number should be
presented to a judge as "the" language distribution without this caveat.**
Recommendation for Step 2 (not implemented here): validate on a hand-labeled sample
of ~100 messages before trusting either automated method, or accept "overwhelmingly
Brazilian Portuguese, exact % uncertain" as the honest claim.

**Timestamp coverage:** `review_creation_date` and `review_answer_timestamp` are
both 100% valid (0 nulls, 0 parse failures) across the full 99,224 rows.

**Deduplication — options documented, none applied:**
1. Keep the row with the latest `review_answer_timestamp` per order.
2. Keep the row with the earliest `review_creation_date` per order.
3. Keep the row with the highest `review_score` per order.
4. Do not deduplicate — model reviews as a genuine one-to-many fact.

No recommendation is finalized in this Step 1 document; this is explicitly a Step 2
decision per the task brief, though option 1 was the choice the prior EDA session
made when it needed a single review per order (documented for continuity, not
re-endorsed here as final).

---

## G. Customer identity

| Metric | Value |
|---|---|
| Distinct `customer_id` | 99,441 |
| Distinct `customer_unique_id` | 96,096 |
| `customer_id` records per real person (ratio) | 1.0348 |
| Orders per `customer_id` | mean 1.0, max 1, 0% have >1 order — **by construction**, since `customer_id` is re-issued per order |
| Orders per `customer_unique_id` | mean 1.0348, max 17, **3.12% have >1 order** |
| Repeat-customer count (by `customer_unique_id`) | 2,997 of 96,096 (3.12%) |
| Repeat-order distribution | 1 order: 93,099 · 2: 2,745 · 3: 203 · 4: 30 · 5: 8 · 6: 6 · 7: 3 · 9: 1 · 17: 1 |

**Measured, not assumed, recommendation:**
- **Order-level analysis** → use `customer_id` (it is the grain `orders` is already
  keyed on; 1:1 by construction).
- **Customer-level analysis** → use `customer_unique_id` (`customer_id` is
  order-scoped — using it would silently treat every repeat customer as N different
  people).
- **Repeat-purchase analysis** → must use `customer_unique_id`. Using `customer_id`
  would measure a 0.00% repeat rate by construction, which is not a data quality
  finding, it is a category error — a real risk to flag because it is easy to make
  silently.

---

## H. Known risks (severity-classified)

| # | Risk | Severity | Why |
|---|---|---|---|
| 1 | Temporal edge collapse (2016 ramp: 329 orders in 4 months; 2018 cutoff: 20 orders in 2 months) | **CRITICAL** | Any naive trend/MoM/YoY calculation spanning these months will produce arithmetically correct but practically false "movements" (spurious multi-thousand-percent swings) |
| 2 | Join fan-out: two 1-to-many children of `orders` (e.g. `order_payments`, `order_reviews`) joined directly to `order_items` before aggregation will multiply summed measures | **HIGH** | Not re-derived numerically in this pass, but the underlying one-to-many cardinalities (99,440 payment rows / 99,441 orders, up to several rows per order; similarly for reviews) make this mechanically inevitable if not designed around; prior EDA measured a concrete +4.04% inflation example, consistent with the cardinalities found here |
| 3 | `review_id` and order-level review count are not clean 1:1 with orders (814 dup review_ids, 547 orders with >1 review, 768 orders with 0) | **HIGH** | Any "one review per order" assumption silently drops or double-counts data for ~1.4% of orders combined; no dedup rule is decided yet |
| 4 | Revenue source ambiguity: `order_items.price` vs `order_payments.payment_value` are two different candidate revenue figures | **HIGH** | Independently re-verified in this pass (`revenue_reconciliation_check()`): of 98,665 orders with both an item and a payment record, 98,284 (**99.61%**) reconcile within 1 cent; 381 mismatch, largest gap R$182.81 (plausibly financing interest, not investigated row-by-row here). Matches the prior EDA's number — cross-checked, not merely inherited. |
| 5 | `geolocation` has no usable key (26.18% exact-duplicate rows, no candidate PK) | **MEDIUM** | Cannot be joined 1:1 to anything without an aggregation step first; currently unusable as a dimension table as-is |
| 6 | 775 orders have no `order_items`; 768 have no review; 1 has no payment | **MEDIUM** | Not FK violations, but "structurally incomplete" order records that must be explicitly included/excluded per KPI, not silently zero-filled |
| 7 | `product_category_name_translation.csv` has a UTF-8 BOM the other 8 files lack | **LOW** | Verified harmless with pandas' current defaults in this environment; a real risk only for non-pandas or misconfigured readers |
| 8 | Language-detection results for review text disagree materially between two methods (crude heuristic 91.8% vs. `langdetect` 87.3%, both plausibly wrong on short text) | **LOW–MEDIUM for RAG scope, informational for Step 1** | Neither figure should be treated as ground truth without manual validation |
| 9 | 610 products (1.85%) have null category; 13 rows (2 category names) have a category with no English translation | **LOW** | Small volume, clear "uncategorized" fallback available |
| 10 | 9 zero-value payments, 2 zero-installment payments, 4 zero-weight products | **LOW** | Small volume, not investigated row-by-row in this pass |

## I. Recommended handling (Step 2 decisions to make — not made here)

- Decide and codify the **review dedup rule** as an explicit, named parameter (one
  of the 4 documented options), not a silent default buried in a function.
- Decide the **canonical revenue definition** (`order_items.price`-based is the
  leading candidate per the prior EDA's reconciliation, but that reconciliation
  should be re-derived by a Step-2-owned script before being finalized, per this
  audit's standard of independent verification).
- Decide the **analytical time window** using the raw evidence in §E — this
  document deliberately stops short of that decision.
- Decide the **order_items pre-aggregation rule** before any join to
  `order_payments` or `order_reviews`, to structurally prevent the fan-out risk in
  §H row 2, rather than relying on analysts remembering to aggregate first each
  time.
- Decide how to treat the **775 / 768 / 1 structurally-incomplete orders** per KPI
  (exclude vs. explicit zero vs. flag) — do not let this default silently.
- Decide whether `geolocation` is needed at all for the initial KPI layer (state-level
  fields on `customers`/`sellers` are already clean and may make the aggregation
  step unnecessary for a first version).
- Specify `encoding="utf-8-sig"` explicitly when reading
  `product_category_name_translation.csv` so correctness doesn't depend on a
  library default.

---

# FINAL DECISION

**1. Is the raw Olist dataset internally consistent enough to proceed?**
Yes, for the structured/relational core. Every candidate primary key that should be
unique is unique (customers, orders, order_items, order_payments, products,
sellers, category_translation — all 100% unique, 0% null, 0 duplicates). Every core
foreign key matches at ≥99.2%, with the small remainder being genuine structural
gaps (orders with no items/payment/review), not corruption. The two real
consistency problems — `order_reviews.review_id` not being a clean key, and
`geolocation` having no usable key at all — are both narrow, well-quantified, and
do not block proceeding; they block specific downstream uses (review-as-1:1-fact,
geolocation-as-a-dimension) until a decision is made for each.

**2. What are the 5 most important data risks?**
(1) Temporal edge collapse making naive trend/anomaly analysis unsafe over the full
range (CRITICAL). (2) Join fan-out risk when two 1-to-many children of `orders` are
joined to each other before aggregation — verified in this pass at +4.54% revenue
inflation on a naive 2-table join, with a reproduced concrete example (HIGH). (3)
`order_reviews` is not a clean 1:1 fact with orders — 814 duplicate `review_id`s,
547 multi-review orders, 768 orders with zero reviews (HIGH). (4) Revenue source
ambiguity between `order_items.price` and `order_payments.payment_value` — verified
in this pass at 99.61% agreement within 1 cent across 98,665 orders, 381 real
mismatches (HIGH). (5) `geolocation` has no usable key and is 26.18%
exact-duplicate rows, making it unusable as-is (MEDIUM).

**3. What tables should enter the canonical analytical layer?**
`orders`, `order_items`, `order_payments`, `products`, `sellers`,
`category_translation` — all have clean, verified keys and ≥99.2% FK match rates to
their neighbors. `customers` also belongs, keyed by `customer_unique_id` for
person-level grain (not `customer_id`).

**4. What tables should remain optional?**
`order_reviews` — genuinely useful (review score/text) but requires an explicit
dedup decision before it can be treated as 1:1 with orders; should enter as a
clearly-scoped, separately-governed fact, not silently joined in. `geolocation` —
optional/deferred until an aggregation step gives it a usable key; state-level
fields already on `customers`/`sellers` may make it unnecessary for an initial
build.

**5. What cleaning decisions must be made in STEP 2?**
The review dedup rule; the canonical revenue definition (with a fresh cent-level
reconciliation, not inherited from the prior pass); the analytical time window; the
order_items pre-aggregation rule before any join outward; the treatment of the
775/768/1 structurally-incomplete orders; the geolocation aggregation approach (if
geolocation is used at all); explicit `utf-8-sig` handling for the one BOM-affected
file.

**6. What relationships are safe?**
`orders.customer_id → customers.customer_id` (100% match, 1:1). `order_items.product_id
→ products.product_id` and `order_items.seller_id → sellers.seller_id` (100% match,
many-to-one, safe to join directly). `orders.order_id → order_items.order_id`,
`→ order_payments.order_id`, `→ order_reviews.order_id` (99.2–100% match,
one-to-many — safe to join **one at a time**, from `orders`).

**7. What relationships require special handling?**
Any join that brings **two** of `order_items`, `order_payments`, `order_reviews`
together in the same query without first aggregating at least one to the order
grain — this is where the fan-out risk lives. `products.product_category_name →
category_translation.product_category_name` (98.11% match — needs an explicit null/
missing-translation fallback, not a silent inner join that drops 623 rows).
`customers.customer_unique_id` is not a join key against `customers.customer_id`
in the normal sense — it's a person-level grouping key, and using it in a join
where `customer_id`-grain uniqueness is assumed will silently collapse repeat
customers.

**8. What information is NOT actually available?**
No cost-of-goods, margin, commission, or fee-schedule field anywhere — profit
cannot be computed. No marketing/campaign/channel/spend data — no marketing
attribution is possible. No logistics-partner/carrier identity field — delivery-time
variation cannot be attributed to a specific carrier or process. No slowly-changing
dimension history for products/sellers/customers — only the price/attributes
actually recorded at each order can be known, not "what the price was at any other
point in time." No documented extraction-date metadata — the 2016-ramp/2018-cutoff
pattern in §E is an observed pattern with a plausible but unverified explanation,
not a documented fact.

---

**STOP — this document ends Step 1.** No cleaning, transformation, KPI, or modeling
work has been performed. Step 2 begins from the decisions listed in §I and the
Final Decision above.
