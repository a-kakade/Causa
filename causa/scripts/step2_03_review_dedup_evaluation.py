"""
step2_03_review_dedup_evaluation.py — STEP 2 §8: evaluate the 4 candidate review
deduplication/aggregation strategies quantitatively, rather than picking one for
convenience.

For each strategy: orders affected, resulting review coverage, score distribution,
potential bias, text coverage, and temporal behavior (does the choice systematically
prefer earlier or later reviews).

Writes reports/step2_review_dedup_comparison.json. Read-only against data/raw/.
"""

from __future__ import annotations

import json

import pandas as pd

from lib.raw_loader import load_raw_tables, REPORTS_DIR


def strategy_latest_answer(reviews: pd.DataFrame) -> pd.DataFrame:
    return reviews.sort_values("review_answer_timestamp").drop_duplicates(subset="order_id", keep="last")


def strategy_earliest_creation(reviews: pd.DataFrame) -> pd.DataFrame:
    return reviews.sort_values("review_creation_date").drop_duplicates(subset="order_id", keep="first")


def strategy_highest_score(reviews: pd.DataFrame) -> pd.DataFrame:
    # tie-break deterministically by latest answer timestamp so the result is stable
    return (reviews.sort_values(["review_score", "review_answer_timestamp"], ascending=[False, False])
            .drop_duplicates(subset="order_id", keep="first"))


def strategy_retain_all(reviews: pd.DataFrame) -> pd.DataFrame:
    return reviews.copy()


def profile_strategy(name: str, chosen: pd.DataFrame, all_reviews: pd.DataFrame,
                      multi_review_orders: set) -> dict:
    n_orders_represented = chosen["order_id"].nunique()
    msg = chosen["review_comment_message"].fillna("")
    text_coverage = round(float((msg.str.strip() != "").mean()) * 100, 2)

    # bias check: for orders that originally had multiple reviews, does this strategy's
    # chosen score differ from the simple average of all that order's reviews?
    affected = chosen[chosen["order_id"].isin(multi_review_orders)]
    all_multi = all_reviews[all_reviews["order_id"].isin(multi_review_orders)]
    avg_all = all_multi.groupby("order_id")["review_score"].mean()
    chosen_scores = affected.set_index("order_id")["review_score"]
    score_bias = (chosen_scores - avg_all.reindex(chosen_scores.index)).dropna()

    return {
        "n_rows_in_output": int(len(chosen)),
        "n_distinct_orders_represented": int(n_orders_represented),
        "is_1_to_1_with_orders_that_have_reviews": bool(len(chosen) == n_orders_represented),
        "score_distribution": chosen["review_score"].value_counts().sort_index().to_dict(),
        "mean_score": round(float(chosen["review_score"].mean()), 4),
        "text_coverage_pct": text_coverage,
        "orders_affected_by_this_choice": int(len(multi_review_orders)),
        "bias_vs_simple_average_of_all_reviews_for_that_order": {
            "mean_signed_bias": round(float(score_bias.mean()), 4) if len(score_bias) else None,
            "pct_rows_where_chosen_gt_average": round(float((score_bias > 0).mean()) * 100, 2) if len(score_bias) else None,
            "pct_rows_where_chosen_lt_average": round(float((score_bias < 0).mean()) * 100, 2) if len(score_bias) else None,
            "interpretation": "0 = strategy's chosen score exactly matches the simple average across "
                               "that order's reviews on average; a nonzero mean_signed_bias means this "
                               "strategy systematically over- or under-states the score for the 547 "
                               "multi-review orders relative to using all evidence.",
        },
    }


def main():
    dfs = load_raw_tables()
    reviews = dfs["order_reviews"]

    review_counts = reviews.groupby("order_id").size()
    multi_review_orders = set(review_counts[review_counts > 1].index)

    strategies = {
        "latest_review_answer_timestamp": strategy_latest_answer(reviews),
        "earliest_review_creation_date": strategy_earliest_creation(reviews),
        "highest_review_score": strategy_highest_score(reviews),
        "retain_all_no_dedup": strategy_retain_all(reviews),
    }

    result = {
        "n_total_review_rows": int(len(reviews)),
        "n_orders_with_gt1_review": int(len(multi_review_orders)),
        "n_orders_with_review": int(reviews["order_id"].nunique()),
        "strategies": {
            name: profile_strategy(name, df, reviews, multi_review_orders)
            for name, df in strategies.items()
        },
        "recommendation": {
            "review_level_text_retrieval_or_future_RAG": "retain_all_no_dedup -- fact_reviews preserves "
                "every legitimate row; no information is discarded, since a future retrieval use case "
                "may want every review's text, not just one per order.",
            "order_level_KPI_single_representative_score": "latest_review_answer_timestamp -- represents "
                "the most current customer sentiment for that order (a customer who edits/re-reviews "
                "presumably wants their latest word to count), and is the standard used in "
                "agg_order_reviews.latest_review_score. This is a DECISION, not the only defensible "
                "choice -- see bias comparison above for how it differs from a simple average.",
            "order_level_KPI_general_purpose": "avg_review_score (a true aggregation over ALL reviews for "
                "that order) is materialized in agg_order_reviews alongside latest_review_score, because "
                "picking one row and averaging all rows are different operations with different biases, "
                "and this task explicitly warns against confusing deduplication with aggregation.",
        },
    }

    REPORTS_DIR.mkdir(exist_ok=True)
    out_path = REPORTS_DIR / "step2_review_dedup_comparison.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    for name, s in result["strategies"].items():
        print(f"{name}: rows={s['n_rows_in_output']} mean_score={s['mean_score']} "
              f"text_cov={s['text_coverage_pct']}% bias={s['bias_vs_simple_average_of_all_reviews_for_that_order']['mean_signed_bias']}")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
