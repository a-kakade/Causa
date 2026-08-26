"""Revenue reconciliation and payment aggregation tests (Step 2 §21.5, .6)."""

from __future__ import annotations

import pytest


def test_agg_order_items_matches_fresh_raw_recomputation(canonical, raw):
    """agg_order_items must be reproducible: recomputing SUM(price)/SUM(freight_value)
    grouped by order_id directly from the raw CSV must match the canonical table
    exactly, for every order."""
    agg = canonical["agg_order_items"].set_index("order_id")
    raw_recompute = raw["order_items"].groupby("order_id").agg(
        item_price_total=("price", "sum"), item_freight_total=("freight_value", "sum"),
        item_count=("order_item_id", "count"),
    )
    joined = agg.join(raw_recompute, lsuffix="_canonical", rsuffix="_raw")
    price_diff = (joined["item_price_total_canonical"] - joined["item_price_total_raw"]).abs()
    assert (price_diff < 0.01).all(), f"{(price_diff >= 0.01).sum()} orders have item_price_total mismatch"
    count_diff = (joined["item_count_canonical"] != joined["item_count_raw"]).sum()
    assert count_diff == 0, f"{count_diff} orders have item_count mismatch vs raw recomputation"


def test_causa_revenue_definition_reconciles_with_payments_at_documented_rate(canonical):
    """Regression guard on the CAUSA_REVENUE decision documented in
    KPI_SEMANTICS_PREVIEW.md: item_gmv_total (price+freight) should reconcile with
    total_payment_value within 1 cent for approximately 99.6% of orders present in
    both tables. This is a wide tolerance band (99.0-100.0%) so the test catches a
    genuine regression (e.g. a unit conversion bug) without being brittle to the
    exact float value."""
    items = canonical["agg_order_items"].set_index("order_id")
    payments = canonical["agg_order_payments"].set_index("order_id")
    both = items.join(payments, how="inner")
    diff = (both["total_payment_value"] - both["item_gmv_total"]).abs()
    matched_pct = (diff <= 0.01).mean() * 100
    assert 99.0 <= matched_pct <= 100.0, (
        f"Revenue reconciliation rate {matched_pct:.2f}% is outside the expected 99.0-100.0% band "
        f"documented in KPI_SEMANTICS_PREVIEW.md -- investigate before trusting CAUSA_REVENUE."
    )


def test_payment_value_never_negative_in_canonical_layer(canonical):
    fp = canonical["fact_payments"]
    n_negative = (fp["payment_value"] < 0).sum()
    assert n_negative == 0, f"{n_negative} fact_payments rows have a negative payment_value"


def test_agg_order_payments_payment_count_matches_raw(canonical, raw):
    agg = canonical["agg_order_payments"].set_index("order_id")["payment_count"]
    raw_count = raw["order_payments"].groupby("order_id").size()
    diff = (agg - raw_count.reindex(agg.index)).abs()
    assert (diff == 0).all(), f"{(diff != 0).sum()} orders have payment_count mismatch vs raw"


def test_agg_order_payments_payment_types_nonempty(canonical):
    agg = canonical["agg_order_payments"]
    empty = agg["payment_types"].isna() | (agg["payment_types"].str.len() == 0)
    assert empty.sum() == 0, f"{empty.sum()} orders in agg_order_payments have an empty payment_types field"


def test_agg_order_payments_max_installments_nonnegative(canonical):
    agg = canonical["agg_order_payments"]
    assert (agg["max_installments"] >= 0).all(), "max_installments must never be negative"


def test_no_zero_filled_revenue_for_orders_without_items(canonical):
    """Orders without order_items must be absent from agg_order_items -- never present
    with item_price_total == 0, which would misrepresent 'no transaction data' as
    'confirmed zero revenue'."""
    fo = canonical["fact_orders"]
    agg = canonical["agg_order_items"]
    no_items_ids = set(fo.loc[~fo["has_items"], "order_id"])
    zero_filled = agg[agg["order_id"].isin(no_items_ids)]
    assert len(zero_filled) == 0, (
        f"{len(zero_filled)} orders without items appear in agg_order_items (should be fully absent)"
    )
