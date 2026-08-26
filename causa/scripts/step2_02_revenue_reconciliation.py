"""
step2_02_revenue_reconciliation.py — STEP 2 §9: define CAUSA_REVENUE.

Fresh reconciliation of:
  A: SUM(order_items.price)          -- item-level, excludes freight
  B: SUM(order_payments.payment_value) -- payment-level, includes financing/interest

Breaks mismatches down by payment_type, installments, and order_status, and reports
the distribution of differences (not just a headline match rate), so the
CAUSA_REVENUE decision in KPI_SEMANTICS_PREVIEW.md is backed by more than one number.

Writes reports/step2_revenue_reconciliation.json. Read-only against data/raw/.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from lib.raw_loader import load_raw_tables, REPORTS_DIR


def build_order_level_comparison(orders, items, payments) -> pd.DataFrame:
    items_agg = items.groupby("order_id").agg(
        item_price_total=("price", "sum"),
        item_freight_total=("freight_value", "sum"),
        item_count=("order_item_id", "count"),
    )
    items_agg["item_gmv_total"] = items_agg["item_price_total"] + items_agg["item_freight_total"]

    payments_agg = payments.groupby("order_id").agg(
        payment_total=("payment_value", "sum"),
        payment_count=("payment_sequential", "count"),
        max_installments=("payment_installments", "max"),
    )
    dominant_payment_type = (
        payments.sort_values("payment_value", ascending=False)
        .drop_duplicates(subset="order_id")
        .set_index("order_id")["payment_type"]
    )

    df = orders[["order_id", "order_status"]].set_index("order_id")
    df = df.join(items_agg, how="outer").join(payments_agg, how="outer").join(
        dominant_payment_type.rename("dominant_payment_type"), how="left"
    )
    return df.reset_index()


def main():
    dfs = load_raw_tables()
    df = build_order_level_comparison(dfs["orders"], dfs["order_items"], dfs["order_payments"])

    both = df.dropna(subset=["item_gmv_total", "payment_total"]).copy()
    both["abs_diff"] = (both["payment_total"] - both["item_gmv_total"]).abs()
    both["rel_diff_pct"] = np.where(
        both["item_gmv_total"] > 0, both["abs_diff"] / both["item_gmv_total"] * 100, np.nan
    )
    matched = both[both["abs_diff"] <= 0.01]
    mismatched = both[both["abs_diff"] > 0.01]

    only_items = df[df["item_gmv_total"].notna() & df["payment_total"].isna()]
    only_payments = df[df["item_gmv_total"].isna() & df["payment_total"].notna()]
    neither = df[df["item_gmv_total"].isna() & df["payment_total"].isna()]

    # breakdowns of mismatches
    by_status = mismatched.groupby("order_status").size().sort_values(ascending=False)
    by_payment_type = mismatched.groupby("dominant_payment_type").size().sort_values(ascending=False)
    by_installments = pd.cut(
        mismatched["max_installments"].fillna(0), bins=[-1, 0, 1, 3, 6, 12, 100],
        labels=["0", "1", "2-3", "4-6", "7-12", "13+"]
    ).value_counts().sort_index()

    diff_distribution = {
        "count": int(len(mismatched)),
        "mean_abs_diff": round(float(mismatched["abs_diff"].mean()), 2) if len(mismatched) else None,
        "median_abs_diff": round(float(mismatched["abs_diff"].median()), 2) if len(mismatched) else None,
        "p90_abs_diff": round(float(mismatched["abs_diff"].quantile(0.9)), 2) if len(mismatched) else None,
        "max_abs_diff": round(float(mismatched["abs_diff"].max()), 2) if len(mismatched) else None,
        "mean_rel_diff_pct": round(float(mismatched["rel_diff_pct"].mean()), 2) if len(mismatched) else None,
    }

    largest_mismatches = mismatched.sort_values("abs_diff", ascending=False).head(15)[
        ["order_id", "order_status", "item_gmv_total", "payment_total", "abs_diff",
         "dominant_payment_type", "max_installments"]
    ].to_dict(orient="records")

    # Does payment_total systematically exceed item total (consistent with financing
    # interest being included in payments but not items)?
    signed_diff = both["payment_total"] - both["item_gmv_total"]
    pct_payment_gt_items = round(float((signed_diff > 0.01).mean()) * 100, 2)
    pct_payment_lt_items = round(float((signed_diff < -0.01).mean()) * 100, 2)

    result = {
        "definitions": {
            "A_item_price_total": "SUM(order_items.price) per order -- excludes freight",
            "A_item_gmv_total": "SUM(order_items.price) + SUM(order_items.freight_value) per order",
            "B_payment_total": "SUM(order_payments.payment_value) per order",
        },
        "coverage": {
            "orders_with_both_items_and_payments": int(len(both)),
            "orders_with_items_only_no_payment": int(len(only_items)),
            "orders_with_payment_only_no_items": int(len(only_payments)),
            "orders_with_neither": int(len(neither)),
        },
        "reconciliation_item_gmv_vs_payment_total": {
            "matched_within_1_cent": int(len(matched)),
            "matched_pct": round(len(matched) / len(both) * 100, 4) if len(both) else None,
            "mismatched_count": int(len(mismatched)),
            "mismatched_pct": round(len(mismatched) / len(both) * 100, 4) if len(both) else None,
            "pct_of_mismatches_where_payment_exceeds_items": pct_payment_gt_items,
            "pct_of_mismatches_where_payment_is_less_than_items": pct_payment_lt_items,
        },
        "diff_distribution": diff_distribution,
        "mismatch_breakdown_by_order_status": by_status.to_dict(),
        "mismatch_breakdown_by_dominant_payment_type": by_payment_type.to_dict(),
        "mismatch_breakdown_by_max_installments_bucket": {str(k): int(v) for k, v in by_installments.items()},
        "largest_15_mismatches": largest_mismatches,
        "interpretation": (
            f"{pct_payment_gt_items}% of mismatches have payment_total > item_gmv_total (consistent "
            "with financing/installment interest being captured in order_payments but not in "
            "order_items.price, since order_items has no interest field). This directionality supports "
            "treating order_items.price as the cleaner, decomposable 'what was actually sold' figure, "
            "and order_payments.payment_value as 'what was actually collected, including financing "
            "cost' -- two legitimate but different numbers, not a defect in either."
        ),
    }

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / "step2_revenue_reconciliation.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(json.dumps({k: v for k, v in result.items() if k != "monthly_metrics"}, indent=2, default=str)[:4000])
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
