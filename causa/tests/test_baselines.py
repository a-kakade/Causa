"""Step 3C: tests for src/anomaly/baseline.py -- the baseline engine (§1) and
the historical sufficiency / fallback ladder (§2)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from anomaly.baseline import (  # noqa: E402
    BaselineConfig, compute_baselines, compute_ewma, compute_previous_period, compute_rolling_mean,
    compute_rolling_median, compute_rolling_std, compute_seasonal, confidence_for_level, select_level,
)
from anomaly.models import BaselineLevel, PeriodObservation  # noqa: E402


def obs(period, value, sample_size=10):
    return PeriodObservation(period=period, value=value, sample_size=sample_size)


# ---------------------------------------------------------------------------
# Individual methods
# ---------------------------------------------------------------------------

def test_previous_period_is_the_last_valid_value():
    hist = [obs("2017-08", 100.0), obs("2017-09", 200.0)]
    assert compute_previous_period(hist) == 200.0


def test_previous_period_skips_trailing_nulls():
    hist = [obs("2017-08", 100.0), obs("2017-09", None)]
    assert compute_previous_period(hist) == 100.0


def test_previous_period_none_when_all_null():
    assert compute_previous_period([obs("2017-08", None)]) is None


def test_rolling_mean_requires_at_least_3_points():
    assert compute_rolling_mean([obs("2017-08", 10.0), obs("2017-09", 20.0)], window=6) is None
    assert compute_rolling_mean([obs("2017-07", 10.0), obs("2017-08", 20.0), obs("2017-09", 30.0)], window=6) == 20.0


def test_rolling_mean_respects_window():
    hist = [obs(f"2017-{m:02d}", float(m)) for m in range(1, 11)]  # 1..10
    # window=3 -> last 3 values: 8, 9, 10 -> mean 9
    assert compute_rolling_mean(hist, window=3) == 9.0


def test_rolling_median_odd_and_even_counts():
    hist = [obs("2017-01", 1.0), obs("2017-02", 2.0), obs("2017-03", 3.0)]
    assert compute_rolling_median(hist, window=6) == 2.0
    hist.append(obs("2017-04", 4.0))
    assert compute_rolling_median(hist, window=6) == 2.5


def test_rolling_std_requires_at_least_3_points_and_is_correct():
    assert compute_rolling_std([obs("2017-01", 1.0), obs("2017-02", 2.0)], window=6) is None
    hist = [obs("2017-01", 2.0), obs("2017-02", 4.0), obs("2017-03", 4.0), obs("2017-04", 4.0), obs("2017-05", 5.0), obs("2017-06", 5.0), obs("2017-07", 7.0), obs("2017-08", 9.0)]
    std = compute_rolling_std(hist, window=8)
    assert std is not None and std > 0


def test_ewma_needs_at_least_2_points():
    assert compute_ewma([obs("2017-01", 5.0)], span=3) is None
    val = compute_ewma([obs("2017-01", 10.0), obs("2017-02", 20.0)], span=3)
    assert val is not None and 10.0 < val < 20.0


def test_seasonal_averages_matching_calendar_months_across_prior_years():
    # two prior Novembers (2016, 2017) in the history -- exactly meets a
    # cycles_required=2 bar for evaluating 2018-11.
    hist = [obs("2016-11", 500.0), obs("2017-01", 100.0), obs("2017-11", 600.0)]
    assert compute_seasonal(hist, "2018-11", cycles_required=2) == (500.0 + 600.0) / 2


def test_seasonal_none_with_only_1_prior_cycle():
    hist = [obs("2016-11", 500.0), obs("2017-01", 100.0)]
    assert compute_seasonal(hist, "2018-11", cycles_required=2) is None


def test_seasonal_none_for_malformed_period_label():
    hist = [obs("not-a-period", 500.0)]
    assert compute_seasonal(hist, "2018-11", cycles_required=1) is None


# ---------------------------------------------------------------------------
# compute_baselines -- primary method selection priority
# ---------------------------------------------------------------------------

def test_primary_prefers_seasonal_when_available():
    hist = [obs(f"{y}-11", 2000.0) for y in (2015, 2016, 2017)] + [obs(f"2017-{m:02d}", 1000.0) for m in range(1, 11)]
    outcome = compute_baselines(hist, "2018-11", BaselineConfig())
    assert outcome.primary_method == "seasonal"
    assert outcome.primary_value == 2000.0


def test_primary_falls_back_to_rolling_mean_without_seasonal():
    hist = [obs(f"2017-{m:02d}", 100.0 + m) for m in range(1, 10)]
    outcome = compute_baselines(hist, "2017-10", BaselineConfig())
    assert outcome.primary_method == "rolling_mean"


def test_primary_falls_back_to_ewma_with_only_2_points():
    hist = [obs("2017-08", 100.0), obs("2017-09", 110.0)]
    outcome = compute_baselines(hist, "2017-10", BaselineConfig())
    assert outcome.primary_method == "ewma"


def test_primary_falls_back_to_previous_period_with_only_1_point():
    hist = [obs("2017-09", 100.0)]
    outcome = compute_baselines(hist, "2017-10", BaselineConfig())
    assert outcome.primary_method == "previous_period"
    assert outcome.primary_value == 100.0


def test_primary_none_with_no_history_at_all():
    outcome = compute_baselines([], "2017-10", BaselineConfig())
    assert outcome.primary_method == "none"
    assert outcome.primary_value is None


def test_all_methods_are_exposed_for_transparency():
    hist = [obs(f"2017-{m:02d}", 100.0 + m) for m in range(1, 10)]
    outcome = compute_baselines(hist, "2017-10", BaselineConfig())
    assert set(outcome.all_methods) == {"previous_period", "rolling_mean", "ewma", "seasonal"}


# ---------------------------------------------------------------------------
# select_level -- the fallback ladder (§2)
# ---------------------------------------------------------------------------

def test_entity_level_selected_when_sufficient():
    entity = BaselineLevel("entity", "product:abc", [obs(f"2017-{m:02d}", 100.0, sample_size=50) for m in range(1, 10)])
    category = BaselineLevel("category", "category:xyz", [obs(f"2017-{m:02d}", 9000.0, sample_size=500) for m in range(1, 10)])
    sel = select_level([entity, category], contract_minimum_observations=30)
    assert sel.level.level == "entity"
    assert sel.fallback_reason is None
    assert not sel.insufficient_even_at_chosen_level


def test_falls_back_to_category_when_entity_too_few_periods():
    entity = BaselineLevel("entity", "product:sparse", [obs("2018-01", 50.0, sample_size=1)])
    category = BaselineLevel("category", "category:xyz", [obs(f"2017-{m:02d}", 9000.0, sample_size=500) for m in range(1, 10)])
    sel = select_level([entity, category], contract_minimum_observations=30)
    assert sel.level.level == "category"
    assert sel.fallback_reason == "entity_history_insufficient"


def test_falls_back_to_category_when_entity_total_observations_below_contract_minimum():
    # entity has enough PERIODS (3) but each period only had 1 underlying row --
    # total 3 observations, below a minimum_observations=30 contract requirement.
    entity = BaselineLevel("entity", "product:sparse",
                            [obs(f"2018-{m:02d}", 50.0, sample_size=1) for m in range(1, 4)])
    category = BaselineLevel("category", "category:xyz", [obs(f"2017-{m:02d}", 9000.0, sample_size=500) for m in range(1, 10)])
    sel = select_level([entity, category], contract_minimum_observations=30)
    assert sel.level.level == "category"
    assert sel.fallback_reason == "entity_history_insufficient"


def test_multi_hop_fallback_reason_names_every_skipped_level():
    entity = BaselineLevel("entity", "product:sparse", [obs("2018-01", 50.0, sample_size=1)])
    category = BaselineLevel("category", "category:sparse", [obs("2018-01", 60.0, sample_size=2)])
    regional = BaselineLevel("regional", "region:sparse", [obs("2018-01", 70.0, sample_size=3)])
    global_ = BaselineLevel("global", "all", [obs(f"2017-{m:02d}", 9000.0, sample_size=500) for m in range(1, 10)])
    sel = select_level([entity, category, regional, global_], contract_minimum_observations=30)
    assert sel.level.level == "global"
    assert sel.fallback_reason == "entity, category, regional_history_insufficient"


def test_insufficient_even_at_global_flagged_not_fabricated():
    entity = BaselineLevel("entity", "product:sparse", [obs("2018-01", 50.0, sample_size=1)])
    global_ = BaselineLevel("global", "all", [obs("2018-01", 9000.0, sample_size=2)])
    sel = select_level([entity, global_], contract_minimum_observations=30)
    assert sel.insufficient_even_at_chosen_level
    assert sel.fallback_reason == "all_levels_insufficient"
    assert sel.level.level == "global"  # returns the last rung, but flagged -- caller must not trust it


def test_select_level_requires_at_least_one_level():
    with pytest.raises(ValueError):
        select_level([], contract_minimum_observations=30)


def test_select_level_with_no_contract_minimum_only_checks_period_count():
    entity = BaselineLevel("entity", "product:x", [obs(f"2018-{m:02d}", 50.0, sample_size=1) for m in range(1, 4)])
    sel = select_level([entity], contract_minimum_observations=None)
    assert sel.level.level == "entity"
    assert not sel.insufficient_even_at_chosen_level


# ---------------------------------------------------------------------------
# confidence_for_level
# ---------------------------------------------------------------------------

def test_confidence_high_for_first_level_with_healthy_history():
    assert confidence_for_level("global", n_periods=9, is_fallback=False, insufficient=False) == "HIGH"


def test_confidence_medium_for_first_level_with_thin_history():
    assert confidence_for_level("entity", n_periods=3, is_fallback=False, insufficient=False) == "MEDIUM"


def test_confidence_medium_for_fallback_with_healthy_history():
    assert confidence_for_level("category", n_periods=9, is_fallback=True, insufficient=False) == "MEDIUM"


def test_confidence_low_for_fallback_with_thin_history():
    assert confidence_for_level("category", n_periods=3, is_fallback=True, insufficient=False) == "LOW"


def test_confidence_none_when_insufficient():
    assert confidence_for_level("global", n_periods=1, is_fallback=True, insufficient=True) == "NONE"
