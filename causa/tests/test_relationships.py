"""Foreign-key, category-resolution, missing-data-flag, and temporal-window tests
for the canonical layer (Step 2 §21.2, .8, .10, .11)."""

from __future__ import annotations

import pandas as pd


# --- Foreign keys ------------------------------------------------------------------

def test_fact_orders_customer_id_matches_dim_customer(canonical):
    fo, dc = canonical["fact_orders"], canonical["dim_customer"]
    orphans = ~fo["customer_id"].isin(dc["customer_id"])
    assert orphans.sum() == 0, f"{orphans.sum()} fact_orders rows have a customer_id not in dim_customer"


def test_fact_order_items_product_id_matches_dim_product(canonical):
    foi, dp = canonical["fact_order_items"], canonical["dim_product"]
    orphans = ~foi["product_id"].isin(dp["product_id"])
    assert orphans.sum() == 0, f"{orphans.sum()} fact_order_items rows have a product_id not in dim_product"


def test_fact_order_items_seller_id_matches_dim_seller(canonical):
    foi, ds = canonical["fact_order_items"], canonical["dim_seller"]
    orphans = ~foi["seller_id"].isin(ds["seller_id"])
    assert orphans.sum() == 0, f"{orphans.sum()} fact_order_items rows have a seller_id not in dim_seller"


def test_fact_order_items_order_id_matches_fact_orders(canonical):
    foi, fo = canonical["fact_order_items"], canonical["fact_orders"]
    orphans = ~foi["order_id"].isin(fo["order_id"])
    assert orphans.sum() == 0, f"{orphans.sum()} fact_order_items rows reference an order_id not in fact_orders"


def test_fact_payments_order_id_matches_fact_orders(canonical):
    fp, fo = canonical["fact_payments"], canonical["fact_orders"]
    orphans = ~fp["order_id"].isin(fo["order_id"])
    assert orphans.sum() == 0, f"{orphans.sum()} fact_payments rows reference an order_id not in fact_orders"


def test_fact_reviews_order_id_matches_fact_orders(canonical):
    fr, fo = canonical["fact_reviews"], canonical["fact_orders"]
    orphans = ~fr["order_id"].isin(fo["order_id"])
    assert orphans.sum() == 0, f"{orphans.sum()} fact_reviews rows reference an order_id not in fact_orders"


def test_agg_tables_orders_are_subset_of_fact_orders(canonical):
    fo = canonical["fact_orders"]
    for name in ("agg_order_items", "agg_order_payments", "agg_order_reviews"):
        agg = canonical[name]
        orphans = ~agg["order_id"].isin(fo["order_id"])
        assert orphans.sum() == 0, f"{name}: {orphans.sum()} order_ids not present in fact_orders"


# --- Product category resolution (Step 2 §12, §21.8) -------------------------------

def test_dim_product_category_resolution_status_values(canonical):
    dp = canonical["dim_product"]
    valid_statuses = {"TRANSLATED", "UNTRANSLATED", "NULL_CATEGORY"}
    seen = set(dp["category_resolution_status"].unique())
    assert seen <= valid_statuses, f"Unexpected category_resolution_status values: {seen - valid_statuses}"


def test_dim_product_null_category_count(canonical):
    dp = canonical["dim_product"]
    n_null = (dp["category_resolution_status"] == "NULL_CATEGORY").sum()
    assert n_null == 610, (
        f"Expected 610 products with NULL_CATEGORY (per Step 1 audit), found {n_null}. "
        f"If raw data hasn't changed, dim_product's category join logic has a bug."
    )
    assert dp.loc[dp["category_resolution_status"] == "NULL_CATEGORY", "category_name_pt"].isna().all()


def test_dim_product_untranslated_category_count(canonical):
    dp = canonical["dim_product"]
    n_untranslated = (dp["category_resolution_status"] == "UNTRANSLATED").sum()
    assert n_untranslated == 13, (
        f"Expected 13 products with UNTRANSLATED category (2 category names with no translation row, "
        f"per Step 1 audit), found {n_untranslated}."
    )
    untranslated = dp[dp["category_resolution_status"] == "UNTRANSLATED"]
    assert untranslated["category_name_en"].isna().all(), (
        "UNTRANSLATED rows must have a NULL category_name_en (not silently dropped from dim_product, "
        "not silently filled)"
    )
    assert untranslated["category_name_pt"].notna().all(), (
        "UNTRANSLATED rows must retain their Portuguese category name"
    )


def test_dim_product_no_rows_dropped_by_category_join(canonical, raw):
    assert len(canonical["dim_product"]) == len(raw["products"]), (
        "dim_product must have exactly 1 row per raw product -- the category_translation join must be "
        "LEFT, never INNER (an inner join would silently drop the 623 unresolved-category products)."
    )


# --- Missing-data flags (Step 2 §10, §20, §21.10) -----------------------------------

def test_has_items_flag_matches_agg_order_items_presence(canonical):
    fo, agg = canonical["fact_orders"], canonical["agg_order_items"]
    expected = fo["order_id"].isin(agg["order_id"])
    mismatches = (fo["has_items"] != expected).sum()
    assert mismatches == 0, f"{mismatches} orders have has_items inconsistent with agg_order_items presence"


def test_has_payment_flag_matches_agg_order_payments_presence(canonical):
    fo, agg = canonical["fact_orders"], canonical["agg_order_payments"]
    expected = fo["order_id"].isin(agg["order_id"])
    mismatches = (fo["has_payment"] != expected).sum()
    assert mismatches == 0, f"{mismatches} orders have has_payment inconsistent with agg_order_payments presence"


def test_has_review_flag_matches_agg_order_reviews_presence(canonical):
    fo, agg = canonical["fact_orders"], canonical["agg_order_reviews"]
    expected = fo["order_id"].isin(agg["order_id"])
    mismatches = (fo["has_review"] != expected).sum()
    assert mismatches == 0, f"{mismatches} orders have has_review inconsistent with agg_order_reviews presence"


def test_structurally_incomplete_order_counts_match_step1_audit(canonical):
    fo = canonical["fact_orders"]
    n_no_items = (~fo["has_items"]).sum()
    n_no_payment = (~fo["has_payment"]).sum()
    n_no_review = (~fo["has_review"]).sum()
    assert n_no_items == 775, f"Expected 775 orders without items (Step 1 audit), found {n_no_items}"
    assert n_no_payment == 1, f"Expected 1 order without payment (Step 1 audit), found {n_no_payment}"
    assert n_no_review == 768, f"Expected 768 orders without a review (Step 1 audit), found {n_no_review}"


def test_missing_items_not_zero_filled(canonical):
    """Orders without items must be ABSENT from agg_order_items, not present with a
    zero value -- zero-filling would misrepresent 'no transaction' as 'confirmed
    zero revenue', which this task explicitly prohibits (§10)."""
    fo, agg = canonical["fact_orders"], canonical["agg_order_items"]
    no_items_orders = set(fo.loc[~fo["has_items"], "order_id"])
    leaked = no_items_orders & set(agg["order_id"])
    assert len(leaked) == 0, (
        f"{len(leaked)} orders flagged has_items=False are nonetheless present in agg_order_items -- "
        f"this indicates zero-filling occurred instead of leaving the order absent."
    )


# --- Temporal window (Step 2 §2, §21.11) --------------------------------------------

def test_in_analytical_window_flag_boundaries(canonical):
    fo = canonical["fact_orders"]
    in_window = fo[fo["in_analytical_window"]]
    out_window = fo[~fo["in_analytical_window"]]
    assert in_window["purchase_timestamp"].dt.to_period("M").astype(str).min() == "2017-01"
    assert in_window["purchase_timestamp"].dt.to_period("M").astype(str).max() == "2018-08"
    out_months = set(out_window["purchase_timestamp"].dt.to_period("M").astype(str).unique())
    assert out_months == {"2016-09", "2016-10", "2016-12", "2018-09", "2018-10"}, (
        f"Excluded months {out_months} do not match the documented ANALYTICAL_WINDOW.md exclusion set"
    )


def test_analytical_window_does_not_drop_rows_from_fact_orders(canonical, raw):
    """The window is a FLAG, not a filter -- excluded-period orders must remain in
    fact_orders (per this task's explicit requirement that excluded data stay
    available for exploratory/reference use)."""
    assert len(canonical["fact_orders"]) == len(raw["orders"]), (
        "fact_orders row count must equal raw orders row count -- the analytical window must never be "
        "implemented by deleting rows."
    )
