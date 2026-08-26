"""Step 3D: tests for src/drivers/pvm.py -- the Volume/Price/Mix bridge
(task §1/§2), using synthetic order-item-grain frames (no canonical data
dependency -- fast, deterministic). Real-data reproduction of the exact
November 2017 numbers lives in tests/test_driver_engine.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from drivers.pvm import UNCATEGORIZED_LABEL, compute_pvm_bridge  # noqa: E402


def items(rows):
    """rows: list of (category, price) tuples -> one-row-per-unit DataFrame."""
    return pd.DataFrame(rows, columns=["category", "price"])


def test_pvm_reconciles_exactly_on_a_simple_two_category_case():
    old = items([("a", 10.0), ("a", 10.0), ("b", 20.0)])          # 2 units @10 + 1 unit @20 = 40
    new = items([("a", 10.0), ("a", 10.0), ("a", 10.0), ("b", 20.0)])  # +1 unit of a
    bridge = compute_pvm_bridge(old, new)
    assert bridge.revenue_previous == 40.0
    assert bridge.revenue_current == 50.0
    assert abs(bridge.checksum_error) < 1e-9


def test_pvm_pure_volume_growth_no_mix_or_price_shift():
    # doubling every category's quantity at unchanged prices -> price_effect
    # and mix_effect should both be ~0, all of delta_revenue is volume_effect.
    old = items([("a", 10.0)] * 10 + [("b", 20.0)] * 10)
    new = items([("a", 10.0)] * 20 + [("b", 20.0)] * 20)
    bridge = compute_pvm_bridge(old, new)
    delta = bridge.revenue_current - bridge.revenue_previous
    assert abs(bridge.price_effect) < 1e-9
    assert abs(bridge.mix_effect) < 1e-9
    assert abs(bridge.volume_effect - delta) < 1e-6


def test_pvm_pure_price_increase_no_volume_or_mix_change():
    # same quantities in both periods, every category's price goes up 10%
    old = items([("a", 10.0)] * 10 + [("b", 20.0)] * 10)
    new = items([("a", 11.0)] * 10 + [("b", 22.0)] * 10)
    bridge = compute_pvm_bridge(old, new)
    assert abs(bridge.volume_effect) < 1e-9
    assert abs(bridge.mix_effect) < 1e-6
    assert bridge.price_effect > 0


def test_pvm_mix_shift_toward_cheaper_category_can_be_negative():
    # same total quantity (20 units) both periods, but the new period skews
    # heavily toward the cheaper category -- mix_effect should be negative
    # even though total qty and category-level prices are both unchanged.
    old = items([("expensive", 100.0)] * 10 + [("cheap", 10.0)] * 10)
    new = items([("expensive", 100.0)] * 2 + [("cheap", 10.0)] * 18)
    bridge = compute_pvm_bridge(old, new)
    assert bridge.mix_effect < 0


def test_pvm_reconciles_within_tolerance_on_many_synthetic_cases():
    import random
    rng = random.Random(42)
    cats = ["a", "b", "c", "d", "uncategorized"]
    for _ in range(20):
        old_rows = [(rng.choice(cats), round(rng.uniform(5, 500), 2)) for _ in range(rng.randint(5, 200))]
        new_rows = [(rng.choice(cats), round(rng.uniform(5, 500), 2)) for _ in range(rng.randint(5, 200))]
        bridge = compute_pvm_bridge(items(old_rows), items(new_rows))
        assert abs(bridge.checksum_error) < 1e-6


def test_pvm_handles_brand_new_previous_period_of_zero_without_crashing():
    old = items([])
    new = items([("a", 100.0), ("b", 50.0)])
    bridge = compute_pvm_bridge(old, new)
    assert bridge.revenue_previous == 0.0
    assert bridge.revenue_current == 150.0
    assert abs(bridge.checksum_error) < 1e-9
    # No prior baseline at all -> qty_old=0 -> volume_effect is 0 by
    # construction (overall_avg_price_old is 0 when qty_old is 0). Every
    # category is "brand new", so its revenue lands entirely in price_effect
    # (implicit prior price of R$0 -- see pvm.py's documented, validated
    # treatment), leaving mix_effect at 0. No NaN, no infinity, no crash.
    assert bridge.volume_effect == 0.0
    assert bridge.price_effect == 150.0
    assert bridge.mix_effect == 0.0


def test_pvm_handles_discontinued_category_going_to_zero():
    old = items([("a", 100.0), ("b", 50.0)])
    new = items([("a", 100.0)])  # category b disappears entirely
    bridge = compute_pvm_bridge(old, new)
    assert bridge.revenue_current == 100.0
    assert abs(bridge.checksum_error) < 1e-9


def test_pvm_never_drops_a_null_style_uncategorized_category():
    old = items([("a", 100.0), (UNCATEGORIZED_LABEL, 30.0)])
    new = items([("a", 110.0), (UNCATEGORIZED_LABEL, 20.0)])
    bridge = compute_pvm_bridge(old, new)
    # uncategorized revenue (30 -> 20) must still be reflected in the totals
    assert bridge.revenue_previous == 130.0
    assert bridge.revenue_current == 130.0
    assert abs(bridge.checksum_error) < 1e-9


def test_pvm_confidence_low_below_the_row_count_floor():
    old = items([("a", 10.0)])
    new = items([("a", 20.0)])
    bridge = compute_pvm_bridge(old, new)
    assert bridge.confidence == "LOW"


def test_pvm_confidence_high_above_the_row_count_floor():
    old = items([("a", 10.0)] * 40)
    new = items([("a", 20.0)] * 40)
    bridge = compute_pvm_bridge(old, new)
    assert bridge.confidence == "HIGH"
