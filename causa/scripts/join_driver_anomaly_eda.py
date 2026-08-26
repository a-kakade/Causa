"""
join_driver_anomaly_eda.py

1. Demonstrates the fan-out / revenue-multiplication risk of naive joins across
   orders x order_items x order_payments x order_reviews, and shows the correct
   (non-multiplying) aggregation.
2. Runs a real Price x Volume x Mix (PVM) decomposition of the revenue movement
   between two actual periods (Oct 2017 -> Nov 2017, the largest MoM revenue jump
   found by kpi_temporal_eda.py) at the product_category level, to test whether the
   dataset genuinely supports PVM decomposition claims.
3. Cross-tabulates review score and delivery time by month around that same window,
   to test for a genuine structured-vs-unstructured contradiction candidate.
4. Breaks the Nov 2017 spike down by customer state and category to assess whether
   it is broad-based (platform-level) or concentrated (segment-level).

Writes reports/join_driver_anomaly_summary.json
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "raw" / "olist"
REPORTS_DIR = REPO_ROOT / "reports"


def load():
    orders = pd.read_csv(DATA_DIR / "olist_orders_dataset.csv", parse_dates=["order_purchase_timestamp"])
    items = pd.read_csv(DATA_DIR / "olist_order_items_dataset.csv")
    payments = pd.read_csv(DATA_DIR / "olist_order_payments_dataset.csv")
    reviews = pd.read_csv(DATA_DIR / "olist_order_reviews_dataset.csv")
    products = pd.read_csv(DATA_DIR / "olist_products_dataset.csv")
    customers = pd.read_csv(DATA_DIR / "olist_customers_dataset.csv")
    return orders, items, payments, reviews, products, customers


def join_fanout_demo(orders, items, payments, reviews) -> dict:
    """Take a sample of orders with multiple items AND multiple payment rows AND
    multiple reviews, and show what naive vs correct revenue aggregation yields."""
    correct_revenue = float(items["price"].sum())

    naive = orders.merge(items, on="order_id", how="inner") \
                   .merge(payments, on="order_id", how="inner") \
                   .merge(reviews, on="order_id", how="inner")
    naive_revenue_if_summed_price_over_fanned_out_join = float(naive["price"].sum())

    # isolate one concrete multi-item + multi-payment example order to show the mechanism
    n_items_per_order = items.groupby("order_id").size()
    n_payments_per_order = payments.groupby("order_id").size()
    candidates = n_items_per_order[n_items_per_order > 1].index.intersection(
        n_payments_per_order[n_payments_per_order > 1].index
    )
    example = None
    if len(candidates):
        oid = candidates[0]
        n_i = int(n_items_per_order[oid])
        n_p = int(n_payments_per_order[oid])
        true_item_total = float(items[items.order_id == oid]["price"].sum())
        naive_joined_rows = n_i * n_p
        naive_summed_price = true_item_total * n_p  # price row repeated once per payment row
        example = {
            "order_id": oid, "n_order_items": n_i, "n_payment_rows": n_p,
            "true_item_price_total": round(true_item_total, 2),
            "rows_after_naive_items_x_payments_join": naive_joined_rows,
            "price_sum_if_naively_summed_over_that_join": round(naive_summed_price, 2),
            "inflation_factor": n_p,
        }

    return {
        "correct_total_revenue_sum_order_items_price": round(correct_revenue, 2),
        "naive_revenue_if_price_summed_after_joining_items_payments_reviews": round(
            naive_revenue_if_summed_price_over_fanned_out_join, 2
        ),
        "inflation_ratio": round(
            naive_revenue_if_summed_price_over_fanned_out_join / correct_revenue, 4
        ),
        "concrete_example_order": example,
        "rule": "Revenue MUST be aggregated (groupby order_id, sum price) BEFORE joining to "
                "order_payments or order_reviews. Joining first and summing price after multiplies "
                "revenue by the payment/review row count for that order. This is a real, "
                "reproducible risk in this schema, not a hypothetical -- order_payments has up to 29 "
                "rows for a single order_id (installment rows) and order_reviews up to 3.",
    }


def pvm_decomposition(orders, items, products) -> dict:
    """Revenue change Oct 2017 -> Nov 2017 (the largest MoM order/revenue jump in the
    KPI series) decomposed into Price, Volume(quantity), and Mix effects at the
    product_category_name grain, using a standard PVM bridge:
        Delta Revenue = Volume Effect + Price Effect + Mix Effect
        Volume Effect = (Qty_new - Qty_old) * Price_old_wtd_avg   [total qty growth at old avg price]
        Price Effect  = sum_category( Qty_new_cat * (Price_new_cat - Price_old_cat) )
        Mix Effect    = Revenue_new - Revenue_old - Volume Effect - Price Effect  (residual, captures
                        share shift toward higher/lower-priced categories)
    """
    df = items.merge(orders[["order_id", "order_purchase_timestamp", "order_status"]], on="order_id", how="left")
    df = df.merge(products[["product_id", "product_category_name"]], on="product_id", how="left")
    df["product_category_name"] = df["product_category_name"].fillna("uncategorized")
    df["month"] = pd.to_datetime(df["order_purchase_timestamp"]).dt.to_period("M")

    old = df[df["month"] == pd.Period("2017-10")]
    new = df[df["month"] == pd.Period("2017-11")]

    def cat_agg(d):
        g = d.groupby("product_category_name").agg(qty=("order_item_id", "count"), revenue=("price", "sum"))
        g["avg_price"] = g["revenue"] / g["qty"]
        return g

    old_agg, new_agg = cat_agg(old), cat_agg(new)
    all_cats = old_agg.index.union(new_agg.index)
    old_agg = old_agg.reindex(all_cats, fill_value=0)
    new_agg = new_agg.reindex(all_cats, fill_value=0)

    rev_old, rev_new = float(old_agg["revenue"].sum()), float(new_agg["revenue"].sum())
    qty_old, qty_new = float(old_agg["qty"].sum()), float(new_agg["qty"].sum())
    overall_avg_price_old = rev_old / qty_old if qty_old else 0.0

    volume_effect = (qty_new - qty_old) * overall_avg_price_old
    price_effect = float(((new_agg["avg_price"] - old_agg["avg_price"]).fillna(0) * new_agg["qty"]).sum())
    mix_effect = (rev_new - rev_old) - volume_effect - price_effect

    top_category_contributors = (new_agg["revenue"] - old_agg["revenue"]).sort_values(ascending=False)

    return {
        "period_old": "2017-10", "period_new": "2017-11",
        "revenue_old": round(rev_old, 2), "revenue_new": round(rev_new, 2),
        "delta_revenue": round(rev_new - rev_old, 2),
        "qty_old": int(qty_old), "qty_new": int(qty_new),
        "volume_effect": round(volume_effect, 2),
        "price_effect": round(price_effect, 2),
        "mix_effect": round(mix_effect, 2),
        "check_sum_matches_delta": round(volume_effect + price_effect + mix_effect - (rev_new - rev_old), 4),
        "top_10_category_revenue_contributors": {
            k: round(v, 2) for k, v in top_category_contributors.head(10).items()
        },
        "bottom_5_category_revenue_contributors": {
            k: round(v, 2) for k, v in top_category_contributors.tail(5).items()
        },
        "n_categories_involved": int(len(all_cats)),
        "grain_used": "product_category_name (73 raw categories incl. nulls->uncategorized)",
        "caveat": "This decomposition is fully deterministic and reproducible from order_items + products "
                  "alone -- no fabricated data. Category-level avg_price mixes genuinely different SKUs "
                  "within a category, so 'price effect' here is a price-per-category-unit shift, not a "
                  "true like-for-like SKU price change (no promotional-price / list-price field exists in "
                  "this schema to isolate discounting from mix within-category).",
    }


def contradiction_scan(orders, items, reviews) -> dict:
    """Delivery time and review score by month, to check whether they move together or diverge."""
    o = orders.copy()
    o["order_purchase_timestamp"] = pd.to_datetime(o["order_purchase_timestamp"])
    o["order_delivered_customer_date"] = pd.to_datetime(o["order_delivered_customer_date"])
    o["delivery_days"] = (o["order_delivered_customer_date"] - o["order_purchase_timestamp"]).dt.total_seconds() / 86400
    o["month"] = o["order_purchase_timestamp"].dt.to_period("M").astype(str)

    rev = reviews.merge(orders[["order_id", "order_purchase_timestamp"]], on="order_id", how="left")
    rev["month"] = pd.to_datetime(rev["order_purchase_timestamp"]).dt.to_period("M").astype(str)

    delivery_by_month = o.groupby("month")["delivery_days"].mean().round(2)
    review_by_month = rev.groupby("month")["review_score"].mean().round(3)
    order_count_by_month = o.groupby("month").size()

    joined = pd.DataFrame({
        "avg_delivery_days": delivery_by_month, "avg_review_score": review_by_month, "orders": order_count_by_month
    }).dropna()
    joined = joined[joined["orders"] >= 200]  # exclude sparse early months

    corr = joined["avg_delivery_days"].corr(joined["avg_review_score"])

    # focus window around the Nov 2017 spike
    window = joined.loc["2017-09":"2018-02"] if all(m in joined.index for m in ["2017-09", "2018-02"]) else joined

    return {
        "correlation_delivery_days_vs_review_score_across_months": round(float(corr), 3),
        "interpretation": "Negative correlation expected (slower delivery -> lower score) if delivery is a "
                           "real driver of satisfaction; a weak/positive correlation would itself be a "
                           "noteworthy contradiction worth investigating via review text.",
        "window_around_nov_2017_spike": window.to_dict(orient="index"),
    }


def spike_breakdown(orders, items, customers, products) -> dict:
    """Nov 2017 order spike: is it broad-based across states/categories, or concentrated?"""
    o = orders.copy()
    o["order_purchase_timestamp"] = pd.to_datetime(o["order_purchase_timestamp"])
    o["month"] = o["order_purchase_timestamp"].dt.to_period("M")

    nov = o[o["month"] == pd.Period("2017-11")]
    oct_ = o[o["month"] == pd.Period("2017-10")]

    nov_c = nov.merge(customers[["customer_id", "customer_state"]], on="customer_id", how="left")
    oct_c = oct_.merge(customers[["customer_id", "customer_state"]], on="customer_id", how="left")

    by_state_nov = nov_c["customer_state"].value_counts()
    by_state_oct = oct_c["customer_state"].value_counts()
    state_growth = ((by_state_nov - by_state_oct.reindex(by_state_nov.index, fill_value=0))
                     / by_state_oct.reindex(by_state_nov.index, fill_value=1) * 100).round(1)

    items_nov = items.merge(nov[["order_id"]], on="order_id", how="inner").merge(
        products[["product_id", "product_category_name"]], on="product_id", how="left")
    items_oct = items.merge(oct_[["order_id"]], on="order_id", how="inner").merge(
        products[["product_id", "product_category_name"]], on="product_id", how="left")

    cat_nov = items_nov["product_category_name"].value_counts()
    cat_oct = items_oct["product_category_name"].value_counts()
    cat_growth_abs = (cat_nov - cat_oct.reindex(cat_nov.index, fill_value=0)).sort_values(ascending=False)

    return {
        "n_orders_oct_2017": int(len(oct_)), "n_orders_nov_2017": int(len(nov)),
        "n_states_with_orders_oct": int((by_state_oct > 0).sum()),
        "n_states_with_orders_nov": int((by_state_nov > 0).sum()),
        "top_10_states_by_order_count_nov": by_state_nov.head(10).to_dict(),
        "top_10_categories_by_absolute_item_growth_nov_vs_oct": cat_growth_abs.head(10).to_dict(),
        "conclusion": "growth pattern computed directly from the data -- see whether growth is spread "
                      "across most states/categories (broad platform-level demand event, e.g. Black Friday) "
                      "or concentrated in a handful (segment-specific event).",
    }


def main():
    orders, items, payments, reviews, products, customers = load()

    fanout = join_fanout_demo(orders, items, payments, reviews)
    pvm = pvm_decomposition(orders, items, products)
    contradiction = contradiction_scan(orders, items, reviews)
    spike = spike_breakdown(orders, items, customers, products)

    summary = {
        "join_fanout_demo": fanout,
        "pvm_decomposition_oct_to_nov_2017": pvm,
        "delivery_vs_review_contradiction_scan": contradiction,
        "nov_2017_spike_breakdown": spike,
    }
    with open(REPORTS_DIR / "join_driver_anomaly_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
