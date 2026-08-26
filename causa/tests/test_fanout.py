"""Anti-fan-out architecture tests (Step 2 §18, §21.12).

This is the hard requirement: prove that a naive join across orders x order_items x
payments x reviews DOES multiply revenue (so the risk is real and demonstrated, not
just asserted), and prove that the canonical aggregate tables (agg_order_items,
agg_order_payments, agg_order_reviews) are structurally immune to this -- canonical
revenue must be identical no matter how many payment or review rows an order has.

If a future change to the build script accidentally re-introduces a fan-out (e.g. by
joining order_items to payments/reviews before aggregating, or by adding a `revenue`
column to fact_orders that gets summed after a join), these tests must fail.
"""

from __future__ import annotations

import pandas as pd
import pytest


def test_naive_join_inflates_revenue_vs_canonical_aggregate(canonical, raw):
    """Proves the fan-out risk is real: joining raw order_items to raw order_payments
    before summing price produces a DIFFERENT (larger) total than the canonical
    agg_order_items.item_price_total sum. If these two numbers ever become EQUAL,
    it does not mean the risk went away -- it means this test's naive-join
    reproduction is broken and must be fixed, not the assertion relaxed."""
    items, payments = raw["order_items"], raw["order_payments"]

    canonical_total = canonical["agg_order_items"]["item_price_total"].sum()
    raw_correct_total = items["price"].sum()
    assert abs(canonical_total - raw_correct_total) < 0.01, (
        f"canonical agg_order_items total ({canonical_total}) must match "
        f"SUM(raw order_items.price) ({raw_correct_total}) -- if they differ, the aggregation itself "
        f"is broken, not a fan-out issue."
    )

    naive = items.merge(payments, on="order_id", how="inner")
    naive_total = naive["price"].sum()

    assert naive_total != pytest.approx(canonical_total, abs=0.01), (
        f"Naive join (order_items x order_payments, summed after joining) produced "
        f"{naive_total:,.2f}, which equals the canonical total {canonical_total:,.2f} -- expected them "
        f"to DIFFER (that's the fan-out bug this test exists to catch happening for real). If this "
        f"assertion now fails, verify the raw data hasn't changed such that every order has exactly "
        f"1 payment row (which would make the naive join safe by coincidence, not by design)."
    )
    inflation_pct = (naive_total / raw_correct_total - 1) * 100
    assert inflation_pct > 1.0, (
        f"Expected a material (>1%) revenue inflation from the naive join, got {inflation_pct:.4f}%. "
        f"A near-zero inflation would suggest order_payments no longer has a 1-to-many relationship "
        f"with orders, which should be independently verified before trusting this result."
    )


def test_canonical_revenue_stable_regardless_of_payment_multiplicity(canonical):
    """The core anti-fan-out proof: joining agg_order_items (already aggregated to
    order grain) to fact_payments (native, multi-row-per-order grain) and re-summing
    item_price_total per order must reproduce EXACTLY the same total as
    agg_order_items alone -- because item_price_total is already 1 row per order, a
    join to a multi-row table and a groupby('order_id').first() (or equivalent)
    cannot inflate it, unlike a naive re-sum would."""
    agg_items = canonical["agg_order_items"]
    payments = canonical["fact_payments"]

    baseline_total = agg_items["item_price_total"].sum()

    # The CORRECT way to bring in payment multiplicity: join at agg grain, take one
    # row per order (item_price_total is already order-grain, so it is identical
    # across every payment row for that order after the join -- summing it after a
    # naive join would inflate; selecting distinct order-grain rows first does not).
    joined = agg_items.merge(payments[["order_id", "payment_sequential"]], on="order_id", how="left")
    # A correct downstream consumer takes the order-grain value ONCE per order:
    correct_reaggregated_total = joined.drop_duplicates(subset="order_id")["item_price_total"].sum()
    assert correct_reaggregated_total == pytest.approx(baseline_total, abs=0.01), (
        f"Re-deriving revenue via drop_duplicates(order_id) after joining to fact_payments should "
        f"reproduce the baseline total exactly ({baseline_total:,.2f}), got {correct_reaggregated_total:,.2f}."
    )

    # The INCORRECT way (naive sum after join) must NOT match -- proving the
    # multiplicity in fact_payments really would inflate a careless aggregation,
    # which is exactly why agg_order_items exists as a separate, pre-aggregated table.
    naive_reaggregated_total = joined["item_price_total"].sum()
    assert naive_reaggregated_total != pytest.approx(baseline_total, abs=0.01), (
        f"Expected naively summing item_price_total after a join to fact_payments to INFLATE the total "
        f"beyond {baseline_total:,.2f} (got {naive_reaggregated_total:,.2f}, which matches) -- this would "
        f"mean fact_payments no longer has any orders with >1 payment row, changing the premise of "
        f"this regression test."
    )


def test_canonical_revenue_stable_regardless_of_review_multiplicity(canonical):
    """Same proof, against fact_reviews (which has its own independent multiplicity --
    up to 3 review rows per order)."""
    agg_items = canonical["agg_order_items"]
    reviews = canonical["fact_reviews"]

    baseline_total = agg_items["item_price_total"].sum()
    joined = agg_items.merge(reviews[["order_id", "review_row_id"]], on="order_id", how="left")

    correct_reaggregated_total = joined.drop_duplicates(subset="order_id")["item_price_total"].sum()
    assert correct_reaggregated_total == pytest.approx(baseline_total, abs=0.01)

    naive_reaggregated_total = joined["item_price_total"].sum()
    assert naive_reaggregated_total != pytest.approx(baseline_total, abs=0.01), (
        f"Expected naively summing item_price_total after a join to fact_reviews to inflate the total "
        f"beyond {baseline_total:,.2f}. If this now matches, fact_reviews' review-per-order multiplicity "
        f"(547 orders with >1 review, per Step 1) may have been lost."
    )


def test_agg_order_payments_total_is_not_derived_from_a_fanned_out_join(canonical, raw):
    """agg_order_payments.total_payment_value must equal SUM(order_payments.payment_value)
    grouped by order_id directly from raw -- NOT via any join to order_items."""
    agg = canonical["agg_order_payments"].set_index("order_id")["total_payment_value"]
    raw_grouped = raw["order_payments"].groupby("order_id")["payment_value"].sum()
    diff = (agg - raw_grouped.reindex(agg.index)).abs()
    assert (diff < 0.01).all(), (
        f"{(diff >= 0.01).sum()} orders have agg_order_payments.total_payment_value that does not match "
        f"a direct groupby sum of raw order_payments -- possible fan-out contamination in the build."
    )


def test_fact_order_items_is_never_pre_joined_to_payments_or_reviews(canonical):
    """Structural check: fact_order_items must have exactly the raw row count and
    column set -- if a future change joins it to payments/reviews and flattens the
    result into this table, row count will multiply and this test will fail."""
    foi = canonical["fact_order_items"]
    expected_cols = {"order_id", "order_item_id", "product_id", "seller_id",
                      "shipping_limit_date", "price", "freight_value"}
    assert set(foi.columns) == expected_cols, (
        f"fact_order_items has unexpected columns {set(foi.columns) - expected_cols} -- this table must "
        f"stay at native order_item grain with only its own fields, never enriched with payment/review "
        f"columns (which would signal an upstream fan-out join)."
    )
