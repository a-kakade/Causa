# Olist Financial Reconciliation

Status: analysis complete, based on `notebooks/04_olist_financial_reconciliation.ipynb`
run against the dataset in `data/raw/olist/` (profiled 2026-08-26). This document does
**not** define a KPI YAML/contract, does not touch agents, LLM functionality,
frontend, or database models — it is a written recommendation only, to be formalized
in a later milestone.

All raw CSVs under `data/raw/olist/` were read-only throughout this analysis, verified
by file-hash comparison before and after the notebook ran (see notebook Section 9).

---

## 1. Executive conclusion

**Causa's primary financial KPI should be Gross Merchandise Value (GMV), defined as
`SUM(order_items.price + order_items.freight_value)` on `delivered` orders.**

This is a **GMV-like proxy measuring order value, not an accounting revenue figure** —
the Olist dataset does not contain the fields (net-of-return revenue recognition,
Olist's own take-rate/commission, refund reversals, tax treatment) needed to support a
true revenue metric, so nothing in this project should be labeled "Revenue."
`item_value + freight_value` is preferred over `item_value` alone because freight is a
real, unavoidable component of what the customer paid for the order and of what moved
through the marketplace (~14% of the combined total; see Section 3), and it is
preferred over `payment_value` because payment volume reflects installment/financing
mechanics of the payment gateway (evidence in Section 4) rather than the value of the
merchandise transacted — see Section 5 for the full comparison. `delivered` is the
only status with both complete data and a resolved logistics outcome, and is used to
avoid the near-total absence of item data in `unavailable`/`created` orders.

---

## 2. Data model and grain

| Table | Grain | Key |
|---|---|---|
| `orders` | one row per order | `order_id` |
| `order_items` | one row per **order line item** | `(order_id, order_item_id)` |
| `order_payments` | one row per **payment method/installment record** | `(order_id, payment_sequential)` |

`order_items` and `order_payments` are both one-to-many children of `orders`, but
**not** of each other. Joining them to each other directly, before aggregating either
to order grain, produces a many-to-many cross product within each order.

**Demonstrated in the notebook (Section 2)**: joining `order_items` (112,650 rows)
directly to `order_payments` (103,886 rows) on `order_id` produces 117,601 joined
rows — more than either input table — and summing `price` on that joined table
inflates the true total (13,591,643.70 BRL) to 14,209,115.34 BRL, a **4.54% inflation**
purely from the unsafe join pattern. This is not a fixed percentage; it depends on how
many orders combine multiple items with multiple payment records, which is exactly why
the pattern must never be used.

**Safe pattern used throughout this analysis**: aggregate `order_items` to order grain
(`SUM(price)`, `SUM(freight_value)`, one row per `order_id`) and `order_payments` to
order grain (`SUM(payment_value)`, one row per `order_id`) **independently**, then join
each order-grain result 1:1 onto `orders`. This was verified with explicit assertions
in the notebook: both aggregates have exactly one row per `order_id`, and the final
joined table (`recon`) has exactly `len(orders)` = 99,441 rows, matching `orders`
exactly.

---

## 3. Reconciliation analysis

Restricted to the 98,665 orders (99.22% of all orders) that have **both** an item
record and a payment record — reconciliation is only meaningful where both exist.

| Metric | Value |
|---|---|
| Orders with both item + payment data | 98,665 |
| Exact equality rate (`payment_value == item_plus_freight`) | 99.43% |
| Near-equality rate, tolerance ≤ 0.01 BRL | 99.61% |
| Near-equality rate, tolerance ≤ 0.05 BRL | 99.74% |
| Near-equality rate, tolerance ≤ 1.00 BRL | 99.75% |
| Mean absolute difference | 0.033 BRL |
| Median absolute difference | 0.00 BRL |
| Max absolute difference | 182.81 BRL |
| Orders with negative difference (`payment_value < item_plus_freight`, beyond 1-cent tolerance) | 90 (0.09%) |
| Orders with a discrepancy > 50 BRL | 8 (0.008%) |
| Orders with ~zero `item_plus_freight` or ~zero `payment_value` (among those with both records) | 0 |

**Working tolerance used throughout this analysis: 0.01 BRL (1 cent)** — chosen to
absorb floating-point/rounding noise without absorbing any genuine mismatch (the
median absolute difference among all 98,665 orders is exactly 0.00, so any tolerance
above true floating-point noise already captures the overwhelming majority of orders;
1 cent is the smallest meaningful currency unit and does not mask real discrepancies).

**Missing-record patterns** (never silently dropped; explicit in Section 4 below):

| Pattern | Count | Dominant `order_status` |
|---|---|---|
| Has items, no payment record | 1 | `delivered` (1 of 1) |
| Has payment, no item record | 775 | `unavailable` (603), `canceled` (164), `created` (5), `invoiced` (2), `shipped` (1) |
| Has neither | 0 | — |

**Conclusion**: the two measures agree almost everywhere (>99.4% exact match), so
`payment_value` and `item_plus_freight` are **not** unrelated numbers — but they are
also **not defined to be identical**, and the data does not support assuming they
should be. The disagreement is small in aggregate but has a real, non-random tail (see
Section 4).

---

## 4. Status analysis

All 8 `order_status` values present in the dataset are analyzed; none are excluded.

| `order_status` | Order count | Total item_value (BRL) | Total freight_value (BRL) | Total payment_value (BRL) | Avg item_value (BRL) | Avg payment_value (BRL) | Orders w/ items | Orders w/ payment |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| delivered | 96,478 | 13,221,498.11 | 2,198,275.64 | 15,422,461.77 | 137.04 | 159.86 | 96,478 (100%) | 96,477 (99.999%) |
| shipped | 1,107 | 150,727.44 | 26,401.90 | 177,213.96 | 136.28 | 160.08 | 1,106 (99.9%) | 1,107 (100%) |
| canceled | 625 | 95,235.27 | 10,650.45 | 143,255.60 | 206.58 | 229.21 | 461 (73.8%) | 625 (100%) |
| unavailable | 609 | 2,007.69 | 132.80 | 126,479.51 | 334.62 | 207.68 | 6 (1.0%) | 609 (100%) |
| invoiced | 314 | 61,526.37 | 7,462.38 | 69,137.99 | 197.20 | 220.18 | 312 (99.4%) | 314 (100%) |
| processing | 301 | 60,439.22 | 8,954.89 | 69,394.11 | 200.79 | 230.55 | 301 (100%) | 301 (100%) |
| created | 5 | 0.00 | 0.00 | 688.10 | n/a | 137.62 | 0 (0%) | 5 (100%) |
| approved | 2 | 209.60 | 31.48 | 241.08 | 104.80 | 120.54 | 2 (100%) | 2 (100%) |

Reconciliation quality by status (orders with both item + payment records only):

| `order_status` | n | Exact/near-equal rate (≤0.01 BRL) | Mean abs diff | Median abs diff | Max abs diff |
|---|---:|---:|---:|---:|---:|
| delivered | 96,477 | 99.42% | 0.0335 | 0.00 | 182.81 |
| shipped | 1,106 | 99.64% | 0.0063 | 0.00 | 5.99 |
| canceled | 461 | 99.57% | 0.0694 | 0.00 | 25.12 |
| invoiced | 312 | 99.68% | ~0.00003 | 0.00 | 0.01 |
| processing | 301 | 100.00% | ~0 (float noise) | 0.00 | ~0 |
| approved | 2 | 100.00% | ~0 (float noise) | 0.00 | ~0 |
| unavailable | 6 | 100.00% | 0.00 | 0.00 | 0.00 |
| **created** | 0 | n/a — no order in `created` has item data | — | — | — |

**Key observations**:

- `delivered`, `shipped`, `invoiced`, and `processing` orders have near-complete item
  and payment data and reconcile almost perfectly.
- `unavailable` orders overwhelmingly (99.0%) have a payment record but **no** item
  record — nearly the inverse data-completeness profile of the other statuses.
- `canceled` orders are a mixed case: 73.8% have item records, 26.2% do not, but 100%
  have payment records.
- `created` orders (n=5, a tiny sample) never have item data — structurally consistent
  with "order created but not yet populated with item/logistics detail."
- `approved` has only 2 orders — too small a sample to draw any general conclusion.

This directly shapes the KPI recommendation in Section 6: any GMV-like measure that
requires `item_value` cannot be computed for the vast majority of `unavailable` orders,
and would systematically undercount `canceled` orders, by construction of the data
itself — not by choice of formula.

---

## 5. Candidate KPI definitions

### A. Item sales value — `SUM(order_items.price)`

Represents the sum of listed item prices across an order's line items, **excluding**
freight. It is the cleanest "what merchandise was priced at" figure, but on its own
excludes freight, which the customer did pay and which is a real cost that moved
through the marketplace.

### B. Merchandise value / GMV candidate — `item_value` vs. `item_value + freight_value`

On `delivered` orders (the cleanest, most complete status): `freight_value` totals
2,198,275.64 BRL against `item_value` totals 13,221,498.11 BRL — **freight is ~14.25%
of `item_plus_freight`**. This is not a rounding-level effect; excluding freight would
material undercount the true value of what moved through the platform.

**`item_value + freight_value` is the more defensible GMV-like measure** for this
project: freight is a real component of the transaction, is present on essentially
every order (0 delivered orders have zero/null `item_plus_freight`), and is directly
attributable to `order_items` at the correct grain (no join risk, since it comes from
the same table as `item_value`).

### C. Payment volume — `SUM(order_payments.payment_value)`

Represents the total amount actually charged/collected via the payment gateway, across
all payment legs of an order (which may include vouchers, installment financing, or
split payment methods). **Payment volume is not a merchandise/order value measure** —
Section 4 (notebook) found `payment_value` running measurably above
`item_plus_freight` on high-installment credit-card orders (all 8 discrepancies over
50 BRL involved 10+ installment credit-card payments), consistent with the payment
gateway including installment financing charges. This makes `payment_value` a better
fit for payment-operations analysis (e.g. gateway reconciliation, payment-method mix)
than for a merchandise-value KPI. Payment volume is also the only measure available for
the 775 orders (mostly `unavailable`/`canceled`) that have no item records at all — it
systematically overstates apparent "value" for those orders since it captures money
collected even where no merchandise record exists.

### D. Revenue-like KPI

**The dataset does not support a true accounting revenue metric, and this project will
not claim one.** True revenue recognition would require, at minimum: Olist's own
commission/take-rate on each transaction (not present — the dataset reflects
seller-side pricing and payment collection, not Olist's own P&L), an explicit
refund/return-reversal field (not present — canceled orders' payment amounts are not
flagged as refunded or not), and clarity on whether `payment_value` includes
pass-through financing costs that would need to be excluded from revenue (plausible
per Section 4, not confirmed). Given these gaps, no measure derived in this analysis
should be labeled "Revenue" — GMV-like proxy is the accurate, honest label for what the
data can support.

---

## 6. Final recommendation

| Field | Value |
|---|---|
| **KPI name** | `gmv_delivered` (Gross Merchandise Value, delivered orders) |
| **Business meaning** | Total value of merchandise (item price + freight) transacted through orders that were successfully delivered to the customer. A GMV-like proxy for marketplace order value — **not** an accounting revenue figure. |
| **Formula** | `SUM(order_items.price) + SUM(order_items.freight_value)`, aggregated to order grain first, then summed across all included orders |
| **Source tables** | `orders` (for `order_id`, `order_status`, `order_purchase_timestamp`), `order_items` (for `price`, `freight_value`) |
| **Grain** | Computed at order grain (`order_items` aggregated to one row per `order_id` before use), then rolled up to whatever reporting grain is needed (e.g. monthly) |
| **Included order statuses** | `delivered` only |
| **Treatment of cancellations** | Excluded. `canceled` orders are excluded from `gmv_delivered` because delivery did not occur and 26.2% of them lack item records entirely (Section 4), making the measure both conceptually wrong (merchandise was not delivered) and structurally incomplete (couldn't be computed consistently) for this status. |
| **Treatment of unavailable orders** | Excluded. 99.0% of `unavailable` orders have no item record at all (Section 4) — `item_value`/`item_plus_freight` cannot be computed for the vast majority of them, and no fulfillment occurred. |
| **Treatment of missing values** | An order is included in `gmv_delivered` only if it has `order_status = "delivered"` **and** at least one `order_items` row. On the current dataset this excludes exactly 1 `delivered` order that has item data but is otherwise complete (that 1 order still has items, so it is included via `item_value`; the note here is that `payment_value` is separately missing for it — payment-based measures, not GMV, would need to handle that gap). No `delivered` order lacks item data on the current dataset (0 of 96,478), so in practice this exclusion clause currently affects zero orders — it is stated for correctness against future data refreshes. |
| **Treatment of freight** | **Included.** Freight is ~14.25% of `item_plus_freight` on delivered orders — material, not negligible — and is directly attributable at `order_items` grain with no join risk. |
| **Currency** | Brazilian Real (BRL) — the dataset does not specify currency explicitly, but Olist is a Brazilian marketplace and all sampled values (e.g. mean order value ~137–160 BRL) are consistent with BRL-denominated prices. No currency-conversion logic is in scope. |
| **Known limitations** | (1) Not a true revenue metric — see Section 5D. (2) Does not account for `payment_value` discrepancies (Section 3/4) since it deliberately does not use `payment_value` as its source. (3) Excludes `canceled`/`unavailable`/other non-delivered orders entirely, so it does not capture "orders placed" or "attempted GMV" — a separate metric would be needed for that. (4) `order_purchase_timestamp` (used for time-based rollups) reflects when the order was placed, not when it was delivered or when payment cleared — monthly `gmv_delivered` by purchase month can include orders delivered in a later month. |

---

## 7. Supporting metrics

A small set, each explaining a distinct, defensible movement in `gmv_delivered`:

| Metric | Formula | Purpose |
|---|---|---|
| **Delivered order count** | `COUNT(DISTINCT order_id)` where `order_status = "delivered"` | Distinguishes GMV growth driven by more orders vs. higher order value. |
| **Average Order Value (AOV)** | `gmv_delivered / delivered_order_count` | Standard complement to GMV + order count; validated as stable (~146–176 BRL/month) in Section 9 of the notebook. |
| **Item sales value** | `SUM(order_items.price)`, delivered orders | Isolates the merchandise-price component of GMV, separate from freight — useful for pricing/catalog analysis. |
| **Freight value** | `SUM(order_items.freight_value)`, delivered orders | Isolates the logistics-cost component of GMV — useful for shipping/logistics analysis, and to monitor freight's ~14% share of GMV over time. |
| **Payment volume** | `SUM(order_payments.payment_value)`, delivered orders | A distinct, payment-operations-oriented measure — tracked *alongside* GMV, never substituted for it, given the installment-related divergence found in Section 4. |

**Not recommended at this time**: a discount/voucher-specific measure. Voucher usage
was investigated as a candidate explanation for GMV/payment discrepancies (Section 4)
and found to be *not* associated with mismatches (voucher usage rate among mismatched
orders, 2.89%, was lower than the overall rate, 3.82%) — so no discount-adjustment
metric is currently defensible from the evidence. This should be revisited only if a
clearer voucher-value field or discount field becomes available.

---

## 8. Limitations — what the Olist dataset cannot establish

- **No true revenue metric.** No commission/take-rate, no refund/return field, no
  confirmed accounting treatment of installment interest. See Section 5D.
- **No confirmed explanation for installment-related payment discrepancies.** The
  installment-interest hypothesis (Section 4 of the notebook / this document) is
  plausible and consistent with the correlational evidence but is not confirmed by any
  explicit field in the dataset.
- **No explanation for the 90 orders with negative differences** (`payment_value <
  item_plus_freight`). No payment-type, voucher, or installment pattern distinguishes
  them from the rest of the data.
- **No explanation for why some `canceled`/`unavailable` orders retain a payment
  record with no item record.** The "payment collected before cancellation" hypothesis
  is plausible but not confirmed by any lifecycle field that distinguishes the timing
  of payment vs. cancellation.
- **No currency-conversion or multi-currency support** — the dataset is assumed to be
  entirely BRL-denominated; this is inferred from context (Olist is Brazilian), not
  confirmed by an explicit currency field.
- **`order_purchase_timestamp` vs. delivery timing**: GMV rolled up by purchase month
  will include some orders that were delivered in a later month; no
  delivery-month-based rollup was evaluated in this analysis.

---

## 9. Lineage

```
Raw Olist tables
    orders.csv               (order_id, order_status, order_purchase_timestamp)
    order_items.csv          (order_id, order_item_id, price, freight_value)
    order_payments.csv       (order_id, payment_sequential, payment_value)
        ↓
Order-level aggregation (independently, per table, BEFORE any cross-table join)
    item_agg   = order_items    GROUP BY order_id -> SUM(price), SUM(freight_value)
    pay_agg    = order_payments GROUP BY order_id -> SUM(payment_value)
        ↓
Order-grain join (1:1, safe)
    recon = orders LEFT JOIN item_agg ON order_id LEFT JOIN pay_agg ON order_id
        ↓
Financial calculation
    item_plus_freight = item_value + freight_value       (per order)
    gmv_delivered      = SUM(item_plus_freight) WHERE order_status = 'delivered'
        ↓
Causa KPI
    gmv_delivered  (primary, this document's Section 6)
    + supporting metrics (Section 7): delivered_order_count, AOV, item_sales_value,
      freight_value, payment_volume
```

No KPI YAML/contract is created at this stage — this lineage and the Section 6
definition are the input to that future artifact, not the artifact itself.
