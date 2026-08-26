"""
raw_loader.py — the ONE place Step 2 reads raw CSVs from.

Consolidates the raw-load logic that Step 1's REPOSITORY_AUDIT.md flagged as
duplicated across the prior EDA scripts. Every Step 2 script imports this module
rather than re-implementing pd.read_csv calls, so the encoding fix for
product_category_name_translation.csv (utf-8-sig, per DATA_FOUNDATION_REPORT.md
§A / this task's §16) lives in exactly one place.

This module NEVER writes to data/raw/olist/ — read-only, by construction (no
DataFrame.to_csv / to_parquet call exists anywhere in this file).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = REPO_ROOT / "data" / "raw" / "olist"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
REPORTS_DIR = REPO_ROOT / "reports"

RAW_FILES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

ORDER_DATE_COLS = [
    "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
    "order_delivered_customer_date", "order_estimated_delivery_date",
]
REVIEW_DATE_COLS = ["review_creation_date", "review_answer_timestamp"]
ITEM_DATE_COLS = ["shipping_limit_date"]


def load_raw_tables() -> dict[str, pd.DataFrame]:
    """Load all 9 raw Olist tables, read-only. Dates are parsed explicitly (not left
    as strings) so downstream code never has to guess a column's type. Encoding is
    explicit for every file -- utf-8-sig for category_translation (it carries a BOM,
    verified in Step 1), plain utf-8 for the rest (verified BOM-free in Step 1)."""
    for name, filename in RAW_FILES.items():
        path = RAW_DIR / filename
        if not path.exists():
            raise FileNotFoundError(
                f"Expected raw file missing: {path}. Raw data must be extracted from "
                f"archive.zip into data/raw/olist/ before running Step 2 scripts."
            )

    customers = pd.read_csv(RAW_DIR / RAW_FILES["customers"], encoding="utf-8")
    orders = pd.read_csv(RAW_DIR / RAW_FILES["orders"], encoding="utf-8", parse_dates=ORDER_DATE_COLS)
    order_items = pd.read_csv(RAW_DIR / RAW_FILES["order_items"], encoding="utf-8", parse_dates=ITEM_DATE_COLS)
    order_payments = pd.read_csv(RAW_DIR / RAW_FILES["order_payments"], encoding="utf-8")
    order_reviews = pd.read_csv(RAW_DIR / RAW_FILES["order_reviews"], encoding="utf-8", parse_dates=REVIEW_DATE_COLS)
    products = pd.read_csv(RAW_DIR / RAW_FILES["products"], encoding="utf-8")
    sellers = pd.read_csv(RAW_DIR / RAW_FILES["sellers"], encoding="utf-8")
    geolocation = pd.read_csv(RAW_DIR / RAW_FILES["geolocation"], encoding="utf-8")
    # Verified in Step 1 (DATA_FOUNDATION_REPORT.md §A): this file has a UTF-8 BOM
    # that the other 8 do not. Read explicitly with utf-8-sig per this task's §16 --
    # do not rely on pandas silently stripping it.
    category_translation = pd.read_csv(
        RAW_DIR / RAW_FILES["category_translation"], encoding="utf-8-sig"
    )
    assert category_translation.columns[0] == "product_category_name", (
        "BOM was not stripped correctly from product_category_name_translation.csv -- "
        f"got column name {category_translation.columns[0]!r}"
    )

    return {
        "customers": customers,
        "orders": orders,
        "order_items": order_items,
        "order_payments": order_payments,
        "order_reviews": order_reviews,
        "products": products,
        "sellers": sellers,
        "geolocation": geolocation,
        "category_translation": category_translation,
    }


def raw_row_counts(dfs: dict[str, pd.DataFrame]) -> dict[str, int]:
    return {name: len(df) for name, df in dfs.items()}
