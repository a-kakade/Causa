"""
step2_04_build_canonical.py — STEP 2 §3-17: build the canonical data model.

Reads raw tables (via lib.raw_loader, read-only), applies the analytical-window
decision from reports/step2_window_analysis.json, and writes 10 canonical tables to
data/processed/*.parquet. Every transformation is logged to
reports/step2_build_summary.json (row counts in/out, dropped counts with exact
reasons, transformed-record counts) so nothing here is opaque.

Tables written:
  dim_customer, dim_product, dim_seller           -- dimensions
  fact_orders, fact_order_items, fact_payments,   -- facts (native grain, no premature
  fact_reviews                                       aggregation)
  agg_order_items, agg_order_payments,            -- explicit order-level aggregates
  agg_order_reviews                                  (never silently substituted for facts)

Design principle enforced throughout: NO measure that belongs to another grain is
added to fact_orders without an explicit, named, separately-materialized aggregate
table. This is what makes the fan-out mistake structurally hard to make -- there is
no `fact_orders.revenue` column to accidentally multiply; revenue only exists in
agg_order_items, one row per order, already summed.

Missing data is never silently converted to zero. Absence of a payment/review/item
is represented by that order's absence from the corresponding agg_* table (a LEFT
JOIN from fact_orders will correctly produce NULL, not 0) and by explicit boolean
flags on fact_orders (has_items, has_payment, has_review, has_delivery_data).

Usage:
    python scripts/step2_04_build_canonical.py
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from lib.raw_loader import load_raw_tables, PROCESSED_DIR, REPORTS_DIR, REPO_ROOT


# ---------------------------------------------------------------------------
# Dimensions
# ---------------------------------------------------------------------------

def build_dim_customer(customers: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per customer_id (order-scoped identity), exactly as raw.
    customer_unique_id (person-level identity) is preserved as a plain attribute
    column, NOT collapsed into -- this table is intentionally NOT deduplicated to
    one row per person. See docs/CANONICAL_DATA_MODEL.md for why."""
    df = customers.copy()
    df["customer_identity_valid"] = df["customer_id"].notna() & df["customer_unique_id"].notna()
    return df[[
        "customer_id", "customer_unique_id", "customer_zip_code_prefix",
        "customer_city", "customer_state", "customer_identity_valid",
    ]]


def build_dim_product(products: pd.DataFrame, category_translation: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per product_id, exactly as raw (32,951 rows in, 32,951 rows out
    -- LEFT join never drops a row). category_resolution_status in
    {TRANSLATED, UNTRANSLATED, NULL_CATEGORY}."""
    df = products.merge(
        category_translation, on="product_category_name", how="left", indicator=True
    )
    assert len(df) == len(products), (
        f"dim_product row count changed on join: {len(products)} -> {len(df)}. "
        "This must never happen (category_translation join must be LEFT, one row per category)."
    )

    def resolve(row):
        if pd.isna(row["product_category_name"]):
            return "NULL_CATEGORY"
        if row["_merge"] == "both":
            return "TRANSLATED"
        return "UNTRANSLATED"

    df["category_resolution_status"] = df.apply(resolve, axis=1)
    df = df.rename(columns={
        "product_category_name": "category_name_pt",
        "product_category_name_english": "category_name_en",
    })
    df = df.drop(columns=["_merge"])
    return df[[
        "product_id", "category_name_pt", "category_name_en", "category_resolution_status",
        "product_name_lenght", "product_description_lenght", "product_photos_qty",
        "product_weight_g", "product_length_cm", "product_height_cm", "product_width_cm",
    ]]


def build_dim_seller(sellers: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per seller_id, exactly as raw. Geolocation NOT joined -- see
    docs/GEOLOCATION_DECISION.md."""
    return sellers[["seller_id", "seller_zip_code_prefix", "seller_city", "seller_state"]].copy()


# ---------------------------------------------------------------------------
# Facts (native grain -- no premature aggregation)
# ---------------------------------------------------------------------------

def build_fact_order_items(order_items: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per (order_id, order_item_id). Validated as the PK -- build fails
    loudly if this is ever violated by a future raw-data refresh."""
    dup = order_items.duplicated(subset=["order_id", "order_item_id"]).sum()
    assert dup == 0, f"fact_order_items PK (order_id, order_item_id) has {dup} duplicate rows"
    return order_items[[
        "order_id", "order_item_id", "product_id", "seller_id",
        "shipping_limit_date", "price", "freight_value",
    ]].copy()


def build_fact_payments(order_payments: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per (order_id, payment_sequential). Validated as the PK."""
    dup = order_payments.duplicated(subset=["order_id", "payment_sequential"]).sum()
    assert dup == 0, f"fact_payments PK (order_id, payment_sequential) has {dup} duplicate rows"
    return order_payments[[
        "order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value",
    ]].copy()


def build_fact_reviews(order_reviews: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per RAW review record -- genuine review grain, NOT deduplicated
    to order grain. review_id is NOT a valid PK on its own (814 duplicates, verified
    in Step 1) so a synthetic surrogate `review_row_id` is added as the actual
    technical primary key of this table. review_id, order_id, and all raw review
    fields are preserved unchanged."""
    df = order_reviews.copy().reset_index(drop=True)
    df.insert(0, "review_row_id", df.index.astype(int))
    df["has_text"] = df["review_comment_message"].fillna("").str.strip() != ""
    return df[[
        "review_row_id", "review_id", "order_id", "review_score",
        "review_comment_title", "review_comment_message",
        "review_creation_date", "review_answer_timestamp", "has_text",
    ]]


# ---------------------------------------------------------------------------
# Explicit order-level aggregates (NEVER substituted silently for facts)
# ---------------------------------------------------------------------------

def build_agg_order_items(order_items: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per order_id THAT HAS AT LEAST ONE order_item (98,666 of 99,441
    orders -- the 775 without items are simply absent, not zero-filled). This is the
    ONLY table CAUSA_REVENUE is defined against -- see docs/KPI_SEMANTICS_PREVIEW.md."""
    g = order_items.groupby("order_id").agg(
        item_count=("order_item_id", "count"),
        item_price_total=("price", "sum"),
        item_freight_total=("freight_value", "sum"),
        distinct_product_count=("product_id", "nunique"),
        distinct_seller_count=("seller_id", "nunique"),
    )
    g["item_gmv_total"] = g["item_price_total"] + g["item_freight_total"]
    return g.reset_index()[[
        "order_id", "item_count", "item_price_total", "item_freight_total", "item_gmv_total",
        "distinct_product_count", "distinct_seller_count",
    ]]


def build_agg_order_payments(order_payments: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per order_id THAT HAS AT LEAST ONE payment row (99,440 of 99,441
    -- the 1 without a payment is simply absent, not zero-filled)."""
    def payment_types_sorted(s):
        return ",".join(sorted(s.unique()))

    g = order_payments.groupby("order_id").agg(
        total_payment_value=("payment_value", "sum"),
        payment_count=("payment_sequential", "count"),
        max_installments=("payment_installments", "max"),
    )
    types = order_payments.groupby("order_id")["payment_type"].apply(payment_types_sorted)
    g["payment_types"] = types
    return g.reset_index()[[
        "order_id", "total_payment_value", "payment_count", "payment_types", "max_installments",
    ]]


def build_agg_order_reviews(order_reviews: pd.DataFrame) -> pd.DataFrame:
    """Grain: 1 row per order_id THAT HAS AT LEAST ONE review (98,673 of 99,441 --
    the 768 without any review are simply absent, not zero-filled or NULL-filled with
    a fake score). Materializes BOTH a true aggregate (avg/min/max_review_score,
    computed over ALL of that order's reviews) AND a single representative value
    (latest_review_score, per the dedup decision in docs/REVIEW_GOVERNANCE.md) --
    these are two different, deliberately-not-conflated operations."""
    has_text = order_reviews["review_comment_message"].fillna("").str.strip() != ""
    df = order_reviews.copy()
    df["has_text"] = has_text

    latest = df.sort_values("review_answer_timestamp").drop_duplicates(subset="order_id", keep="last")
    latest = latest.set_index("order_id")[["review_id", "review_score"]].rename(
        columns={"review_id": "latest_review_id", "review_score": "latest_review_score"}
    )

    g = df.groupby("order_id").agg(
        review_count=("review_id", "count"),
        avg_review_score=("review_score", "mean"),
        min_review_score=("review_score", "min"),
        max_review_score=("review_score", "max"),
        has_review_text=("has_text", "any"),
        first_review_creation_date=("review_creation_date", "min"),
        last_review_answer_timestamp=("review_answer_timestamp", "max"),
    )
    g["avg_review_score"] = g["avg_review_score"].round(4)
    g = g.join(latest)
    return g.reset_index()[[
        "order_id", "review_count", "avg_review_score", "min_review_score", "max_review_score",
        "latest_review_score", "latest_review_id", "has_review_text",
        "first_review_creation_date", "last_review_answer_timestamp",
    ]]


# ---------------------------------------------------------------------------
# fact_orders -- the anchor table
# ---------------------------------------------------------------------------

def compute_delivery_fields(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    purchase = df["purchase_timestamp"]
    carrier = df["carrier_delivery_timestamp"]
    customer = df["customer_delivery_timestamp"]
    estimated = df["estimated_delivery_timestamp"]

    df["delivery_days"] = (customer - purchase).dt.total_seconds() / 86400
    df["carrier_days"] = (carrier - purchase).dt.total_seconds() / 86400
    df["delivery_delay_days"] = (customer - estimated).dt.total_seconds() / 86400

    invalid_customer_seq = customer.notna() & (df["delivery_days"] < 0)
    invalid_carrier_seq = carrier.notna() & (df["carrier_days"] < 0)
    invalid_sequence = invalid_customer_seq | invalid_carrier_seq

    flag = pd.Series("VALID", index=df.index, dtype=object)
    flag[carrier.isna()] = "MISSING_CARRIER_DATE"
    flag[customer.isna()] = "MISSING_CUSTOMER_DATE"
    flag[invalid_sequence] = "INVALID_SEQUENCE"  # highest priority -- checked last so it wins
    df["delivery_data_quality_flag"] = flag
    df["has_delivery_data"] = df["delivery_data_quality_flag"] == "VALID"
    return df


def build_fact_orders(orders: pd.DataFrame, customers: pd.DataFrame,
                       agg_items: pd.DataFrame, agg_payments: pd.DataFrame,
                       agg_reviews: pd.DataFrame, window_start: str, window_end: str) -> pd.DataFrame:
    """Grain: 1 row per order_id -- ALL 99,441 orders, none dropped. The analytical
    window is NOT applied by deleting rows; it is applied by the `in_analytical_window`
    boolean flag, so excluded periods remain available for exploratory/reference use
    (per docs/ANALYTICAL_WINDOW.md) without being silently discarded."""
    df = orders.rename(columns={
        "order_purchase_timestamp": "purchase_timestamp",
        "order_approved_at": "approved_timestamp",
        "order_delivered_carrier_date": "carrier_delivery_timestamp",
        "order_delivered_customer_date": "customer_delivery_timestamp",
        "order_estimated_delivery_date": "estimated_delivery_timestamp",
    }).copy()

    df = df.merge(
        customers[["customer_id", "customer_unique_id", "customer_state", "customer_city"]],
        on="customer_id", how="left",
    )

    df = compute_delivery_fields(df)

    df["has_items"] = df["order_id"].isin(agg_items["order_id"])
    df["has_payment"] = df["order_id"].isin(agg_payments["order_id"])
    df["has_review"] = df["order_id"].isin(agg_reviews["order_id"])

    purchase_month = df["purchase_timestamp"].dt.to_period("M").astype(str)
    df["in_analytical_window"] = (purchase_month >= window_start) & (purchase_month <= window_end)

    return df[[
        "order_id", "customer_id", "customer_unique_id", "order_status",
        "purchase_timestamp", "approved_timestamp", "carrier_delivery_timestamp",
        "customer_delivery_timestamp", "estimated_delivery_timestamp",
        "customer_state", "customer_city",
        "delivery_days", "carrier_days", "delivery_delay_days", "delivery_data_quality_flag",
        "has_items", "has_payment", "has_review", "has_delivery_data",
        "in_analytical_window",
    ]]


# ---------------------------------------------------------------------------
# Orchestration + build summary
# ---------------------------------------------------------------------------

def main():
    window = json.load(open(REPORTS_DIR / "step2_window_analysis.json"))
    window_start, window_end = window["first_reliable_month"], window["last_reliable_month"]

    dfs = load_raw_tables()
    raw_counts = {name: len(df) for name, df in dfs.items()}

    dim_customer = build_dim_customer(dfs["customers"])
    dim_product = build_dim_product(dfs["products"], dfs["category_translation"])
    dim_seller = build_dim_seller(dfs["sellers"])

    fact_order_items = build_fact_order_items(dfs["order_items"])
    fact_payments = build_fact_payments(dfs["order_payments"])
    fact_reviews = build_fact_reviews(dfs["order_reviews"])

    agg_order_items = build_agg_order_items(dfs["order_items"])
    agg_order_payments = build_agg_order_payments(dfs["order_payments"])
    agg_order_reviews = build_agg_order_reviews(dfs["order_reviews"])

    fact_orders = build_fact_orders(
        dfs["orders"], dfs["customers"], agg_order_items, agg_order_payments, agg_order_reviews,
        window_start, window_end,
    )

    # -- integrity assertions (fail loudly, not silently) --
    assert len(fact_orders) == raw_counts["orders"], "fact_orders must have exactly 1 row per raw order"
    assert fact_orders["order_id"].is_unique, "fact_orders.order_id must be unique"
    assert (fact_order_items.groupby(["order_id", "order_item_id"]).size() == 1).all()
    assert (fact_payments.groupby(["order_id", "payment_sequential"]).size() == 1).all()
    assert len(dim_product) == raw_counts["products"], "dim_product join must not drop rows"
    assert len(dim_customer) == raw_counts["customers"]
    assert len(dim_seller) == raw_counts["sellers"]

    tables = {
        "dim_customer": dim_customer, "dim_product": dim_product, "dim_seller": dim_seller,
        "fact_orders": fact_orders, "fact_order_items": fact_order_items,
        "fact_payments": fact_payments, "fact_reviews": fact_reviews,
        "agg_order_items": agg_order_items, "agg_order_payments": agg_order_payments,
        "agg_order_reviews": agg_order_reviews,
    }

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(PROCESSED_DIR / f"{name}.parquet", index=False)

    # -- build summary: row counts, dropped/transformed records, exact reasons --
    summary = {
        "analytical_window": {"start": window_start, "end": window_end},
        "raw_row_counts": raw_counts,
        "canonical_row_counts": {name: int(len(df)) for name, df in tables.items()},
        "row_count_reconciliation": {
            "fact_orders_vs_raw_orders": {
                "raw": raw_counts["orders"], "canonical": len(fact_orders),
                "dropped": 0, "reason": "no rows dropped -- fact_orders is 1:1 with raw orders by design",
            },
            "fact_order_items_vs_raw_order_items": {
                "raw": raw_counts["order_items"], "canonical": len(fact_order_items),
                "dropped": 0, "reason": "no rows dropped -- native grain preserved exactly",
            },
            "fact_payments_vs_raw_order_payments": {
                "raw": raw_counts["order_payments"], "canonical": len(fact_payments),
                "dropped": 0, "reason": "no rows dropped -- native grain preserved exactly",
            },
            "fact_reviews_vs_raw_order_reviews": {
                "raw": raw_counts["order_reviews"], "canonical": len(fact_reviews),
                "dropped": 0, "reason": "no rows dropped -- native grain preserved exactly, including "
                                         "814 duplicate review_id rows and all 547 multi-review orders; "
                                         "a surrogate review_row_id was ADDED (not a drop) as the real PK",
            },
            "agg_order_items_vs_raw_orders": {
                "raw": raw_counts["orders"], "canonical": len(agg_order_items),
                "dropped": raw_counts["orders"] - len(agg_order_items),
                "reason": f"{raw_counts['orders'] - len(agg_order_items)} orders have zero order_items "
                          "rows and are therefore absent from this order-level aggregate by construction "
                          "(NOT zero-filled) -- see fact_orders.has_items to detect these",
            },
            "agg_order_payments_vs_raw_orders": {
                "raw": raw_counts["orders"], "canonical": len(agg_order_payments),
                "dropped": raw_counts["orders"] - len(agg_order_payments),
                "reason": f"{raw_counts['orders'] - len(agg_order_payments)} order(s) have zero payment "
                          "rows and are therefore absent (NOT zero-filled) -- see fact_orders.has_payment",
            },
            "agg_order_reviews_vs_raw_orders": {
                "raw": raw_counts["orders"], "canonical": len(agg_order_reviews),
                "dropped": raw_counts["orders"] - len(agg_order_reviews),
                "reason": f"{raw_counts['orders'] - len(agg_order_reviews)} orders have zero review rows "
                          "and are therefore absent (NOT zero-filled) -- see fact_orders.has_review",
            },
            "dim_product_category_resolution": dim_product["category_resolution_status"].value_counts().to_dict(),
        },
        "transformed_records": {
            "fact_orders_delivery_flags": fact_orders["delivery_data_quality_flag"].value_counts().to_dict(),
            "fact_orders_in_analytical_window": int(fact_orders["in_analytical_window"].sum()),
            "fact_orders_outside_analytical_window": int((~fact_orders["in_analytical_window"]).sum()),
            "invalid_sequence_orders_sample": fact_orders.loc[
                fact_orders["delivery_data_quality_flag"] == "INVALID_SEQUENCE", "order_id"
            ].head(10).tolist(),
        },
    }

    out_path = REPORTS_DIR / "step2_build_summary.json"
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print("=== CANONICAL ROW COUNTS ===")
    for name, df in tables.items():
        print(f"{name:22} {len(df):>8,} rows  {len(df.columns):>2} cols")
    print(f"\nDelivery quality flags: {summary['transformed_records']['fact_orders_delivery_flags']}")
    print(f"In analytical window ({window_start}..{window_end}): "
          f"{summary['transformed_records']['fact_orders_in_analytical_window']:,} orders")
    print(f"\nWritten: {out_path}")
    print(f"Parquet files in: {PROCESSED_DIR}")


if __name__ == "__main__":
    main()
