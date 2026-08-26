"""Review multiplicity and review aggregation tests (Step 2 §21.3, .7)."""

from __future__ import annotations


def test_fact_reviews_preserves_full_raw_row_count(canonical, raw):
    """fact_reviews must have exactly 1 row per RAW review row -- no deduplication at
    the fact grain (deduplication only happens in agg_order_reviews.latest_review_score,
    which is a separate, explicitly-labeled derived value)."""
    assert len(canonical["fact_reviews"]) == len(raw["order_reviews"]), (
        "fact_reviews row count must equal raw order_reviews row count exactly."
    )


def test_fact_reviews_preserves_multi_review_orders(canonical):
    fr = canonical["fact_reviews"]
    reviews_per_order = fr.groupby("order_id").size()
    n_multi = (reviews_per_order > 1).sum()
    assert n_multi == 547, (
        f"Expected 547 orders with >1 review row preserved in fact_reviews (per Step 1 audit), found {n_multi}."
    )


def test_agg_order_reviews_avg_score_is_true_average_not_a_single_row(canonical, raw):
    """Verify avg_review_score in agg_order_reviews is a genuine mean over ALL of an
    order's reviews (not accidentally just the latest or first row's score) -- this is
    the distinction between deduplication and aggregation this task requires."""
    reviews = raw["order_reviews"]
    multi_order_ids = reviews.groupby("order_id").size()
    multi_order_ids = multi_order_ids[multi_order_ids > 1].index

    raw_avg = reviews[reviews["order_id"].isin(multi_order_ids)].groupby("order_id")["review_score"].mean().round(4)
    canonical_avg = canonical["agg_order_reviews"].set_index("order_id").loc[multi_order_ids, "avg_review_score"]

    diff = (raw_avg - canonical_avg).abs()
    assert (diff < 0.0001).all(), (
        f"{(diff >= 0.0001).sum()} multi-review orders have avg_review_score that is not a true mean "
        f"of all their review rows -- aggregation logic may have collapsed to a single row instead."
    )


def test_agg_order_reviews_latest_score_matches_latest_answer_timestamp(canonical, raw):
    reviews = raw["order_reviews"]
    expected_latest = (
        reviews.sort_values("review_answer_timestamp")
        .drop_duplicates(subset="order_id", keep="last")
        .set_index("order_id")["review_score"]
    )
    canonical_latest = canonical["agg_order_reviews"].set_index("order_id")["latest_review_score"]
    mismatches = (expected_latest.reindex(canonical_latest.index) != canonical_latest).sum()
    assert mismatches == 0, f"{mismatches} orders have latest_review_score not matching the latest-by-answer-timestamp rule"


def test_agg_order_reviews_count_matches_raw(canonical, raw):
    raw_count = raw["order_reviews"].groupby("order_id").size()
    canonical_count = canonical["agg_order_reviews"].set_index("order_id")["review_count"]
    diff = (raw_count.reindex(canonical_count.index) - canonical_count).abs()
    assert (diff == 0).all(), f"{(diff != 0).sum()} orders have review_count mismatch vs raw"


def test_agg_order_reviews_min_max_bound_avg(canonical):
    agg = canonical["agg_order_reviews"]
    violations = agg[(agg["avg_review_score"] < agg["min_review_score"] - 1e-6) |
                      (agg["avg_review_score"] > agg["max_review_score"] + 1e-6)]
    assert len(violations) == 0, (
        f"{len(violations)} orders have avg_review_score outside [min_review_score, max_review_score]"
    )


def test_has_review_text_flag_correct(canonical, raw):
    reviews = raw["order_reviews"]
    text_nonempty = reviews["review_comment_message"].fillna("").str.strip() != ""
    expected = reviews.assign(has_text=text_nonempty).groupby("order_id")["has_text"].any()
    canonical_flag = canonical["agg_order_reviews"].set_index("order_id")["has_review_text"]
    mismatches = (expected.reindex(canonical_flag.index) != canonical_flag).sum()
    assert mismatches == 0, f"{mismatches} orders have has_review_text inconsistent with raw text presence"


def test_no_orders_without_reviews_present_in_agg_order_reviews(canonical):
    fo = canonical["fact_orders"]
    agg = canonical["agg_order_reviews"]
    no_review_ids = set(fo.loc[~fo["has_review"], "order_id"])
    leaked = no_review_ids & set(agg["order_id"])
    assert len(leaked) == 0, f"{len(leaked)} no-review orders incorrectly present in agg_order_reviews"
