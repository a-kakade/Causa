# Review Governance

Computed by `scripts/step2_03_review_dedup_evaluation.py`. Full output:
`reports/step2_review_dedup_comparison.json`. Basis: 99,224 raw review rows,
547 orders with more than one review (543 with exactly 2, 4 with exactly 3).

**Deduplication and aggregation are different operations and are not confused
here** — this document evaluates 4 candidate *single-row-per-order* strategies
(each is a form of deduplication) separately from the *true aggregate* fields
(avg/min/max) that are computed regardless of which dedup strategy is chosen.

## The 4 candidate strategies, quantitatively compared

For all 547 multi-review orders, "bias" below means: the chosen strategy's score
minus the simple average of *all* of that order's review scores. A strategy with
`mean_signed_bias = 0` neither over- nor understates satisfaction relative to using
all the evidence; a positive bias means the strategy is more optimistic than the
full evidence, negative means more pessimistic.

| Strategy | Output rows | Distinct orders | Mean score | Text coverage | Mean signed bias | % rows biased up | % rows biased down |
|---|---|---|---|---|---|---|---|
| **latest_review_answer_timestamp** | 98,673 | 98,673 (1:1) | 4.0864 | 41.30% | **−0.0734** | 16.27% | 20.66% |
| earliest_review_creation_date | 98,673 | 98,673 (1:1) | 4.0873 | 41.31% | +0.0948 | 21.57% | 15.36% |
| **highest_review_score** | 98,673 | 98,673 (1:1) | 4.0889 | 41.27% | **+0.3763** | 36.93% | 0.00% |
| retain_all_no_dedup | 99,224 | 98,673 (1:many) | 4.0864 | 41.27% | 0.00 (by definition) | 18.49% | 18.49% |

## Interpretation

- **`highest_review_score` is disqualified for KPI use.** Its bias (+0.3763) is 4–5×
  larger in magnitude than the other two dedup strategies, and — tellingly —
  **0.00%** of its rows are biased downward: by construction it can never
  understate, only match or overstate, a multi-review order's satisfaction. This
  is a form of cherry-picking, not a neutral representative-value choice, and
  would make any review-score KPI built on it systematically too optimistic for
  the 0.55% of orders with multiple reviews.
- **`earliest_review_creation_date`** has a smaller but still real positive bias
  (+0.0948) — plausibly because a customer's *first* review, before any
  back-and-forth or a delayed problem discovery, tends to run slightly more
  positive than their eventual final word.
- **`latest_review_answer_timestamp`** has the smallest-magnitude bias of the three
  dedup strategies (−0.0734) and represents *the customer's most recent stated
  opinion*, which is also the most defensible business semantics — if a customer
  revises their review, the revision should count, not the first impression.
- **`retain_all_no_dedup`** has zero bias by definition (it doesn't collapse
  anything), at the cost of not being 1:1 with orders — unsuitable on its own for
  an order-level KPI, but exactly right for anything that needs every legitimate
  review record.

## Decision (use-case-specific, not one global rule)

| Use case | Strategy | Materialized as |
|---|---|---|
| **Review-level text retrieval / future RAG** | `retain_all_no_dedup` | `data/processed/fact_reviews.parquet` — every raw row preserved, including all 814 duplicate `review_id`s and all 547 multi-review orders. A synthetic `review_row_id` surrogate key is added (review_id is not unique) so the table is still safely joinable/indexable. |
| **Order-level KPI, single representative score** | `latest_review_answer_timestamp` | `data/processed/agg_order_reviews.parquet` → `latest_review_score` (+ `latest_review_id` pointing back to the exact `fact_reviews` row it came from, for traceability) |
| **Order-level KPI, general-purpose / distributional** | true aggregation (not a dedup strategy at all) | `agg_order_reviews` → `avg_review_score`, `min_review_score`, `max_review_score`, `review_count` — computed over *all* of an order's reviews, independent of which single-row strategy is chosen above |

**Both the single-representative-value column and the true-aggregate columns are
materialized side by side in `agg_order_reviews`.** A Step 3 KPI engine should
default to `avg_review_score` for anything computing a distribution or mean across
many orders (it has zero bias by construction) and use `latest_review_score` only
when a single, order-specific "current sentiment" value is semantically required
(e.g., displaying "this order's review" in a UI).

## What is explicitly NOT decided here

- Whether `orders_without_review` (768 orders, absent from `agg_order_reviews` by
  construction — never zero- or null-score-filled) should be excluded or flagged
  in a review-score KPI. That is a Step 3 decision; this document only guarantees
  the absence is honestly represented (`fact_orders.has_review == False`), not how
  a future KPI engine should react to it.
- Sentiment analysis, topic modeling, or any text-derived score — out of scope for
  Step 2 entirely (that is RAG/LLM territory, explicitly excluded from this step).
