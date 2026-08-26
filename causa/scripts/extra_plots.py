"""extra_plots.py — supplementary plots for the anomaly/contradiction/sparse-history
findings that the main scripts compute but don't visualize. Reads only from
data/raw/olist/ and reports/*.json (already-computed, not re-derived here)."""

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


def plot_delivery_vs_review():
    monthly = pd.read_csv(REPORTS_DIR / "kpi_timeseries_monthly.csv", index_col=0, parse_dates=True)
    monthly = monthly[monthly["orders"] >= 200]
    fig, ax1 = plt.subplots(figsize=(12, 5))
    ax2 = ax1.twinx()
    ax1.plot(monthly.index, monthly["avg_delivery_days"], color="tab:red", marker="o", markersize=3, label="avg delivery days")
    ax2.plot(monthly.index, monthly["avg_review_score"], color="tab:blue", marker="s", markersize=3, label="avg review score")
    ax1.set_ylabel("avg delivery days", color="tab:red")
    ax2.set_ylabel("avg review score", color="tab:blue")
    ax1.axvspan(pd.Timestamp("2017-11-01"), pd.Timestamp("2017-12-01"), color="gray", alpha=0.15)
    ax1.set_title("Delivery time vs review score by month (shaded = Nov 2017 spike)")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "delivery_vs_review_score.png", dpi=130)
    plt.close(fig)


def plot_sparse_history():
    items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")
    per_product = items.groupby("product_id").size()
    per_seller = items.groupby("seller_id").size()

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].hist(per_product.clip(upper=50), bins=50)
    axes[0].axvline(30, color="red", linestyle="--", label="30-obs threshold")
    axes[0].set_title(f"Order-item count per product (n={len(per_product):,}, clipped at 50)")
    axes[0].legend()
    axes[1].hist(per_seller.clip(upper=200), bins=50)
    axes[1].axvline(30, color="red", linestyle="--", label="30-obs threshold")
    axes[1].set_title(f"Order-item count per seller (n={len(per_seller):,}, clipped at 200)")
    axes[1].legend()
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "sparse_history_distributions.png", dpi=130)
    plt.close(fig)


def plot_nov_spike_breakdown():
    with open(REPORTS_DIR / "join_driver_anomaly_summary.json") as f:
        d = json.load(f)
    cats = d["nov_2017_spike_breakdown"]["top_10_categories_by_absolute_item_growth_nov_vs_oct"]
    fig, ax = plt.subplots(figsize=(9, 5))
    names = list(cats.keys())
    vals = list(cats.values())
    ax.barh(names[::-1], vals[::-1])
    ax.set_title("Nov 2017 vs Oct 2017: item-count growth by category (top 10)")
    ax.set_xlabel("absolute increase in order-item count")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "nov_2017_spike_category_growth.png", dpi=130)
    plt.close(fig)

    pvm = d["pvm_decomposition_oct_to_nov_2017"]
    fig, ax = plt.subplots(figsize=(7, 5))
    components = ["volume_effect", "price_effect", "mix_effect"]
    values = [pvm[c] for c in components]
    colors = ["tab:green" if v >= 0 else "tab:red" for v in values]
    ax.bar(components, values, color=colors)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_title(f"PVM bridge: Oct->Nov 2017 revenue change (Δ={pvm['delta_revenue']:,.0f} BRL)")
    ax.set_ylabel("BRL contribution")
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "pvm_bridge_oct_nov_2017.png", dpi=130)
    plt.close(fig)


def plot_review_score_distribution():
    reviews = pd.read_csv(DATA_DIR / "olist_order_reviews_dataset.csv")
    fig, ax = plt.subplots(figsize=(6, 4.5))
    counts = reviews["review_score"].value_counts().sort_index()
    ax.bar(counts.index.astype(str), counts.values)
    ax.set_title("Review score distribution (n={:,})".format(len(reviews)))
    for i, v in zip(counts.index, counts.values):
        ax.text(str(i), v, f"{v:,}", ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(PLOTS_DIR / "review_score_distribution.png", dpi=130)
    plt.close(fig)


def main():
    plot_delivery_vs_review()
    plot_sparse_history()
    plot_nov_spike_breakdown()
    plot_review_score_distribution()
    print("Extra plots written to", PLOTS_DIR)


if __name__ == "__main__":
    main()
