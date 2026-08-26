"""
kpi_temporal_eda.py

Builds the order-item fact table from the raw Olist CSVs, verifies the revenue
reconciliation (order_items vs order_payments), computes candidate KPI time series
(orders, revenue, AOV, quantity, freight, delivery time, review score, review volume)
at daily/weekly/monthly grain, and flags candidate material movements.

This script does NOT modify any raw CSV. It reads from data/raw/olist/ and writes:
  - reports/kpi_timeseries_monthly.csv (and _weekly.csv)
  - reports/kpi_eda_summary.json (machine-readable: reconciliation stats, anomaly
    candidates, sparse-history counts, segmentation cardinality)
  - eda_plots/*.png

Usage:
    python scripts/kpi_temporal_eda.py
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "raw" / "olist"
REPORTS_DIR = REPO_ROOT / "reports"
PLOTS_DIR = REPO_ROOT / "eda_plots"
REPORTS_DIR.mkdir(exist_ok=True)
PLOTS_DIR.mkdir(exist_ok=True)


def load():
    orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv", parse_dates=[
        "order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
        "order_delivered_customer_date", "order_estimated_delivery_date"
    ])
    items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv", parse_dates=["shipping_limit_date"])
    payments = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv")
    reviews = pd.read_csv(DATA_DIR / "olist_order_reviews_dataset.csv", parse_dates=[
        "review_creation_date", "review_answer_timestamp"
    ])
    products = pd.read_csv(DATA_DIR / "olist_products_dataset.csv")
    sellers = pd.read_csv(DATA_DIR / "olist_sellers_dataset.csv")
    customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")
    cat_translation = pd.read_csv(DATA_DIR / "product_category_name_translation.csv")
    return orders, items, payments, reviews, products, sellers, customers, cat_translation


def revenue_reconciliation(orders, items, payments) -> dict:
    """Per-order sum(price+freight) from order_items vs sum(payment_value) from
    order_payments. This determines whether order_items or order_payments is the
    correct 'revenue' source of truth for Causa KPIs."""
    items_per_order = items.groupby("order_id").agg(
        item_total=("price", "sum"), freight_total=("freight_value", "sum"), n_items=("order_item_id", "count")
    )
    items_per_order["order_items_total"] = items_per_order["item_total"] + items_per_order["freight_total"]

    payments_per_order = payments.groupby("order_id").agg(payment_total=("payment_value", "sum"))

    merged = items_per_order.join(payments_per_order, how="outer")
    n_orders_items_only = int(merged["payment_total"].isna().sum())
    n_orders_payments_only = int(merged["order_items_total"].isna().sum())
    both = merged.dropna(subset=["order_items_total", "payment_total"]).copy()
    both["diff"] = both["payment_total"] - both["order_items_total"]
    both["abs_diff"] = both["diff"].abs()
    # tolerance for float rounding
    matched_within_1c = int((both["abs_diff"] <= 0.01).sum())
    mismatched = both[both["abs_diff"] > 0.01]

    n_orders_total_rows = len(orders)
    n_orders_with_items = items["order_id"].nunique()
    n_orders_with_payments = payments["order_id"].nunique()

    return {
        "n_orders_total": n_orders_total_rows,
        "n_orders_with_items": int(n_orders_with_items),
        "n_orders_without_items": int(n_orders_total_rows - n_orders_with_items),
        "n_orders_with_payments": int(n_orders_with_payments),
        "n_orders_without_payments": int(n_orders_total_rows - n_orders_with_payments),
        "n_orders_in_both_items_and_payments": len(both),
        "n_orders_items_only_no_payment_row": n_orders_items_only,
        "n_orders_payment_only_no_item_row": n_orders_payments_only,
        "n_matched_within_1_cent": matched_within_1c,
        "matched_rate_of_both": round(matched_within_1c / len(both), 4) if len(both) else None,
        "n_mismatched": len(mismatched),
        "mismatch_abs_diff_mean": round(float(mismatched["abs_diff"].mean()), 2) if len(mismatched) else None,
        "mismatch_abs_diff_median": round(float(mismatched["abs_diff"].median()), 2) if len(mismatched) else None,
        "mismatch_abs_diff_max": round(float(mismatched["abs_diff"].max()), 2) if len(mismatched) else None,
        "top_10_mismatches": mismatched.sort_values("abs_diff", ascending=False).head(10)[
            ["order_items_total", "payment_total", "diff"]
        ].reset_index().to_dict(orient="records"),
    }


def build_order_fact(orders, items, payments, reviews) -> pd.DataFrame:
    """One row per order_id: revenue (from order_items, the line-item source of truth),
    item/freight totals, quantity, delivery time, status, review score. Orders without
    order_items (n=775, mostly non-delivered) get NaN revenue, not zero -- zero would
    misrepresent 'no transaction value' as 'confirmed zero revenue'."""
    items_agg = items.groupby("order_id").agg(
        revenue=("price", "sum"), freight=("freight_value", "sum"), quantity=("order_item_id", "count"),
        n_distinct_products=("product_id", "nunique"), n_distinct_sellers=("seller_id", "nunique"),
    )
    items_agg["gross_merchandise_value"] = items_agg["revenue"] + items_agg["freight"]

    reviews_agg = reviews.sort_values("review_answer_timestamp").groupby("order_id").agg(
        review_score=("review_score", "last")
    )

    fact = orders.set_index("order_id").join(items_agg, how="left").join(reviews_agg, how="left")
    fact["delivery_days"] = (fact["order_delivered_customer_date"] - fact["order_purchase_timestamp"]).dt.total_seconds() / 86400
    fact["estimate_accuracy_days"] = (fact["order_estimated_delivery_date"] - fact["order_delivered_customer_date"]).dt.total_seconds() / 86400
    fact["purchase_date"] = fact["order_purchase_timestamp"].dt.normalize()
    return fact.reset_index()


def kpi_timeseries(fact: pd.DataFrame, freq: str, delivered_only: bool) -> pd.DataFrame:
    df = fact.copy()
    if delivered_only:
        df = df[df["order_status"] == "delivered"]
    df = df.dropna(subset=["order_purchase_timestamp"])
    g = df.set_index("order_purchase_timestamp").resample(freq)

    out = pd.DataFrame({
        "orders": g["order_id"].count(),
        "revenue": g["revenue"].sum(min_count=1),
        "freight": g["freight"].sum(min_count=1),
        "gmv": g["gross_merchandise_value"].sum(min_count=1),
        "quantity": g["quantity"].sum(min_count=1),
        "avg_delivery_days": g["delivery_days"].mean(),
        "avg_review_score": g["review_score"].mean(),
        "review_count": g["review_score"].count(),
    })
    out["aov"] = out["revenue"] / out["orders"]
    return out


def add_change_stats(ts: pd.DataFrame, roll_window: int) -> pd.DataFrame:
    ts = ts.copy()
    for col in ["orders", "revenue", "aov", "avg_delivery_days", "avg_review_score"]:
        if col not in ts.columns:
            continue
        ts[f"{col}_pct_change"] = ts[col].pct_change() * 100
        ts[f"{col}_roll_mean"] = ts[col].rolling(roll_window, min_periods=max(2, roll_window // 2)).mean()
        ts[f"{col}_roll_std"] = ts[col].rolling(roll_window, min_periods=max(2, roll_window // 2)).std()
        ts[f"{col}_zscore"] = (ts[col] - ts[f"{col}_roll_mean"]) / ts[f"{col}_roll_std"]
    return ts


def detect_material_movements(monthly: pd.DataFrame, min_orders_base=200) -> list[dict]:
    """Month-over-month movements in core KPIs, restricted to months with a
    plausible order-volume base (avoids flagging early 2016 near-zero-volume noise)."""
    candidates = []
    df = monthly[monthly["orders"] >= min_orders_base].copy()
    for col in ["orders", "revenue", "aov", "avg_delivery_days", "avg_review_score"]:
        pct_col = f"{col}_pct_change"
        if pct_col not in df.columns:
            continue
        for period, row in df.iterrows():
            pct = row[pct_col]
            if pd.isna(pct):
                continue
            if abs(pct) >= 15:  # material threshold, in percent
                candidates.append({
                    "kpi": col,
                    "period": str(period.date()) if hasattr(period, "date") else str(period),
                    "value": None if pd.isna(row[col]) else round(float(row[col]), 2),
                    "pct_change_mom": round(float(pct), 2),
                    "orders_that_month": int(row["orders"]),
                })
    candidates.sort(key=lambda c: abs(c["pct_change_mom"]), reverse=True)
    return candidates


def plot_series(monthly: pd.DataFrame):
    fig, axes = plt.subplots(4, 2, figsize=(14, 16))
    plots = [
        ("orders", "Orders per month"),
        ("revenue", "Revenue per month (order_items.price sum)"),
        ("aov", "Average Order Value"),
        ("freight", "Freight per month"),
        ("quantity", "Item quantity per month"),
        ("avg_delivery_days", "Avg delivery days (purchase->delivered)"),
        ("avg_review_score", "Avg review score"),
        ("review_count", "Review volume"),
    ]
    for ax, (col, title) in zip(axes.flat, plots):
        ax.plot(monthly.index, monthly[col], marker="o", markersize=3)
        ax.set_title(title, fontsize=10)
        ax.tick_params(axis="x", rotation=45, labelsize=7)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "kpi_monthly_overview.png", dpi=130)
    plt.close(fig)

    # revenue with rolling mean/std band
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(monthly.index, monthly["revenue"], label="revenue (monthly)")
    if "revenue_roll_mean" in monthly.columns:
        ax.plot(monthly.index, monthly["revenue_roll_mean"], label="rolling mean (3mo)", linestyle="--")
    ax.set_title("Monthly revenue with rolling mean")
    ax.legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "revenue_rolling.png", dpi=130)
    plt.close(fig)

    # order status distribution over time (stacked)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.bar(monthly.index, monthly["orders"], width=20)
    ax.set_title("Order volume per month (all statuses at daily->monthly resample)")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "orders_volume.png", dpi=130)
    plt.close(fig)


def sparse_history(fact: pd.DataFrame, items: pd.DataFrame, products: pd.DataFrame, sellers: pd.DataFrame) -> dict:
    delivered = fact[fact["order_status"] == "delivered"]
    item_txn = items.merge(delivered[["order_id", "purchase_date"]], on="order_id", how="inner")

    per_product = item_txn.groupby("product_id").size()
    per_seller = item_txn.groupby("seller_id").size()

    def bucket(counts: pd.Series) -> dict:
        return {
            "n_entities": int(counts.shape[0]),
            "lt_30_obs": int((counts < 30).sum()),
            "lt_90_obs": int((counts < 90).sum()),
            "lt_180_obs": int((counts < 180).sum()),
            "pct_lt_30": round(float((counts < 30).mean()) * 100, 2),
            "pct_lt_90": round(float((counts < 90).mean()) * 100, 2),
            "median_obs": float(counts.median()),
        }

    # products/sellers present in products/sellers table but with zero delivered transactions
    products_zero = int((~products["product_id"].isin(per_product.index)).sum())
    sellers_zero = int((~sellers["seller_id"].isin(per_seller.index)).sum())

    # category-level counts (join through products)
    prod_cat = products.set_index("product_id")["product_category_name"]
    item_txn_cat = item_txn.join(prod_cat, on="product_id")
    per_category = item_txn_cat.groupby("product_category_name").size().sort_values()

    return {
        "products": bucket(per_product),
        "sellers": bucket(per_seller),
        "products_with_zero_delivered_transactions": products_zero,
        "sellers_with_zero_delivered_transactions": sellers_zero,
        "n_categories": int(per_category.shape[0]),
        "categories_lt_30_obs": int((per_category < 30).sum()),
        "smallest_5_categories": per_category.head(5).to_dict(),
        "largest_5_categories": per_category.tail(5).to_dict(),
    }


def segmentation_cardinality(fact: pd.DataFrame, items: pd.DataFrame, products: pd.DataFrame,
                              sellers: pd.DataFrame, customers: pd.DataFrame) -> dict:
    delivered = fact[fact["order_status"] == "delivered"]
    item_txn = items.merge(delivered[["order_id"]], on="order_id", how="inner")
    item_txn = item_txn.merge(sellers[["seller_id", "seller_state"]], on="seller_id", how="left")
    item_txn = item_txn.merge(products[["product_id", "product_category_name"]], on="product_id", how="left")

    return {
        "n_seller_states": int(sellers["seller_state"].nunique()),
        "n_customer_states": int(customers["customer_state"].nunique()),
        "n_product_categories": int(products["product_category_name"].nunique(dropna=True)),
        "n_sellers": int(sellers["seller_id"].nunique()),
        "revenue_by_seller_state": item_txn.groupby("seller_state")["price"].sum().sort_values(ascending=False).round(2).to_dict(),
        "orders_by_customer_state": delivered.merge(
            customers[["customer_id", "customer_state"]], on="customer_id", how="left"
        )["customer_state"].value_counts().to_dict(),
        "top_20_sellers_share_of_revenue_pct": round(
            float(item_txn.groupby("seller_id")["price"].sum().sort_values(ascending=False).head(20).sum()
                  / item_txn["price"].sum() * 100), 2
        ),
    }


def main():
    orders, items, payments, reviews, products, sellers, customers, cat_translation = load()

    recon = revenue_reconciliation(orders, items, payments)
    fact = build_order_fact(orders, items, payments, reviews)

    monthly = kpi_timeseries(fact, "MS", delivered_only=False)
    monthly = add_change_stats(monthly, roll_window=3)
    weekly = kpi_timeseries(fact, "W-MON", delivered_only=False)
    weekly = add_change_stats(weekly, roll_window=4)

    monthly.to_csv(REPORTS_DIR / "kpi_timeseries_monthly.csv")
    weekly.to_csv(REPORTS_DIR / "kpi_timeseries_weekly.csv")

    plot_series(monthly)

    material = detect_material_movements(monthly)
    sparse = sparse_history(fact, items, products, sellers)
    segmentation = segmentation_cardinality(fact, items, products, sellers, customers)

    # order lifecycle anomaly: shipping_limit_date extending far beyond order date range
    shipping_future = items[items["shipping_limit_date"] > orders["order_purchase_timestamp"].max()]
    order_date_span = {
        "order_purchase_timestamp_max": str(orders["order_purchase_timestamp"].max()),
        "shipping_limit_date_max": str(items["shipping_limit_date"].max()),
        "n_items_with_shipping_limit_after_last_order": int(len(shipping_future)),
    }

    summary = {
        "revenue_reconciliation": recon,
        "material_movements_monthly_ge15pct": material[:25],
        "sparse_history": sparse,
        "segmentation_cardinality": segmentation,
        "date_anomalies": order_date_span,
        "order_status_value_counts": orders["order_status"].value_counts().to_dict(),
        "orders_missing_from_order_items": int(orders.shape[0] - items["order_id"].nunique()),
    }

    with open(REPORTS_DIR / "kpi_eda_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(json.dumps(summary, indent=2, default=str)[:6000])
    print(f"\nWritten: {REPORTS_DIR / 'kpi_eda_summary.json'}")
    print(f"Written: {REPORTS_DIR / 'kpi_timeseries_monthly.csv'}")
    print(f"Plots in: {PLOTS_DIR}")


if __name__ == "__main__":
    main()
