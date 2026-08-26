"""Step 3C: tests for src/anomaly/materiality.py -- tiering, business impact
(§5), persistence (§6), and the decision model (§8/§9/§13)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from anomaly.materiality import (  # noqa: E402
    BaselineSignalSet, TIER_CRITICAL, TIER_MATERIAL, TIER_NORMAL, TIER_WATCH,
    classify_business_impact_tier, classify_magnitude_tier, classify_persistence,
    classify_statistical_tier, combine_tiers, compute_business_impact, decide,
)
from anomaly.models import (  # noqa: E402
    PERSISTENCE_ONE_OFF, PERSISTENCE_PERSISTENT, PERSISTENCE_REVERSING, PERSISTENCE_TRENDING, PERSISTENCE_UNKNOWN,
    VERDICT_BASELINE_DISAGREEMENT, VERDICT_CRITICAL, VERDICT_MATERIAL, VERDICT_NORMAL, VERDICT_WATCH,
    PeriodObservation,
)


# ---------------------------------------------------------------------------
# Tiering
# ---------------------------------------------------------------------------

def test_magnitude_tier_absolute_alone_can_trigger_material():
    # Revenue example (§3): +R$300K is material even at a modest % move.
    tier = classify_magnitude_tier(absolute_change=300000.0, percentage_change=5.0,
                                    absolute_threshold=50000.0, relative_threshold=15.0)
    assert tier >= TIER_MATERIAL


def test_magnitude_tier_huge_percentage_on_tiny_base_is_flagged_but_alone_not_enough():
    # +100% on a tiny denominator -- magnitude tier itself will read high
    # (percentage-driven), but classify_magnitude_tier alone doesn't know
    # about sample size; the small-sample check happens elsewhere
    # (materiality.decide via data-quality caps). This test only documents
    # that magnitude tiering is threshold-relative, not judgment-free.
    tier = classify_magnitude_tier(absolute_change=5.0, percentage_change=100.0,
                                    absolute_threshold=50000.0, relative_threshold=15.0)
    assert tier >= TIER_MATERIAL  # magnitude dimension alone says "big", by design


def test_magnitude_tier_normal_when_below_both_thresholds():
    tier = classify_magnitude_tier(absolute_change=100.0, percentage_change=1.0,
                                    absolute_threshold=50000.0, relative_threshold=15.0)
    assert tier == TIER_NORMAL


def test_magnitude_tier_normal_with_no_thresholds_configured():
    assert classify_magnitude_tier(1e9, 1e9, None, None) == TIER_NORMAL


def test_statistical_tier_bands():
    # statistical_threshold=2.0 -> watch>=2, material>=3, critical>=5
    assert classify_statistical_tier(z=1.0, robust_z=None, statistical_threshold=2.0) == TIER_NORMAL
    assert classify_statistical_tier(z=2.5, robust_z=None, statistical_threshold=2.0) == TIER_WATCH
    assert classify_statistical_tier(z=3.5, robust_z=None, statistical_threshold=2.0) == TIER_MATERIAL
    assert classify_statistical_tier(z=6.0, robust_z=None, statistical_threshold=2.0) == TIER_CRITICAL


def test_statistical_tier_uses_max_of_z_and_robust_z():
    assert classify_statistical_tier(z=1.0, robust_z=6.0, statistical_threshold=2.0) == TIER_CRITICAL


def test_business_impact_tier_bands():
    assert classify_business_impact_tier(magnitude=0.01, minimum_business_impact=0.05) == TIER_NORMAL
    assert classify_business_impact_tier(magnitude=0.06, minimum_business_impact=0.05) == TIER_WATCH
    assert classify_business_impact_tier(magnitude=0.5, minimum_business_impact=0.05) == TIER_CRITICAL


def test_combine_tiers_is_the_median_requiring_two_of_three_to_agree():
    # one CRITICAL, two NORMAL -> held to NORMAL (a single outlier dimension
    # cannot elevate the verdict alone)
    assert combine_tiers(TIER_CRITICAL, TIER_NORMAL, TIER_NORMAL) == TIER_NORMAL
    # two MATERIAL, one NORMAL -> MATERIAL (two dimensions corroborate)
    assert combine_tiers(TIER_MATERIAL, TIER_MATERIAL, TIER_NORMAL) == TIER_MATERIAL
    # all three CRITICAL -> CRITICAL
    assert combine_tiers(TIER_CRITICAL, TIER_CRITICAL, TIER_CRITICAL) == TIER_CRITICAL


# ---------------------------------------------------------------------------
# Business impact (§5) -- additive vs rate/average
# ---------------------------------------------------------------------------

def test_additive_business_impact_reports_a_total():
    bi = compute_business_impact("additive", "Revenue", observed_value=1010271.37, baseline_value=664219.43,
                                  observed_sample_size=7480, minimum_business_impact=10000.0)
    assert bi.magnitude == 1010271.37 - 664219.43
    assert bi.meets_minimum_business_impact is True
    assert "Revenue" in bi.business_interpretation
    assert "R$" not in bi.business_interpretation  # no currency symbol assumed -- KPI-agnostic wording


def test_rate_business_impact_never_claims_a_monetary_total():
    bi = compute_business_impact("rate_or_average", "Average Review Score", observed_value=3.91,
                                  baseline_value=4.12, observed_sample_size=7480, minimum_business_impact=0.05)
    assert abs(bi.magnitude - (3.91 - 4.12)) < 1e-9
    assert bi.affected_population == 7480
    assert "not a monetary total" in bi.business_interpretation
    assert bi.meets_minimum_business_impact is True


def test_business_impact_none_when_baseline_or_observed_missing():
    bi = compute_business_impact("additive", "Revenue", observed_value=None, baseline_value=100.0,
                                  observed_sample_size=10, minimum_business_impact=10.0)
    assert bi.magnitude is None
    assert bi.meets_minimum_business_impact is None
    assert "not computable" in bi.business_interpretation.lower()


# ---------------------------------------------------------------------------
# Persistence (§6) -- informational, not a gate
# ---------------------------------------------------------------------------

def _po(period, value):
    return PeriodObservation(period=period, value=value, sample_size=100)


def test_persistence_unknown_with_no_subsequent_data():
    p = classify_persistence(110.0, 100.0, subsequent=[], absolute_threshold=1.0, relative_threshold=1.0,
                              persistence_periods_required=2)
    assert p.persistence_class == PERSISTENCE_UNKNOWN


def test_persistence_one_off_shock_settles_back_to_normal():
    # a genuine one-period shock (200 vs baseline 100) that settles back to
    # near-baseline (101, well inside a 5-unit/5% noise band) the very next period
    p = classify_persistence(200.0, 100.0, subsequent=[_po("2017-12", 101.0)],
                              absolute_threshold=5.0, relative_threshold=5.0, persistence_periods_required=2)
    assert p.persistence_class == PERSISTENCE_ONE_OFF


def test_persistence_reversing_when_next_period_overshoots_opposite_direction():
    # spike up to 200 (baseline 100), then the following period swings materially
    # BELOW baseline (40) -- an overshoot/reversal, not a settling-back.
    p = classify_persistence(200.0, 100.0, subsequent=[_po("2017-12", 40.0)],
                              absolute_threshold=5.0, relative_threshold=5.0, persistence_periods_required=2)
    assert p.persistence_class == PERSISTENCE_REVERSING


def test_persistence_persistent_when_movement_carries_but_not_trending():
    p = classify_persistence(200.0, 100.0, subsequent=[_po("2017-12", 195.0), _po("2018-01", 198.0)],
                              absolute_threshold=1.0, relative_threshold=1.0, persistence_periods_required=2)
    assert p.persistence_class in (PERSISTENCE_PERSISTENT, PERSISTENCE_TRENDING)
    assert p.periods_affected >= 2


def test_persistence_trending_when_magnitude_keeps_growing():
    p = classify_persistence(150.0, 100.0, subsequent=[_po("2017-12", 200.0), _po("2018-01", 260.0)],
                              absolute_threshold=1.0, relative_threshold=1.0, persistence_periods_required=2)
    assert p.persistence_class == PERSISTENCE_TRENDING


def test_persistence_unknown_without_observed_or_baseline():
    p = classify_persistence(None, 100.0, subsequent=[], absolute_threshold=1.0, relative_threshold=1.0,
                              persistence_periods_required=2)
    assert p.persistence_class == PERSISTENCE_UNKNOWN


# ---------------------------------------------------------------------------
# decide() -- the combination + disagreement + confidence caps
# ---------------------------------------------------------------------------

def _sig(method, abs_change, pct_change):
    return BaselineSignalSet(method=method, absolute_change=abs_change, percentage_change=pct_change)


def test_decide_normal_when_all_dimensions_quiet():
    m = decide(primary=_sig("rolling_mean", 10.0, 1.0), alternates=[_sig("previous_period", 8.0, 0.8)],
               z=0.3, robust_z=0.2, percentile=55.0, business_impact_magnitude=10.0,
               absolute_threshold=50000.0, relative_threshold=15.0, statistical_threshold=2.0,
               minimum_business_impact=10000.0, baseline_confidence="HIGH",
               current_period_low_quality=False, current_period_quality_reasons=[])
    assert m.verdict == VERDICT_NORMAL


def test_decide_material_when_all_three_dimensions_corroborate():
    m = decide(primary=_sig("rolling_mean", 300000.0, 45.0), alternates=[_sig("previous_period", 290000.0, 44.0)],
               z=4.5, robust_z=4.8, percentile=99.0, business_impact_magnitude=300000.0,
               absolute_threshold=50000.0, relative_threshold=15.0, statistical_threshold=2.0,
               minimum_business_impact=10000.0, baseline_confidence="HIGH",
               current_period_low_quality=False, current_period_quality_reasons=[])
    assert m.verdict in (VERDICT_MATERIAL, VERDICT_CRITICAL)


def test_decide_low_baseline_confidence_caps_at_watch():
    m = decide(primary=_sig("previous_period", 300000.0, 200.0), alternates=[],
               z=6.0, robust_z=6.0, percentile=100.0, business_impact_magnitude=300000.0,
               absolute_threshold=50000.0, relative_threshold=15.0, statistical_threshold=2.0,
               minimum_business_impact=10000.0, baseline_confidence="LOW",
               current_period_low_quality=False, current_period_quality_reasons=[])
    assert m.verdict == VERDICT_WATCH
    assert any("Baseline confidence" in r for r in m.reasons)


def test_decide_low_current_period_quality_caps_at_watch():
    m = decide(primary=_sig("rolling_mean", 300000.0, 45.0), alternates=[],
               z=4.5, robust_z=4.8, percentile=99.0, business_impact_magnitude=300000.0,
               absolute_threshold=50000.0, relative_threshold=15.0, statistical_threshold=2.0,
               minimum_business_impact=10000.0, baseline_confidence="HIGH",
               current_period_low_quality=True, current_period_quality_reasons=["only 2 observations"])
    assert m.verdict == VERDICT_WATCH
    assert "only 2 observations" in m.reasons


def test_decide_baseline_disagreement_when_methods_split():
    m = decide(primary=_sig("rolling_mean", 10.0, 1.0), alternates=[_sig("previous_period", 500.0, 152.0)],
               z=0.2, robust_z=0.1, percentile=55.0, business_impact_magnitude=10.0,
               absolute_threshold=50000.0, relative_threshold=15.0, statistical_threshold=2.0,
               minimum_business_impact=10000.0, baseline_confidence="HIGH",
               current_period_low_quality=False, current_period_quality_reasons=[])
    assert m.verdict == VERDICT_BASELINE_DISAGREEMENT
    assert m.score is None


def test_decide_seasonal_primary_is_exempt_from_disagreement_check():
    # primary=seasonal says NORMAL, previous_period alternate screams CRITICAL
    # (expected for a real seasonal peak) -- must NOT trigger disagreement.
    m = decide(primary=_sig("seasonal", 0.0, 0.0), alternates=[_sig("previous_period", 1000.0, 100.0)],
               z=0.0, robust_z=0.0, percentile=50.0, business_impact_magnitude=0.0,
               absolute_threshold=50000.0, relative_threshold=15.0, statistical_threshold=2.0,
               minimum_business_impact=10000.0, baseline_confidence="HIGH",
               current_period_low_quality=False, current_period_quality_reasons=[])
    assert m.verdict == VERDICT_NORMAL
