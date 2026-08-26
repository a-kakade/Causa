"""Primary-key and customer-identity tests for the canonical layer (Step 2 §21.1, .4)."""

from __future__ import annotations


def _assert_unique_key(df, cols, table_name):
    dup = df.duplicated(subset=cols).sum()
    assert dup == 0, (
        f"{table_name}: primary key {cols} has {dup} duplicate rows -- this must be 0. "
        f"Sample duplicated keys: {df[df.duplicated(subset=cols, keep=False)][cols].head(5).to_dict('records')}"
    )
    nulls = df[cols].isna().any(axis=1).sum()
    assert nulls == 0, f"{table_name}: primary key {cols} has {nulls} rows with a null key component"


def test_dim_customer_pk(canonical):
    _assert_unique_key(canonical["dim_customer"], ["customer_id"], "dim_customer")


def test_dim_product_pk(canonical):
    _assert_unique_key(canonical["dim_product"], ["product_id"], "dim_product")


def test_dim_seller_pk(canonical):
    _assert_unique_key(canonical["dim_seller"], ["seller_id"], "dim_seller")


def test_fact_orders_pk(canonical):
    _assert_unique_key(canonical["fact_orders"], ["order_id"], "fact_orders")


def test_fact_order_items_pk(canonical):
    _assert_unique_key(canonical["fact_order_items"], ["order_id", "order_item_id"], "fact_order_items")


def test_fact_payments_pk(canonical):
    _assert_unique_key(canonical["fact_payments"], ["order_id", "payment_sequential"], "fact_payments")


def test_fact_reviews_surrogate_pk(canonical):
    """review_id is NOT a valid PK (814 duplicates in the raw data, by design -- see
    Step 1 audit). fact_reviews' real technical PK is the surrogate review_row_id."""
    _assert_unique_key(canonical["fact_reviews"], ["review_row_id"], "fact_reviews")


def test_fact_reviews_review_id_is_deliberately_not_unique(canonical):
    """Regression guard: if a future build accidentally deduplicates fact_reviews down
    to 1-row-per-review_id, this test must fail loudly -- that would silently destroy
    the genuine multi-review-per-order information Step 2 §7/§8 requires preserving."""
    fr = canonical["fact_reviews"]
    n_dup_review_id = fr.duplicated(subset=["review_id"]).sum()
    assert n_dup_review_id == 814, (
        f"fact_reviews should preserve exactly 814 duplicate review_id rows (per the Step 1 audit of "
        f"the raw data), found {n_dup_review_id}. If this is 0, fact_reviews has been incorrectly "
        f"deduplicated -- review-level grain must be preserved, per Step 2 §7."
    )


def test_agg_order_items_pk(canonical):
    _assert_unique_key(canonical["agg_order_items"], ["order_id"], "agg_order_items")


def test_agg_order_payments_pk(canonical):
    _assert_unique_key(canonical["agg_order_payments"], ["order_id"], "agg_order_payments")


def test_agg_order_reviews_pk(canonical):
    _assert_unique_key(canonical["agg_order_reviews"], ["order_id"], "agg_order_reviews")


# --- Customer identity (Step 2 §13, §21.4) ---------------------------------------

def test_customer_id_and_customer_unique_id_both_preserved(canonical):
    """dim_customer must NOT collapse customer_id (order-scoped) into
    customer_unique_id (person-level) -- both columns must exist and both must carry
    their full raw cardinality."""
    dc = canonical["dim_customer"]
    assert "customer_id" in dc.columns and "customer_unique_id" in dc.columns
    n_customer_id = dc["customer_id"].nunique()
    n_unique_id = dc["customer_unique_id"].nunique()
    assert n_customer_id == len(dc), "customer_id must be unique per row in dim_customer"
    assert n_unique_id < n_customer_id, (
        f"customer_unique_id ({n_unique_id} distinct) should be LESS than customer_id "
        f"({n_customer_id} distinct) -- this is the expected signal that repeat customers exist. "
        f"If they are equal, either the repeat-customer signal has been lost or the raw data changed."
    )


def test_customer_identity_valid_flag_matches_raw(canonical, raw):
    dc = canonical["dim_customer"]
    assert dc["customer_identity_valid"].all(), (
        "All customer_identity_valid flags are expected True given Step 1's finding of 0% null "
        "customer_id/customer_unique_id -- if this fails, the raw data has changed and the flag "
        "correctly caught a real identity problem that must be investigated, not suppressed."
    )


def test_fact_orders_customer_unique_id_denormalization_matches_dim_customer(canonical):
    """fact_orders.customer_unique_id is denormalized from dim_customer -- verify it
    was not corrupted in the join."""
    fo, dc = canonical["fact_orders"], canonical["dim_customer"]
    merged = fo[["order_id", "customer_id", "customer_unique_id"]].merge(
        dc[["customer_id", "customer_unique_id"]], on="customer_id", suffixes=("_fact", "_dim")
    )
    mismatches = merged[merged["customer_unique_id_fact"] != merged["customer_unique_id_dim"]]
    assert len(mismatches) == 0, (
        f"{len(mismatches)} orders have a customer_unique_id in fact_orders that does not match "
        f"dim_customer for the same customer_id -- denormalization is corrupted."
    )
