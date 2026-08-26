# Causa — EDA Report (Olist Brazilian E-Commerce Dataset)

**Date:** 2026-08-26 · **Source:** Kaggle "Brazilian E-Commerce Public Dataset by
Olist" (`archive.zip`, extracted to `data/raw/olist/`) · **Scope:** exploratory data
analysis only — no agents, RAG, causal engine, or frontend were built for this
milestone.

This report is the entry point. Detail lives in the companion documents:
[DATA_DICTIONARY.md](DATA_DICTIONARY.md), [DATA_QUALITY_REPORT.md](DATA_QUALITY_REPORT.md),
[RELATIONSHIP_GRAPH.md](RELATIONSHIP_GRAPH.md), [DATA_LINEAGE.md](DATA_LINEAGE.md),
[KPI_CANDIDATES.md](KPI_CANDIDATES.md), [INVESTIGATION_SCENARIOS.md](INVESTIGATION_SCENARIOS.md).
Plots: `eda_plots/`. Machine-readable profiling: `data/raw/olist/_profile_summary.json`,
`reports/kpi_eda_summary.json`, `reports/text_eda_summary.json`,
`reports/join_driver_anomaly_summary.json`.

Standard applied throughout: **every claim below is backed by a number computed in
this pass.** Where something is inferred rather than directly observed, it is
labeled "inferred" or "hypothesis." Where the data cannot support a claim, that is
stated explicitly rather than glossed over.

---

## Executive summary

The Olist dataset is a **single, well-formed relational export** of ~2 years
(2016-09 to 2018-10) of a real Brazilian e-commerce marketplace's orders, items,
payments, reviews, products, and sellers. The core relational graph is genuinely
clean — **zero foreign-key orphans** across the order→customer/item/payment/
review/product/seller chain, and revenue reconciles between the item-price and
payment tables for 99.61% of orders. It supports deterministic KPI calculation,
real PVM (price/volume/mix) driver decomposition, and a strongly evidenced
sparse-history problem (the median product has been sold exactly once).

It has three hard limits that must shape what Causa claims: (1) **only 20 of the
~26 raw calendar months are usable** — the first 4 and last 2 are extraction/ramp
artifacts that would produce spurious anomalies if not excluded; (2) **the only
unstructured field is review text, and only 41% of reviews carry any** — RAG scope
is real but narrow, not a general-purpose document corpus; (3) **no cost, margin,
marketing, or external-calendar data exists** — profit, marketing attribution, and
genuine multi-system reconciliation are out of scope unless a real external source
is added.

---

## 1–3. Dataset understanding, quality audit, relationships

Fully detailed in `DATA_DICTIONARY.md`, `DATA_QUALITY_REPORT.md`, and
`RELATIONSHIP_GRAPH.md`. Headlines:

- 9 tables, 99,441 orders, 112,650 order items, 32,951 products, 3,095 sellers,
  99,224 reviews (814 duplicate `review_id`s), 1,000,163 geolocation rows (26.2%
  exact duplicates).
- Zero FK orphans on the core order graph; the only integrity gap is 2 product
  categories missing an English translation.
- **CRITICAL finding:** temporal coverage collapses to near-zero at both edges
  (2016-09→2016-12 ramp, 2018-09→2018-10 extraction cutoff) — any trend/anomaly
  work must restrict to **2017-01/02 through 2018-08**.
- **HIGH finding:** naively joining `orders ⋈ order_items ⋈ order_payments ⋈
  order_reviews` before summing `price` inflates revenue by **4.04%**, reproduced
  concretely on order `03ecec245220b63fd7f68c1737ba99ba` (2× inflation from 2
  payment rows). The KPI layer must always pre-aggregate `order_items` to order
  grain before joining outward.
- **HIGH finding:** `SUM(order_items.price)` and `SUM(order_payments.payment_value)`
  agree within 1 cent for 99.61% of orders present in both — `order_items.price`
  is adopted as the revenue source of truth because it is PVM-decomposable and
  `payment_value` (which includes financing interest) is not.

## 4–5. Temporal EDA & KPI candidates

Full detail in `KPI_CANDIDATES.md` and `reports/kpi_timeseries_monthly.csv`/`_weekly.csv`.
Five candidate KPIs were verified against the schema and computed at daily/weekly/
monthly grain over the reliable window: **Orders, Revenue, AOV, Freight, Avg
Delivery Days, Avg Review Score, Review Volume.** All are additive/consistent up
the order→category/seller/state hierarchy once the fan-out rule above is applied.
Rejected as **not currently defensible**: Profit/Margin (no cost data), Marketing-
attributed revenue (no marketing data), true LTV (thin 3.12% repeat-customer base
+ no margin data), Return/Refund rate (no explicit return event).

**Important caveat on seasonality/YoY**: the dataset contains only **one** full
November–December cycle inside the reliable window (2017); 2018 data ends in
August, before a second Black Friday would occur. Any "seasonal pattern" claim
from this data describes **one observed instance**, not a confirmed recurring
seasonal effect — say so explicitly rather than implying a validated annual
pattern. Year-over-year comparisons are further complicated because 2017 itself
was a high-growth ramp year for the platform (order volume roughly quadrupled from
Feb to Nov 2017), so a naive YoY % change conflates organic platform growth with
any real seasonal or event-driven effect.

## 6. Driver decomposition feasibility

| Driver | Status | Basis |
|---|---|---|
| Price | **SUPPORTED** | `order_items.price` directly; PVM price effect computed and checksum-verified for Oct→Nov 2017 |
| Volume | **SUPPORTED** | `COUNT(order_item_id)`; PVM volume effect computed |
| Mix | **SUPPORTED** | Category-level revenue share shift computed as a residual, checksum-verified |
| Product | **SUPPORTED** at category grain, **NOT** at individual-product grain for 98.83% of the catalog | Sparse history (median 1 obs/product) — see §10/`INVESTIGATION_SCENARIOS.md` §4 |
| Seller | **PARTIALLY SUPPORTED** | seller_id/seller_state available, revenue concentration measurable (top 20 = 21.28%); no seller cost/commission/performance-tier data exists |
| Geography | **PARTIALLY SUPPORTED** | State-level only, both customer and seller side; city-level requires deduplicating the noisy `geolocation` table (not yet done) and is not currently reliable |
| Freight | **SUPPORTED** | `order_items.freight_value`, directly summable, no known quality issues |
| Delivery | **PARTIALLY SUPPORTED** | Delivery time/on-time rate computable and correlate with review score (−0.942 monthly); survivorship-biased (2.98% of orders excluded for missing delivery date); no carrier/logistics-partner field to explain *why* delivery time varies |
| Customer segment | **PARTIALLY SUPPORTED** | State + repeat-vs-one-time split only; no demographic/behavioral/lifecycle fields |
| Marketing | **NOT SUPPORTED** | No channel, spend, or campaign data anywhere in the dataset |
| Seasonality | **SUPPORTED, weakly** | Observable in the series but only one full annual cycle inside the reliable window — see caveat above |

**Decomposition actually demonstrated (not just claimed):**
`Revenue change (Oct→Nov 2017) = Volume effect (+417,227.65) + Price effect
(+4,674.63) + Mix effect (−75,850.34) = +346,051.94` — exact arithmetic checksum,
fully reproducible from `order_items` + `products` alone. Full detail in
`INVESTIGATION_SCENARIOS.md` §2.

## 7–8. Structured + unstructured data / RAG feasibility

The dataset has exactly **one** substantive unstructured field:
`order_reviews.review_comment_message`.

| Property | Value |
|---|---|
| Documents | 99,224 review rows; 40,950 with non-empty message (41.27%) |
| Language | 91.8% Portuguese-likely by a crude stopword/diacritic heuristic (not a validated classifier — re-verify with a real detector before RAG build) |
| Length | mean 68.7 chars / 11.7 words; median 53 chars / 9 words; **max 208 chars / 45 words** (the field appears to have a hard cap, not organically short) |
| Empty rate | 58.73% |
| Duplicate rate | 14.59% of non-empty messages are exact duplicates ("Muito bom" ×230, "Bom" ×189) — heavy boilerplate |
| Entity linkage | 95.97% of reviews link unambiguously to exactly one product (via order_items), 97.95% to exactly one seller; the remaining ~3-4% (multi-item orders) are genuinely ambiguous — a review cannot be deterministically attributed to one product/seller from structured data alone for those |
| PII scan | 0 email matches, 4 loose phone-like false-positive candidates, 2 URLs, 0 HTML artifacts |
| Prompt-injection scan | 0 of 40,950 messages matched an injection-pattern sweep |

**Can Causa retrieve unstructured evidence specifically tied to a KPI movement?**
Yes, but narrowly: for a single-item order with review text, retrieval by
`order_id → product_id/seller_id/category/month` is fully deterministic. For a
multi-item order, or for any order without review text (59% of reviews, plus 0.77%
of orders with no review at all), no unstructured evidence exists or can be
uniquely attributed. **This is not a general-purpose RAG corpus** — it is a
narrow, well-linked but sparse evidence layer that should be scoped honestly as
such, not oversold as "semantic search over rich customer feedback."

## 9. Multi-grain / multi-cadence analysis

Full detail in `DATA_LINEAGE.md`. The dataset genuinely supports **multi-grain
analysis within one source** (event → daily → weekly → monthly → category-month →
state-month, all verified). It does **not** genuinely support the brief's
**multi-cadence, multi-system reconciliation** requirement (e.g., a daily ops feed
reconciled against a monthly finance close from an independent system) — there is
only one underlying transactional source here. **Recommendation: add one real,
freely available external source** — a Brazilian public holiday/Black-Friday
calendar — to reconcile against the observed Nov 2017 spike, satisfying the
requirement honestly rather than simulating multi-source heterogeneity that doesn't
exist. Do not fabricate a synthetic marketing-spend or finance-close file to paper
over this gap.

## 10. Sparse-history analysis

**This is one of the dataset's strongest, most defensible characteristics.**
98.83% of products (31,840 of 32,216 with any delivered sale) have fewer than 30
delivered transactions; the **median product has been sold exactly once**. Sellers
are less extreme but still thin: 77.04% have <30 observations, median 8. A
defensible 4-level fallback hierarchy (entity → category → region → global) is
laid out with real volume counts in `INVESTIGATION_SCENARIOS.md` §4 — this is not
a hypothetical edge case Causa might someday encounter, it is the dominant
condition of this catalog and must be a first-class part of the baseline design,
not an afterthought.

## 11. Segmentation / persona feasibility

State (customer and seller) and category are the only dimensions with enough
independent volume to support realistic personas; seller-level and small-state
personas hit the sparse-history wall almost immediately. Full table and a
recommended persona split (Executive vs. Regional/Category Ops Manager) in
`INVESTIGATION_SCENARIOS.md` §5.

## 12–14. Anomalies, contradictions, sparse-history candidates

Six ranked anomaly candidates (1 BEST DEMO, 2 STRONG, 2 MODERATE, 1 explicitly
flagged NOT SUITABLE with the reason why), three real contradiction candidates,
and the sparse-history entity list are all in `INVESTIGATION_SCENARIOS.md` §1–4.
Headline: the **November 2017 order/revenue surge**, fully PVM-decomposable and
broad-based across all 27 states, is the strongest demo material this dataset
offers, and it comes with a genuine, textually-evidenced contradiction (fast
delivery does not protect against low satisfaction when the real complaint is
product/fulfillment quality — 7.48% of reviewed orders show this pattern with real
sampled quotes).

## 15. Security / PII audit

Full classification table in `INVESTIGATION_SCENARIOS.md` §6. Headline: the
dataset is pre-anonymized (no name/email/phone/address fields anywhere), which is
good for privacy but means **no organic prompt-injection or PII content was found**
in the review corpus — security-layer test fixtures will need to be synthetically
constructed and clearly labeled as such, not mined from this data.

---

## 16. Final data suitability score

| Requirement | Score /10 | Evidence | Gap |
|---|---|---|---|
| 3–5 connected KPIs | 9 | Orders/Revenue/AOV/Freight/Delivery/Review all share the `order_id` grain, verified reconciliation, deterministic aggregation rule | No profit/margin KPI possible |
| Multiple grains/cadences | 5 | Strong multi-grain within one source (event→daily→weekly→monthly→category/state) | No genuine multi-cadence/multi-system heterogeneity; needs 1 real external source |
| Structured data | 9 | Zero FK orphans, clean core keys, verified revenue reconciliation | Geolocation table needs dedup work before use |
| Unstructured data | 5 | One real text field, 96-98% entity-linkable when present | Only 41% coverage, short/templated, single language, single field type |
| KPI semantic contract | 8 | Formulas, grains, and reliability documented and schema-verified in `KPI_CANDIDATES.md` | Not yet a machine-enforced contract (schema/validation code) |
| Driver decomposition | 7 | PVM fully demonstrated and checksum-verified | Several drivers only partially supported; marketing entirely unsupported |
| Materiality | 8 | 6 ranked real candidates with magnitude, segments, and evidence availability | Only ~20 months of history — no multi-year materiality possible |
| Persona personalization | 6 | State/category personas well-powered and defensible | Seller/small-state personas hit sparse-history wall; no real org-role field |
| Sparse history | 9 | Extremely well-evidenced (98.83% products <30 obs), clear fallback hierarchy | — |
| Ambiguity/abstention | 7 | Multiple genuine "we don't know why" and "two valid readings" cases found | Not exhaustively tested across every KPI type |
| Security | 6 | Clean PII posture confirmed by regex sweep, clear sensitivity classification | 0 organic injection content found — fixtures must be synthetic |
| Feedback | 2 | Review score is feedback on the *business*, not on Causa's own outputs | This is a product-build requirement the raw data cannot satisfy at all |
| LLM/non-LLM separation | 8 | Clean boundary: PVM/KPI math is 100% deterministic; only review-text synthesis needs an LLM | — |

## OVERALL DATASET SCORE: 7/10

The dataset is a strong, real, well-formed foundation for the structured half of
Causa (KPIs, driver decomposition, materiality, sparse-history handling) and
adequate but narrow for the unstructured half (RAG scope must be framed honestly
as thin, single-field, single-language). It cannot, on its own, satisfy genuine
multi-system-cadence reconciliation, any feedback-on-Causa's-own-output loop, or
a rich adversarial-content security demo — each of those needs either an added
real external source or synthetic, clearly-labeled fixtures, not a claim that the
raw data already provides them.

---

# 17. WHAT SHOULD WE BUILD?

Based only on this EDA:

1. **Primary business problem/KPI**: Revenue — the most complete, most
   decomposable, and richest-anomaly KPI in the dataset (Nov 2017 spike, verified
   PVM decomposition, connected review-text evidence).
2. **The KPI graph** (5 KPIs, all sharing the `order_id` grain, verified
   connected): Orders → Revenue (= AOV × Orders) → AOV (decomposes to Price × Volume
   × Mix) ↔ Avg Delivery Days ↔ Avg Review Score. The Nov 2017 case study is the
   concrete proof these are genuinely connected, not just co-located in the same
   schema.
3. **Best investigation scenario**: "Revenue jumped 52% in November 2017 — was it
   unambiguously good news?" Combines materiality, deterministic PVM decomposition,
   a genuine structured contradiction (negative Mix effect, satisfaction dip), and
   available text evidence — the single richest scenario this dataset supports.
4. **Best anomaly to demonstrate**: the November 2017 order/revenue surge (ranked
   #1 BEST DEMO in `INVESTIGATION_SCENARIOS.md`).
5. **Top 5 explanatory drivers**: Volume effect, Price effect, Mix effect (all
   deterministic PVM), Delivery-time strain (statistical correlation to
   satisfaction), Category concentration (deterministic revenue contribution).
6. **Calculated deterministically**: Volume, Price, Mix effects; Freight; Revenue/
   AOV/Quantity at any grain; category/state revenue contribution.
7. **Requiring statistical analysis**: delivery-time↔review-score correlation and
   its monthly stability; anomaly z-scoring against rolling mean/std; sparse-history
   baseline selection (does an entity clear the 30-observation bar, yes/no).
8. **Requiring RAG/LLM reasoning**: synthesizing *why* fast-delivered orders still
   score low (the review text explains what the structured data can't); narrating
   the PVM bridge in business language for a non-technical user.
9. **Best unstructured evidence**: the fast-delivery/low-score review sample
   (7,205 orders, 7.48% of reviews) — real, sampled, on-topic quotes showing the
   actual complaint is product/fulfillment quality, not logistics.
10. **Best ambiguity scenario**: the April 2018 delivery-time improvement
    (−29.5% MoM) with no attributable cause in the data — a legitimate, honest
    "the data shows the effect but not the cause" abstention demo.
11. **Best sparse-history scenario**: any of the 31,840 products with <30
    observations (median product = 1 sale) needing category/global baseline
    fallback — e.g., a product in `pc_gamer` (n=8 category-wide) or
    `la_cuisine` (n=14) demonstrating the entity→category→global cascade concretely.
12. **Best persona split**: Executive (all-region, all-category) vs. Regional/
    Category Operations Manager (e.g., São Paulo + `cama_mesa_banho`, the single
    largest state×category cell, both independently well-powered).
13. **Minimum external dataset required**: a real Brazilian public holiday /
    Black Friday calendar (freely available), to formally satisfy the multi-source
    reconciliation requirement against the observed Nov 2017 spike, without
    fabricating a marketing-spend or finance-close file that doesn't exist.
14. **Data that should NOT be used**: `geolocation` joined without deduplication
    (26.2% exact-duplicate rows will silently distort any join);
    `order_payments.payment_value` as "the" revenue KPI (includes financing
    interest, not PVM-decomposable); raw `review_id` without the dedup rule (814
    duplicates); city-level text fields without normalization (casing/accent
    inconsistencies not yet audited).
15. **Claims Causa must NOT make from this data**: profit or margin (no
    cost-of-goods field exists anywhere); marketing attribution of any kind (no
    channel/spend/campaign data); a validated recurring seasonal pattern (only one
    full annual cycle is observed); true customer LTV (3.12% repeat-purchase base
    and no margin data make it indefensible as stated); a causal — as opposed to
    correlational — claim that delivery time *causes* satisfaction changes (a
    −0.942 monthly correlation is strong evidence, not proof, absent a controlled
    comparison); real-time freshness (this is a static historical snapshot ending
    2018-10); or genuine multi-system data reconciliation without first adding the
    external source named in #13.
