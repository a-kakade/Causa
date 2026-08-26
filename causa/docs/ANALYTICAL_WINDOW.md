# Analytical Window Decision

Computed fresh by `scripts/step2_01_window_analysis.py` from the raw data (not
copied from the prior EDA session's conclusion). Full output:
`reports/step2_window_analysis.json`.

## Method (data-driven, not eyeballed)

1. Compute monthly order volume, revenue (`SUM(order_items.price)`, orders
   pre-aggregated to order grain before joining to purchase month — no fan-out),
   and missingness/coverage of items, delivery timestamps, and reviews, for every
   calendar month in the raw data.
2. Take the **median monthly order count across all months with >0 orders**
   (= 4,285) as the reference scale.
3. Define a month **volume-unreliable** if its order count is below **10% of that
   median** (threshold = 428.5 orders/month). This is an explicit, reproducible
   rule, not a visual judgment call.
4. **Cross-validate** the volume-based classification against the coverage metrics
   (items/delivery/review completeness) for the same months, so the decision isn't
   resting on volume alone.

## Result

| | |
|---|---|
| **Chosen start** | **2017-01** |
| **Chosen end** | **2018-08** |
| Months in window | 20 |
| Orders in window | 99,092 of 99,441 (99.65%) |
| Orders excluded | 349 (0.35%) |

**Excluded months:** 2016-09 (4 orders), 2016-10 (324 orders), 2016-12 (1 order),
2018-09 (16 orders), 2018-10 (4 orders). (2016-11 has 0 orders and needs no
exclusion rule — there is nothing there to include or exclude.)

## Why — the evidence is not uniform across excluded months

The cross-validation step surfaced a genuinely mixed picture, reported honestly
rather than collapsed into one story:

- **2016-10** (324 orders) has broadly normal-looking coverage on its own terms
  (83.33% delivery coverage, 95.06% items coverage, 98.46% review coverage) — its
  exclusion is a **statistical-power argument** (324 orders is too thin a base for
  monthly trend/anomaly comparisons against months with 4,000-7,500 orders), not a
  data-corruption argument.
- **2016-09** (4 orders) and **2016-12** (1 order) are trivially thin — a single
  order literally cannot support any monthly statistic.
- **2018-09** (16 orders) and **2018-10** (4 orders) are **structurally incomplete,
  not just low-volume** — this is a stronger, independent finding: items_coverage
  drops to **6.25%** and **0%** respectively (i.e. 15 of 16, and all 4, of these
  orders have no order_items rows at all), and delivery_coverage drops to **0%** in
  both months. This is consistent with orders placed too close to the
  archive.zip extraction date to have progressed through the fulfillment pipeline —
  a **hypothesis** (no extraction-date metadata exists to confirm it directly), but
  one strongly supported by the structural-completeness collapse, not merely the
  low order count.

## Consequences

- Any KPI, trend, month-over-month, or anomaly calculation in a future step
  **must** filter to `fact_orders.in_analytical_window == True` (or explicitly
  justify not doing so) to avoid reporting spurious multi-thousand-percent
  "movements" driven by near-zero-order-count base months, or silently including
  349 orders whose items/delivery/review data is disproportionately incomplete.
- **AOV, revenue-per-month, and delivery-time-per-month figures for the excluded
  months would be statistically unstable** (e.g., 2016-12's single order defines
  100% of that month's "AOV") and should never be plotted or compared against
  in-window months without this caveat attached.

## Excluded data remains available — nothing is deleted

The window is implemented as a **boolean flag**
(`fact_orders.in_analytical_window`), never as a row deletion. `fact_orders` still
contains all 99,441 orders, `fact_order_items`/`fact_payments`/`fact_reviews`
still contain every raw row regardless of which order they belong to, and the raw
CSVs themselves are untouched (per §1's freeze requirement). Exploratory or
reference analysis of the excluded 349 orders — e.g., "what did the platform's very
first orders look like" or "what happened to the last orders before the data
snapshot was taken" — remains fully possible by filtering
`in_analytical_window == False` instead of by re-deriving anything from raw.

## What this document does not decide

Per this task's brief, this document establishes the window and its evidence. It
does **not** decide how a future KPI engine should handle the boundary months in
edge cases (e.g., a 2017-01 vs 2016-12 month-over-month comparison, where one side
of the comparison is out-of-window) — that is a Step 3 design question that should
reference this document, not be pre-answered here.
