"""Step 3D: tests for src/drivers/contribution.py and src/drivers/ranking.py --
segment-level contribution decomposition (task §4/5/6), zero/new/discontinued
entities (§9), sparse-entity metadata (§10), and deterministic ranking (§11).
Synthetic frames throughout -- fast, no canonical-data dependency. Real-data
category/seller/state reconciliation lives in tests/test_driver_engine.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from drivers.contribution import compute_segment_contributions, confidence_for  # noqa: E402
from drivers.ranking import rank_dimensions_by_contribution, rank_segment_contributions, top_n  # noqa: E402


def frame(rows):
    """rows: list of (key, price) -> one-row-per-unit DataFrame."""
    return pd.DataFrame(rows, columns=["key", "price"])


# ---------------------------------------------------------------------------
# Reconciliation -- a segment's contributions must sum to the total change
# ---------------------------------------------------------------------------

def test_segment_contributions_sum_to_total_change():
    old = frame([("A", 10.0), ("A", 10.0), ("B", 5.0), ("C", 100.0)])
    new = frame([("A", 15.0), ("B", 5.0), ("B", 5.0), ("D", 40.0)])
    total_change = new["price"].sum() - old["price"].sum()
    contributions = compute_segment_contributions(old, new, "key", "test_segment", total_change)
    assert abs(sum(c.absolute_change for c in contributions) - total_change) < 1e-9


def test_segment_contributions_reconcile_with_many_random_frames():
    import random
    rng = random.Random(7)
    for _ in range(15):
        keys = ["A", "B", "C", "D", "E"]
        old_rows = [(rng.choice(keys), round(rng.uniform(1, 200), 2)) for _ in range(rng.randint(3, 100))]
        new_rows = [(rng.choice(keys), round(rng.uniform(1, 200), 2)) for _ in range(rng.randint(3, 100))]
        old, new = frame(old_rows), frame(new_rows)
        total_change = new["price"].sum() - old["price"].sum()
        contributions = compute_segment_contributions(old, new, "key", "test_segment", total_change)
        assert abs(sum(c.absolute_change for c in contributions) - total_change) < 1e-6


# ---------------------------------------------------------------------------
# NULL / missing key handling -- never dropped (task §4)
# ---------------------------------------------------------------------------

def test_missing_key_sentinel_is_never_dropped():
    # caller is responsible for normalizing NaN -> a sentinel label before
    # calling compute_segment_contributions -- verify that sentinel survives
    # through untouched, contributing its own row like any other key.
    old = frame([("A", 10.0), ("uncategorized", 5.0)])
    new = frame([("A", 12.0), ("uncategorized", 5.0), ("uncategorized", 5.0)])
    total_change = new["price"].sum() - old["price"].sum()
    contributions = compute_segment_contributions(old, new, "key", "product_category", total_change)
    values = {c.segment_value: c for c in contributions}
    assert "uncategorized" in values
    assert values["uncategorized"].absolute_change == 5.0
    assert abs(sum(c.absolute_change for c in contributions) - total_change) < 1e-9


# ---------------------------------------------------------------------------
# Zero / new / discontinued entities (task §9)
# ---------------------------------------------------------------------------

def test_zero_to_positive_entity_has_no_percentage_change_not_infinity():
    old = frame([("existing", 50.0)])
    new = frame([("existing", 55.0), ("brand_new", 30.0)])
    total_change = new["price"].sum() - old["price"].sum()
    contributions = {c.segment_value: c for c in compute_segment_contributions(old, new, "key", "seller", total_change)}
    bn = contributions["brand_new"]
    assert bn.previous_value == 0.0
    assert bn.current_value == 30.0
    assert bn.percentage_change is None
    assert bn.absolute_change == 30.0


def test_positive_to_zero_entity_is_a_well_defined_negative_100_pct():
    old = frame([("existing", 50.0), ("discontinued", 40.0)])
    new = frame([("existing", 55.0)])
    total_change = new["price"].sum() - old["price"].sum()
    contributions = {c.segment_value: c for c in compute_segment_contributions(old, new, "key", "seller", total_change)}
    disc = contributions["discontinued"]
    assert disc.current_value == 0.0
    assert disc.absolute_change == -40.0
    assert disc.percentage_change == pytest.approx(-100.0)
    assert disc.percentage_change != float("inf") and disc.percentage_change != float("-inf")


def test_no_contribution_ever_produces_infinity_or_nan():
    import math
    old = frame([])
    new = frame([("only_new", 100.0)])
    total_change = 100.0
    contributions = compute_segment_contributions(old, new, "key", "seller", total_change)
    for c in contributions:
        for v in (c.previous_value, c.current_value, c.absolute_change):
            assert math.isfinite(v)
        if c.percentage_change is not None:
            assert math.isfinite(c.percentage_change)
        if c.share_of_total_movement is not None:
            assert math.isfinite(c.share_of_total_movement)


# ---------------------------------------------------------------------------
# Sparse entity metadata (task §10) -- contribution != statistical confidence
# ---------------------------------------------------------------------------

def test_confidence_low_for_thin_history_and_sample_regardless_of_contribution_size():
    old = frame([("tiny_seller", 100.0)])
    new = frame([("tiny_seller", 500.0)])   # +400%, huge percentage, tiny sample
    total_change = 400.0
    contributions = compute_segment_contributions(old, new, "key", "seller", total_change,
                                                    history_periods_by_key={"tiny_seller": 1})
    c = contributions[0]
    assert c.percentage_change == pytest.approx(400.0)
    assert c.confidence == "LOW"
    assert c.history_periods == 1


def test_confidence_high_for_ample_history_and_sample():
    old_rows = [("big_seller", 10.0)] * 40
    new_rows = [("big_seller", 11.0)] * 40
    total_change = sum(p for _, p in new_rows) - sum(p for _, p in old_rows)
    contributions = compute_segment_contributions(frame(old_rows), frame(new_rows), "key", "seller", total_change,
                                                    history_periods_by_key={"big_seller": 12})
    assert contributions[0].confidence == "HIGH"


def test_confidence_for_helper_bands():
    assert confidence_for(None, 1) == "LOW"
    assert confidence_for(1, 2) == "LOW"
    assert confidence_for(6, 30) == "HIGH"
    assert confidence_for(2, 0) == "MEDIUM"
    assert confidence_for(0, 5) == "MEDIUM"


# ---------------------------------------------------------------------------
# Ranking (task §11) -- absolute contribution, never percentage alone
# ---------------------------------------------------------------------------

def test_ranking_uses_absolute_contribution_not_percentage():
    old = frame([("seller_a", 1_000_000.0), ("seller_b", 100.0)])
    new = frame([("seller_a", 1_080_000.0), ("seller_b", 400.0)])  # a: +80K/+8%, b: +300/+300%
    total_change = new["price"].sum() - old["price"].sum()
    contributions = compute_segment_contributions(old, new, "key", "seller", total_change)
    ranked = rank_segment_contributions(contributions)
    assert ranked[0].segment_value == "seller_a"
    assert ranked[0].rank == 1
    assert ranked[1].segment_value == "seller_b"
    assert ranked[1].rank == 2


def test_top_n_returns_exactly_n_highest_absolute_contributors():
    rows_old = [(f"s{i}", 100.0) for i in range(20)]
    rows_new = [(f"s{i}", 100.0 + i * 10) for i in range(20)]  # s19 grows the most
    total_change = sum(p for _, p in rows_new) - sum(p for _, p in rows_old)
    contributions = compute_segment_contributions(frame(rows_old), frame(rows_new), "key", "seller", total_change)
    top5 = top_n(contributions, 5)
    assert len(top5) == 5
    assert top5[0].segment_value == "s19"
    assert [c.rank for c in top5] == [1, 2, 3, 4, 5]


def test_rank_dimensions_by_contribution_orders_by_max_absolute_contribution():
    cat = compute_segment_contributions(
        frame([("x", 10.0)]), frame([("x", 20.0)]), "key", "product_category", 10.0)
    seller = compute_segment_contributions(
        frame([("y", 10.0)]), frame([("y", 1000.0)]), "key", "seller", 990.0)
    summary = rank_dimensions_by_contribution({"product_category": cat, "seller": seller})
    assert summary[0]["dimension"] == "seller"
    assert summary[0]["max_absolute_contribution"] == 990.0
