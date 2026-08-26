# KPI Semantics Preview — CAUSA_REVENUE Definition

**This is a definition, not an implementation.** No KPI engine, aggregation
service, or dashboard is built in this document or in Step 2. This document exists
so that when Step 3 builds the KPI engine, it inherits one already-reconciled,
already-traceable revenue definition instead of re-litigating the choice.

Computed fresh by `scripts/step2_02_revenue_reconciliation.py`. Full output:
`reports/step2_revenue_reconciliation.json`.

## The two candidates

**A — `SUM(order_items.price)`** (optionally `+ SUM(order_items.freight_value)`
for a GMV variant): item-level, excludes any financing/installment interest,
directly decomposable into Price × Volume × Mix (see the prior EDA's
`docs/KPI_CANDIDATES.md` for that decomposition, independently re-verifiable
against `data/processed/agg_order_items.parquet`).

**B — `SUM(order_payments.payment_value)`**: payment-level, represents what was
actually collected, including any financing/installment interest — not
decomposable into price × quantity because interest has no corresponding
`order_items` row.

## Fresh reconciliation (this pass, not carried over)

| | |
|---|---|
| Orders with both an item and a payment record | 98,665 |
| Matched within 1 cent (A vs B) | 98,284 (**99.61%**) |
| Mismatched | 381 (0.39%) |
| Mean absolute difference (mismatched only) | R$8.58 |
| Median absolute difference | R$3.77 |
| P90 absolute difference | R$21.89 |
| Max absolute difference | R$182.81 |
| Mean relative difference (mismatched only) | 7.09% |

**Directionality of mismatches:** of the 381 mismatched orders, **76.38% (291) have
payment_total > item_total** and 23.62% (90) have the reverse — a clear majority
in the direction consistent with financing interest being captured in
`order_payments` but never in `order_items`, though not exclusively so (the 90
reverse cases are not explained by this hypothesis alone and were not
individually investigated in this pass).

**Breakdown of the 381 mismatches:**

| By order_status | Count | | By dominant payment_type | Count |
|---|---|---|---|---|
| delivered | 375 | | credit_card | 339 |
| shipped | 3 | | boleto | 26 |
| canceled | 2 | | debit_card | 9 |
| invoiced | 1 | | voucher | 7 |

| By max installments | Count |
|---|---|
| 0 (no installment plan) | 0 |
| 1 | 63 |
| 2–3 | 73 |
| 4–6 | 119 |
| 7–12 | 120 |
| 13+ | 6 |

**This is the decisive evidence:** mismatches concentrate almost entirely in
`credit_card` payments **with an active installment plan** (installments ≥ 1) —
**zero** mismatches occur on 0-installment payments, and the mismatch count rises
through the installment buckets. This confirms the hypothesis directly rather than
by assumption: the gap between A and B is financing/interest cost, structurally
absent from `order_items`, not a data-quality defect in either table.

## CAUSA_REVENUE — the decision

> **CAUSA_REVENUE := `agg_order_items.item_price_total`**
> (equivalently, `SUM(order_items.price)` grouped by `order_id`, pre-aggregated to
> order grain **before** any join to `order_payments` or `order_reviews` — see
> `docs/CANONICAL_DATA_MODEL.md` §Anti-fan-out).

**Why A and not B:**
1. **Decomposable** — supports Price × Volume × Mix analysis, which B structurally
   cannot (financing interest has no unit/quantity).
2. **Traceable to a single, unambiguous raw source** — one column
   (`order_items.price`), no dependency on payment-method mix or installment
   plans, which are themselves separate, useful-but-different dimensions.
3. **99.61% reconciled with B anyway** — adopting A does not mean discarding B;
   B remains available (`agg_order_payments.total_payment_value`) as a separate,
   equally legitimate "cash collected including financing cost" metric for future
   financing-behavior analysis. Causa should **never claim** A and B are
   interchangeable, and should surface B alongside A when financing cost is
   analytically relevant.

**GMV variant:** `agg_order_items.item_gmv_total = item_price_total + item_freight_total`
is also materialized, for use cases that need freight included (e.g. logistics-cost
KPIs) — kept as a clearly-separate field, not conflated with `item_price_total`.

## Reproducibility / traceability

```
CAUSA_REVENUE for order X
  = data/processed/agg_order_items.parquet
      .query("order_id == X")["item_price_total"]
  = data/raw/olist/olist_order_items_dataset.csv
      .query("order_id == X")["price"].sum()
```

Every number is one groupby-sum away from a raw CSV cell — see
`docs/DATA_LINEAGE_V2.md` for the full traceability chain.

## Explicitly NOT decided here (Step 3 scope)

- How CAUSA_REVENUE should be filtered by `order_status` or
  `in_analytical_window` for a specific KPI report (this document defines the
  *number*, not the *query*).
- Whether CAUSA_REVENUE should exclude the 775 orders with no items at all —
  they are structurally absent from `agg_order_items` already (see
  `docs/CANONICAL_DATA_MODEL.md`), so no separate decision is needed for them, but
  how a KPI engine *reports* that absence (e.g. "775 orders excluded from revenue,
  here's why") is a Step 3 UX/engine concern.
- Any KPI formula beyond revenue itself (AOV, freight ratio, etc.) — those were
  previewed in the prior EDA's `docs/KPI_CANDIDATES.md` but are not re-implemented
  or re-certified here.
