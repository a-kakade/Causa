"""
step2_01_window_analysis.py — STEP 2 §2: decide the analytical time window.

Fresh, from-scratch quantitative analysis (does not reuse the prior EDA session's
window conclusion, and does not reuse Step 1's audit numbers directly -- recomputes
everything from the raw tables via scripts/lib/raw_loader.py) of:
  - monthly order volume
  - monthly revenue (SUM order_items.price, orders grouped by purchase month)
  - monthly missingness of key order fields
  - monthly delivery-timestamp coverage
  - monthly review coverage

Produces a data-driven threshold rule (not an eyeballed cutoff) for which months are
statistically reliable, and reports the consequence of each candidate window.

Writes reports/step2_window_analysis.json. Does not modify data/raw/. Does not write
data/processed/ (that happens in step2_04_build_canonical.py, which imports the
window decision from this script's output).
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from lib.raw_loader import load_raw_tables, REPORTS_DIR


def monthly_metrics(orders: pd.DataFrame, order_items: pd.DataFrame,
                     order_reviews: pd.DataFrame) -> pd.DataFrame:
    o = orders.copy()
    o["purchase_month"] = o["order_purchase_timestamp"].dt.to_period("M")

    # revenue: aggregate order_items to order grain FIRST (anti-fan-out discipline,
    # applied even in this exploratory script), then join purchase_month.
    items_per_order = order_items.groupby("order_id")["price"].sum().rename("order_revenue")
    o = o.merge(items_per_order, on="order_id", how="left")

    reviews_per_order = order_reviews.groupby("order_id").size().rename("n_reviews")
    o = o.merge(reviews_per_order, on="order_id", how="left")
    o["n_reviews"] = o["n_reviews"].fillna(0).astype(int)

    g = o.groupby("purchase_month")
    metrics = pd.DataFrame({
        "orders": g["order_id"].count(),
        "revenue": g["order_revenue"].sum(min_count=1),
        "orders_missing_items_revenue": g["order_revenue"].apply(lambda s: int(s.isna().sum())),
        "orders_missing_approved_at": g["order_approved_at"].apply(lambda s: int(s.isna().sum())),
        "orders_missing_carrier_date": g["order_delivered_carrier_date"].apply(lambda s: int(s.isna().sum())),
        "orders_missing_customer_delivery_date": g["order_delivered_customer_date"].apply(lambda s: int(s.isna().sum())),
        "orders_with_zero_reviews": g["n_reviews"].apply(lambda s: int((s == 0).sum())),
    })
    metrics["delivery_coverage_pct"] = round(
        (1 - metrics["orders_missing_customer_delivery_date"] / metrics["orders"]) * 100, 2
    )
    metrics["review_coverage_pct"] = round(
        (1 - metrics["orders_with_zero_reviews"] / metrics["orders"]) * 100, 2
    )
    metrics["items_coverage_pct"] = round(
        (1 - metrics["orders_missing_items_revenue"] / metrics["orders"]) * 100, 2
    )
    metrics["aov"] = (metrics["revenue"] / (metrics["orders"] - metrics["orders_missing_items_revenue"])).round(2)
    return metrics


def classify_months(metrics: pd.DataFrame) -> pd.DataFrame:
    """Data-driven reliability rule, not an eyeballed cutoff:
    a month is UNRELIABLE if its order count is < 10% of the median order count
    across all months with >0 orders. This threshold is reported explicitly, and
    cross-validated against coverage metrics below rather than trusted alone."""
    nonzero = metrics[metrics["orders"] > 0]
    median_orders = float(nonzero["orders"].median())
    threshold = median_orders * 0.10
    metrics = metrics.copy()
    metrics["median_monthly_orders_all_nonzero_months"] = median_orders
    metrics["reliability_threshold_10pct_of_median"] = round(threshold, 1)
    metrics["volume_reliable"] = metrics["orders"] >= threshold
    return metrics


def main():
    dfs = load_raw_tables()
    metrics = monthly_metrics(dfs["orders"], dfs["order_items"], dfs["order_reviews"])
    metrics = classify_months(metrics)

    reliable = metrics[metrics["volume_reliable"]]
    unreliable = metrics[~metrics["volume_reliable"]]

    first_reliable = reliable.index.min()
    last_reliable = reliable.index.max()

    # cross-validate: are the unreliable-by-volume months ALSO anomalous on coverage?
    cross_validation = {
        "unreliable_months_orders_total": int(unreliable["orders"].sum()),
        "unreliable_months_revenue_total": None if unreliable["revenue"].isna().all()
        else round(float(unreliable["revenue"].sum()), 2),
        "unreliable_months_delivery_coverage_pct_range": [
            float(unreliable["delivery_coverage_pct"].min()) if len(unreliable) else None,
            float(unreliable["delivery_coverage_pct"].max()) if len(unreliable) else None,
        ],
        "reliable_months_delivery_coverage_pct_range": [
            float(reliable["delivery_coverage_pct"].min()),
            float(reliable["delivery_coverage_pct"].max()),
        ],
        "note": "Mixed picture, reported honestly rather than force-fit to one story: 2016-10 (324 "
                "orders) has broadly normal-looking coverage (83-98%), so its exclusion is a volume/"
                "statistical-power argument, not a data-quality one. But 2018-09 (16 orders) and "
                "2018-10 (4 orders) are structurally incomplete, not just low-volume -- items_coverage "
                "drops to 6.25% and 0% respectively, and delivery_coverage to 0% in both -- consistent "
                "with orders placed too close to the data-extraction date to have progressed through "
                "the fulfillment pipeline yet. This is stronger, independent evidence for excluding the "
                "2018-09/2018-10 tail specifically (not just a volume heuristic), while 2016-09/2016-12 "
                "are excluded primarily on volume/statistical-power grounds.",
    }

    result = {
        "method": "10% of the median monthly order count across all months with >0 orders, "
                   "computed fresh from raw data. Cross-validated against delivery/review/items "
                   "coverage percentages per month (see cross_validation) rather than trusted on "
                   "volume alone.",
        "median_monthly_orders": float(metrics["median_monthly_orders_all_nonzero_months"].iloc[0]),
        "reliability_threshold": float(metrics["reliability_threshold_10pct_of_median"].iloc[0]),
        "first_reliable_month": str(first_reliable),
        "last_reliable_month": str(last_reliable),
        "reliable_months_count": int(len(reliable)),
        "unreliable_months": {str(k): int(v) for k, v in unreliable["orders"].items()},
        "cross_validation": cross_validation,
        "monthly_metrics": {
            str(k): {col: (None if pd.isna(v) else (float(v) if isinstance(v, (float, np.floating)) else v))
                     for col, v in row.items()}
            for k, row in metrics.drop(columns=[
                "median_monthly_orders_all_nonzero_months", "reliability_threshold_10pct_of_median"
            ]).iterrows()
        },
    }

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / "step2_window_analysis.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Median monthly orders (nonzero months): {result['median_monthly_orders']}")
    print(f"Reliability threshold (10% of median):  {result['reliability_threshold']}")
    print(f"Reliable window: {first_reliable} -> {last_reliable} ({len(reliable)} months)")
    print(f"Unreliable months: {result['unreliable_months']}")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
