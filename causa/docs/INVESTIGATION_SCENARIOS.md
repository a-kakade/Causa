# Investigation Scenarios

All movements, contradictions, and sparse-history figures below are measured
directly from the real dataset (window restricted to **2017-02 through 2018-08**,
excluding the platform-ramp and extraction-cutoff months per
`DATA_QUALITY_REPORT.md` §2, unless otherwise noted) via `scripts/kpi_temporal_eda.py`
and `scripts/join_driver_anomaly_eda.py`. Nothing here is manufactured — candidates
were selected from the ranked material-movements output, not hand-picked to fit a
narrative.

---

## 1. Anomaly / materiality candidates (ranked)

### 1. BEST DEMO — November 2017 order & revenue surge

| | |
|---|---|
| KPI | Orders, Revenue |
| Period | 2017-11 vs 2017-10 |
| Baseline (Oct 2017) | 4,631 orders / R$664,219.43 |
| Observed (Nov 2017) | 7,544 orders / R$1,010,271.37 |
| Absolute change | +2,913 orders / +R$346,051.94 |
| % change | **+62.9% orders / +52.1% revenue** |
| Business magnitude | Largest single-month revenue jump in the reliable window |
| Affected segments | Broad-based: **all 27 customer states** placed orders in both months; growth concentrated in general home-goods categories (cama_mesa_banho +430 items, moveis_decoracao +404, ferramentas_jardim +269 — see `RELATIONSHIP_GRAPH.md`/plots), not one narrow SKU |
| Deterministic drivers available | **Volume effect +R$417,227.65, Price effect +R$4,674.63, Mix effect −R$75,850.34** (PVM bridge, fully reproducible, see §PVM below) — arithmetic checksum confirms Volume+Price+Mix = ΔRevenue exactly |
| Statistical evidence | Z-score of the MoM change vs. trailing 3-month rolling std is a clear outlier (visible in `eda_plots/kpi_monthly_overview.png` and `pvm_bridge_oct_nov_2017.png`) |
| Structured evidence | Order/revenue/quantity/category/state breakdowns — all available |
| Unstructured evidence | Review volume also spikes to 7,544/month; review score dips from 4.124 to 3.911 in the same month (see Contradiction §2) — reviewable via `review_comment_message` for the ~41% with text |
| Ambiguity | Genuine: is the growth "all good" (volume win) or does the negative Mix effect (−R$75,850) mean the growth basket skewed toward lower-priced categories? Both are defensible readings of the same numbers — see Contradiction §3 |
| Enough history | Yes — 10 reliable months before and 9 after for context |
| Likely real-world cause | **Hypothesis, not confirmed by this dataset**: this window matches Brazil's Black Friday period (last Friday of November). The dataset contains no explicit promotion/campaign flag, so this is inferred from the calendar date alone, not verified against an internal Olist marketing field. |

### 2. STRONG — December 2017 post-surge pullback

| | |
|---|---|
| KPI | Orders, Revenue |
| Period | 2017-12 vs 2017-11 |
| Baseline | 7,544 orders / R$1,010,271.37 |
| Observed | 5,673 orders / R$743,914.17 |
| % change | −24.8% orders / −26.4% revenue |
| Business magnitude | Second-largest movement in the window |
| Affected segments | Not yet broken down by segment in this pass — recommended follow-up |
| Drivers | Deterministically the mirror of §1 (Volume/Price/Mix bridge computable the same way); plausibly demand pulled forward into November — **hypothesis**, not proven without a demand-forecasting baseline this dataset doesn't support |
| Evidence | Structured: full. Unstructured: review volume also drops with orders. |
| Ambiguity | Is this a real pullback or simply reversion to the pre-November trend line? The Jan–Aug 2018 series (950K, 844K, 983K, 997K, 997K, 865K, 896K, 855K) shows revenue actually *exceeds* pre-November 2017 levels afterward, suggesting December is a genuine post-peak dip, not a return to baseline — worth an explicit investigation scenario. |

### 3. STRONG — November 2017 delivery-time spike

| | |
|---|---|
| KPI | Avg delivery days |
| Period | 2017-11 vs 2017-10 |
| Baseline | 11.86 days |
| Observed | 15.16 days (stays elevated through Feb 2018: 15.39, 14.08, **16.95**) |
| % change | +27.9% MoM, +42.9% by Feb 2018 vs Oct 2017 |
| Business magnitude | Directly mechanistically linked to §1 — volume surge outpacing fulfillment capacity is a defensible, deterministic hypothesis (more orders, same seller/logistics base) |
| Affected segments | Not yet broken down by seller/state in this pass — recommended follow-up before final demo build |
| Evidence | Structured: full monthly series. Statistical: correlation between avg_delivery_days and avg_review_score across all reliable months = **−0.942** — strong, consistent with delivery time being a genuine satisfaction driver at the aggregate level |
| Ambiguity | Low at the aggregate level (the correlation is strong and directionally expected) — the real ambiguity is at the order level, see Contradiction §1 |

### 4. MODERATE — April 2018 delivery-time improvement

| | |
|---|---|
| KPI | Avg delivery days |
| Period | 2018-04 vs 2018-03 |
| Observed | 11.50 days, a −29.5% MoM improvement off a locally elevated base |
| Business magnitude | Real, but smaller and requires a full quarter of comparison to confirm it isn't noise — one month is not yet a trend |
| Drivers | Unknown from this dataset — no logistics-partner or process-change field exists to attribute the improvement |
| Evidence | Structured only; no text data explains *why* delivery improved |
| Ambiguity | High — a genuinely honest "we don't know why" case, useful as an abstention-scenario demo rather than a confident-attribution demo |

### 5. MODERATE — May 2017 platform growth

| | |
|---|---|
| KPI | Orders, Revenue |
| Period | 2017-05 vs 2017-04 |
| Observed | +53.9% orders (2,404→3,700), +40.6% revenue |
| Business magnitude | Large %, but occurs during the platform's early scaling phase (order volume roughly doubled every 1–2 months from 2017-01 to 2017-08) — less a discrete "event" than a continuation of onboarding growth |
| Drivers | Plausibly seller-base growth (more sellers onboarding) rather than a demand event — **not verified** here; would need seller `date_first_sale` proxy (first order_item date per seller) cross-referenced, which is feasible but not yet run |
| Ambiguity | Low interest for a demo — attributing "why" is speculative without more work, downgraded from STRONG for that reason |

### 6. NOT SUITABLE (flagged deliberately, as instructed) — Oct 2016 / Jan 2017 "spikes"

The raw material-movements scan flags things like "orders +8,000% in Oct 2016" and
"revenue +1,103,688% in Jan 2017." These are **artifacts of the platform-ramp period**
(base month has 0–4 orders — see `DATA_QUALITY_REPORT.md` §2), not real business
movements. Included here explicitly to document that they were found and
deliberately excluded, not overlooked.

---

## 2. PVM decomposition detail (Oct → Nov 2017, referenced above)

```
ΔRevenue = R$346,051.94
  = Volume effect  (+R$417,227.65)   -- more units sold, at Oct's average price
  + Price effect    (+R$4,674.63)     -- avg price per category ticked up slightly
  + Mix effect      (−R$75,850.34)    -- the additional units skewed toward
                                          lower-average-price categories
  checksum: 417,227.65 + 4,674.63 − 75,850.34 = 346,051.94 ✓ (exact match)
```

Top revenue-contributing categories in the surge: cama_mesa_banho (+43,214.54),
beleza_saude (+37,204.68), moveis_decoracao (+32,996.46). Full table and chart in
`reports/join_driver_anomaly_summary.json` and `eda_plots/pvm_bridge_oct_nov_2017.png`.
**Caveat (repeated from `KPI_CANDIDATES.md`):** category-level avg price mixes
different SKUs within a category — this is a category-mix decomposition, not a
true like-for-like SKU price change, because no list-price/promo-price field exists
to isolate discounting.

---

## 3. Contradiction candidates

### Contradiction 1 — "Fast delivery, unhappy customer" (structured vs. unstructured)

**Structured signal:** 7,205 orders (7.48% of all reviewed orders) were delivered
**≥5 days ahead of the estimated delivery date** yet received a review score ≤2.
A naive "delivery speed drives satisfaction" model (supported by the aggregate
−0.942 correlation above) would not predict unhappy customers here.

**Unstructured signal:** sampling the actual review text for these orders shows the
complaints are about **product/fulfillment quality, not delivery speed** — wrong
item variant shipped, item missing from the package, product damaged/inferior, or
(paradoxically) the system marking the order "delivered" while the customer reports
not receiving it. None of the sampled complaints mention delivery being too slow.

**Why this matters for Causa:** this is exactly the kind of case where a
deterministic structured KPI (delivery was fast) and the qualitative evidence
(customer is still unhappy, for an unrelated reason) diverge — a strong
Prosecutor-vs-Defense scenario: "Defense" cites fast delivery as evidence of good
operations; "Prosecutor" must pull review text to show the real driver is product
quality/fulfillment accuracy, not logistics.

### Contradiction 2 — "Revenue up, satisfaction down" (structured vs. structured)

In November 2017, revenue rose 52.1% MoM — a headline commercial win — while in the
same month avg review score fell from 4.124 to 3.911 (a real, non-trivial drop given
the −0.942 delivery/score correlation, itself driven by the delivery-time spike in
the same month, see Candidate §3). A revenue-only dashboard would read this as an
unambiguous success month; the review-score series tells a different story about
customer experience cost.

### Contradiction 3 — "Growth story conceals a mix shift" (structured vs. structured, same metric)

The Nov 2017 revenue surge (+R$346,051.94) decomposes to Volume +R$417,227.65 but
Mix **−R$75,850.34** — i.e., a meaningful share of the "growth" came from customers
buying into lower-average-price categories, not from uniform demand growth across
the existing mix. A single "revenue +52%" headline hides this; the PVM bridge does
not. This is a genuine analytical tension defensible entirely from `order_items` +
`products`, no external data required.

### Checked and NOT found (reported honestly, not omitted)

- **Order value vs. satisfaction**: correlation between order-level price and review
  score is **−0.04** — essentially no relationship. The intuitive hypothesis "expensive
  orders get pickier reviews" is **not supported** by this dataset.
- **Late delivery, happy customer**: exists (906 orders, 0.94% of reviews, delivered
  ≥3 days late yet scored ≥4) but is an order of magnitude smaller than Contradiction
  1 and the sampled text is mostly generic positive comments, not a rich "why" — a
  weaker candidate, documented for completeness rather than promoted as a scenario.

---

## 4. Sparse-history analysis

Computed over delivered order_items only (96,478 delivered orders' line items):

| Entity | n entities | <30 observations | <90 observations | <180 observations | Median observations |
|---|---|---|---|---|---|
| Products | 32,216 (of 32,951 total; 735 never sold in a delivered order) | 31,840 (**98.83%**) | 32,149 (99.79%) | 32,199 (99.94%) | **1** |
| Sellers | 2,970 (of 3,095 total; 125 with zero delivered transactions) | 2,288 (**77.04%**) | 2,701 (90.94%) | 2,854 (90.94%→92.24 rounding, see JSON) | **8** |
| Categories | 73 total | 8 categories (11.0%) have <30 observations (smallest: `seguros_e_servicos` n=2, `fashion_roupa_infanto_juvenil` n=7, `pc_gamer` n=8) | — | — | — |

**This is not a marginal edge case — it is the dominant pattern.** The median
product has been sold exactly **once**. A per-product statistical baseline
(mean/std of historical sales) is meaningless for the overwhelming majority of the
catalog. Category-level aggregation is necessary for almost every product, and even
category-level baselines are unreliable for 8 of 73 categories (<30 observations).

**Defensible fallback hierarchy, in order:**
1. Entity (product/seller) baseline — usable for a small minority (median 1 obs for
   products means this is rarely usable; sellers fare better, median 8, still thin).
2. Category baseline — usable for 65 of 73 categories (>30 obs each); the largest
   (cama_mesa_banho, 10,953 obs; beleza_saude, 9,465; esporte_lazer, 8,431) are
   statistically solid.
3. Regional (state) baseline — computable (23 seller states, 27 customer states),
   not yet volume-tested per category × state cell, flagged as a follow-up.
4. Global/platform baseline — always available (96,478 delivered order_items, 20
   reliable months).

This hierarchy is a real requirement, not a nice-to-have: **any product-level or
seller-level Causa KPI investigation will hit the sparse-history wall almost
immediately** and must fall back at least one, often two, levels.

---

## 5. Segmentation / persona feasibility

| Dimension | Cardinality | Usable for personas? |
|---|---|---|
| customer_state | 27 | Yes — SP dominates (40,501 of ~96K delivered orders), long tail to AP (67)/RR (41); an "all-region executive" vs "SP regional manager" split is realistic and volume-balanced only for the top ~10 states |
| seller_state | 23 | Yes, with a caveat: SP alone = ~61% of item-level revenue (8.51M of 13.9M); a "seller ops manager for a small state" persona would have very little data to work with |
| seller_id | 3,095 | Yes for top sellers (top 20 = 21.28% of revenue); NOT usable for the median seller (8 transactions) without falling back to state/category |
| product_category_name | 73 | Yes for the ~65 categories with real volume; NOT usable standalone for the 8 sparse categories |
| customer_unique_id | 96,096 | Not usable as a segmentation axis directly (96% only ever place 1 order) — only usable in aggregate (e.g., repeat vs. one-time customer cohort, which is itself supported: 3.12% repeat) |

**Realistic persona split for a demo:** (a) **Executive** — all-region, all-category
KPI view, backed by the full 20-month reliable series; (b) **Regional/Category
Operations Manager** — e.g. "seller ops for cama_mesa_banho in SP," backed by
real, statistically solid volume (SP + a top-5 category both clear the 30-observation
bar independently). A seller-specific persona is defensible only for the handful of
sellers above the top-20 threshold; below that, the honest answer is "insufficient
history for a seller-level view," which is itself a valid abstention scenario.

---

## 6. Security / PII audit

| Field | Table | Classification | Notes |
|---|---|---|---|
| customer_id, customer_unique_id | customers, orders | SENSITIVE | Pseudonymous ID; re-identification risk when combined with zip+city+order timing (a known re-identification vector for "anonymized" transaction data), even though no name/email/phone exists |
| customer_zip_code_prefix, customer_city, customer_state | customers | INTERNAL | Coarse geography; low individual re-identification risk alone, should still be access-controlled at row level, safe as an aggregate dimension |
| seller_id | sellers, order_items | INTERNAL | Business entity, not a private individual — lower sensitivity than customer IDs, but still excluded from any externally-facing LLM context by default (competitive-sensitivity, not privacy) |
| review_comment_message / title | order_reviews | INTERNAL, spot-check SENSITIVE | No PII regex matches found in this pass (0 email, 4 loose phone-like false-positive candidates, 2 URLs) — but free text from real people can still contain incidental self-disclosed information (names typed by the reviewer, order numbers) that a regex sweep won't catch; **must not be assumed clean** without a manual sample review before any RAG build |
| geolocation lat/lng | geolocation | INTERNAL | Precise enough (raw GPS samples) to be sensitive if ever joined down to individual customer records; safe only as an aggregated regional layer |
| All other ID/master fields | all tables | PUBLIC-within-system | Product/category/order IDs carry no personal information |

**Should be:**
- **Hidden from LLM context by default:** customer_id, customer_unique_id, raw
  geolocation lat/lng.
- **Access-controlled (row/segment level):** seller_id and seller-level financial
  detail, for the seller-persona scenario in §5.
- **Excluded from RAG embeddings without review:** none required by the injection
  scan (0 matches — see below), but a manual pass over a larger review-text sample
  is recommended before production use, since the regex sweep is a floor, not a
  guarantee.

**Prompt-injection surface:** the review-text corpus was swept with a
pattern-matching filter (`ignore instructions`, `system prompt`, `act as`,
`jailbreak`, API-key patterns, etc.) — **0 of 40,950 non-empty review messages
matched.** This is reported as a genuine negative result: this specific corpus does
not currently contain obvious injection payloads. **This does not mean the security
layer is unnecessary** — it means Causa's security-test fixtures for the RAG layer
will need to be **synthetically constructed** (clearly labeled as synthetic test
data, not disguised as real reviews) rather than mined from this dataset, since real
injection-like content was not found here.
