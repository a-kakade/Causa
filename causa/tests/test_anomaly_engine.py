"""
Step 3C: end-to-end tests for src/anomaly/engine.py -- the materiality and
anomaly detection engine. Covers every scenario required by this task's §16:

 1. normal movement
 2. large movement
 3. statistically unusual movement
 4. business-impactful small percentage movement
 5. large percentage movement with tiny sample
 6. sparse entity (real data)
 7. baseline fallback
 8. seasonal movement
 9. persistent movement
10. one-off shock
11. baseline disagreement
12. low-quality data
13. NULL KPI
14. zero denominator
15. November 2017 revenue movement (real data, via kpi.engine.KPIEngine)

Plus: no result anywhere in this file contains a causal claim (§15).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from anomaly import engine as anomaly_engine  # noqa: E402
from anomaly.models import (  # noqa: E402
    BASELINE_LEVEL_CATEGORY, BASELINE_LEVEL_ENTITY, BASELINE_LEVEL_GLOBAL,
    PERSISTENCE_ONE_OFF, PERSISTENCE_PERSISTENT, PERSISTENCE_TRENDING, PERSISTENCE_UNKNOWN,
    VERDICT_BASELINE_DISAGREEMENT, VERDICT_CRITICAL, VERDICT_INSUFFICIENT_DATA, VERDICT_MATERIAL,
    VERDICT_NORMAL, VERDICT_WATCH,
    AnomalyRequest, BaselineLevel, PeriodObservation,
)
from kpi.models import KPIRequest  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402


@pytest.fixture(scope="module")
def registry() -> SemanticRegistry:
    r = SemanticRegistry.load()
    r.validate()
    return r


def months(n, start_value, step=0.0, sample_size=100, start_year=2017, start_month=1):
    """n consecutive monthly PeriodObservations, value = start_value + i*step."""
    obs = []
    y, m = start_year, start_month
    for i in range(n):
        obs.append(PeriodObservation(period=f"{y}-{m:02d}", value=start_value + i * step, sample_size=sample_size))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return obs


def global_level(history):
    return BaselineLevel(level=BASELINE_LEVEL_GLOBAL, label="all_products_all_regions", history=history)


# ---------------------------------------------------------------------------
# 1. Normal movement
# ---------------------------------------------------------------------------

def test_1_normal_movement_is_not_flagged(registry):
    hist = months(9, 1000.0, step=1.0, sample_size=200)  # a nearly flat series
    req = AnomalyRequest(kpi_id="revenue", period="2017-10", observed_value=1009.0,
                          observed_sample_size=200, observed_coverage=0.99, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.materiality.verdict == VERDICT_NORMAL


# ---------------------------------------------------------------------------
# 2. Large movement
# ---------------------------------------------------------------------------

def test_2_large_broad_based_movement_is_material_or_critical(registry):
    hist = months(10, 650000.0, step=1500.0, sample_size=4500)
    req = AnomalyRequest(kpi_id="revenue", period="2017-11", observed_value=1010271.37,
                          observed_sample_size=7480, observed_coverage=0.99, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.materiality.verdict in (VERDICT_MATERIAL, VERDICT_CRITICAL)
    assert res.materiality.tier_magnitude >= 2


# ---------------------------------------------------------------------------
# 3. Statistically unusual movement (small in absolute/% terms relative to
#    contract thresholds, but many std-deviations from a very tight history)
# ---------------------------------------------------------------------------

def test_3_statistically_unusual_movement_flagged_by_zscore(registry):
    # avg_review_score has a tight historical band (4.10-4.14) -- a move to
    # 4.30 is small in absolute/contract terms relative to a 4-point scale but
    # is many std-deviations outside this KPI's own tight history.
    hist = [PeriodObservation(period=f"2017-{m:02d}", value=4.10 + (m % 3) * 0.01, sample_size=5000) for m in range(1, 10)]
    req = AnomalyRequest(kpi_id="avg_review_score", period="2017-10", observed_value=4.30,
                          observed_sample_size=5000, observed_coverage=0.99, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.statistical_signals.z_score is not None
    assert abs(res.statistical_signals.z_score) >= 2.0
    assert res.materiality.tier_statistical >= 1


# ---------------------------------------------------------------------------
# 4. Business-impactful small percentage movement
# ---------------------------------------------------------------------------

def test_4_small_percentage_movement_can_still_be_material_via_absolute_impact(registry):
    # Revenue example from task §3: +R$300K is material even at a modest %
    # move on a large base.
    hist = months(9, 6_000_000.0, step=1000.0, sample_size=50000)
    observed = hist[-1].value + 300_000.0  # ~5% move, but +R$300K in absolute terms
    req = AnomalyRequest(kpi_id="revenue", period="2017-10", observed_value=observed,
                          observed_sample_size=50000, observed_coverage=0.99, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.materiality.tier_magnitude >= 2  # absolute_threshold=50000 -> 300K/50K = 6x -> CRITICAL
    assert res.business_impact.meets_minimum_business_impact is True


# ---------------------------------------------------------------------------
# 5. Large percentage movement with tiny sample -- must NOT be an automatic
#    high-confidence anomaly (task §3's "small product: +100% may be
#    statistically meaningless")
# ---------------------------------------------------------------------------

def test_5_large_percentage_movement_tiny_sample_is_not_automatically_critical(registry):
    hist = [PeriodObservation(period=f"2017-{m:02d}", value=50.0, sample_size=1) for m in range(1, 4)]
    req = AnomalyRequest(kpi_id="revenue", period="2017-04", observed_value=100.0,  # +100%
                          observed_sample_size=1, observed_coverage=0.02, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.materiality.verdict not in (VERDICT_MATERIAL, VERDICT_CRITICAL)
    assert res.data_quality.downgraded


# ---------------------------------------------------------------------------
# 6. Sparse entity -- REAL data (task §12 explicitly requires this)
# ---------------------------------------------------------------------------

def test_6_sparse_real_product_falls_back_and_never_reaches_high_confidence(canonical, registry):
    items = canonical["fact_order_items"][["order_id", "product_id", "price"]]
    orders = canonical["fact_orders"][["order_id", "purchase_timestamp"]]
    merged = items.merge(orders, on="order_id", how="inner")
    merged["month"] = merged["purchase_timestamp"].dt.to_period("M").astype(str)

    row_counts = merged.groupby("product_id").size()
    month_counts = merged.groupby("product_id")["month"].nunique()
    # a real product with exactly 2 line-item rows, in 2 different months --
    # per docs/INVESTIGATION_SCENARIOS.md §4, the median product has exactly 1
    # historical sale, so this pattern is common, not manufactured.
    candidates = row_counts[(row_counts == 2) & (month_counts == 2)]
    assert len(candidates) > 0, "expected at least one real 2-observation/2-month product in the canonical data"
    product_id = candidates.index[0]

    entity_rows = merged[merged["product_id"] == product_id].sort_values("purchase_timestamp")
    entity_monthly = entity_rows.groupby("month")["price"].agg(["sum", "size"]).sort_index()
    entity_history = [PeriodObservation(period=m, value=float(r["sum"]), sample_size=int(r["size"]))
                       for m, r in entity_monthly.iloc[:-1].iterrows()]
    observed_period = entity_monthly.index[-1]
    observed_value = float(entity_monthly.iloc[-1]["sum"])
    assert sum(o.sample_size for o in entity_history) < 30  # well below revenue's minimum_observations

    dim_product = canonical["dim_product"][["product_id", "category_name_en"]]
    with_cat = merged.merge(dim_product, on="product_id", how="left")
    category = with_cat.loc[with_cat["product_id"] == product_id, "category_name_en"].iloc[0]
    cat_rows = with_cat[(with_cat["category_name_en"] == category) & (with_cat["month"] < observed_period)]
    cat_monthly = cat_rows.groupby("month")["price"].agg(["sum", "size"]).sort_index()
    category_history = [PeriodObservation(period=m, value=float(r["sum"]), sample_size=int(r["size"]))
                         for m, r in cat_monthly.iterrows()]

    global_rows = merged[merged["month"] < observed_period]
    glob_monthly = global_rows.groupby("month")["price"].agg(["sum", "size"]).sort_index()
    global_history = [PeriodObservation(period=m, value=float(r["sum"]), sample_size=int(r["size"]))
                       for m, r in glob_monthly.iterrows()]

    levels = [
        BaselineLevel(level=BASELINE_LEVEL_ENTITY, label=f"product:{product_id}", history=entity_history),
        BaselineLevel(level=BASELINE_LEVEL_CATEGORY, label=f"category:{category}", history=category_history),
        global_level(global_history),
    ]
    req = AnomalyRequest(kpi_id="revenue", period=observed_period, observed_value=observed_value,
                          observed_sample_size=1, observed_coverage=0.01, levels=levels)
    res = anomaly_engine.detect(registry, req)

    assert res.baseline.baseline_level != BASELINE_LEVEL_ENTITY  # forced to fall back
    assert res.baseline.baseline_confidence != "HIGH"
    assert res.materiality.verdict != VERDICT_CRITICAL  # never a high-confidence anomaly from 2 observations


# ---------------------------------------------------------------------------
# 7. Baseline fallback (synthetic, explicit multi-hop chain)
# ---------------------------------------------------------------------------

def test_7_baseline_fallback_chain_entity_to_category_to_global(registry):
    entity = BaselineLevel(BASELINE_LEVEL_ENTITY, "product:x", [PeriodObservation("2018-01", 50.0, sample_size=1)])
    category = BaselineLevel(BASELINE_LEVEL_CATEGORY, "category:y", [PeriodObservation("2018-01", 60.0, sample_size=2)])
    glob = global_level(months(9, 9000.0, step=10.0, sample_size=500))
    req = AnomalyRequest(kpi_id="revenue", period="2018-02", observed_value=9500.0,
                          observed_sample_size=500, observed_coverage=0.98, levels=[entity, category, glob])
    res = anomaly_engine.detect(registry, req)
    assert res.baseline.baseline_level == BASELINE_LEVEL_GLOBAL
    assert res.baseline.fallback_reason == "entity, category_history_insufficient"


# ---------------------------------------------------------------------------
# 8. Seasonal movement -- large but expected, must NOT be flagged abnormal
# ---------------------------------------------------------------------------

def test_8_seasonal_peak_matching_prior_years_is_normal(registry):
    hist = []
    for year in (2015, 2016):
        hist += [PeriodObservation(f"{year}-{m:02d}", 2000.0 if m == 11 else 1000.0, sample_size=300) for m in range(1, 13)]
    hist += [PeriodObservation(f"2017-{m:02d}", 2000.0 if m == 11 else 1000.0, sample_size=300) for m in range(1, 11)]
    req = AnomalyRequest(kpi_id="revenue", period="2017-11", observed_value=2000.0,
                          observed_sample_size=300, observed_coverage=0.99, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.baseline.baseline_method == "seasonal"
    assert res.materiality.verdict == VERDICT_NORMAL


# ---------------------------------------------------------------------------
# 9. Persistent movement
# ---------------------------------------------------------------------------

def test_9_persistent_movement_is_classified_but_persistence_does_not_gate_verdict(registry):
    hist = months(9, 650000.0, step=1500.0, sample_size=4500)
    subsequent = [PeriodObservation("2017-12", 990000.0, sample_size=7000),
                  PeriodObservation("2018-01", 985000.0, sample_size=7000)]
    req = AnomalyRequest(kpi_id="revenue", period="2017-11", observed_value=1010271.37,
                          observed_sample_size=7480, observed_coverage=0.99,
                          levels=[global_level(hist)], subsequent=subsequent)
    res = anomaly_engine.detect(registry, req)
    assert res.persistence.persistence_class in (PERSISTENCE_PERSISTENT, PERSISTENCE_TRENDING)
    assert res.persistence.periods_affected >= 2
    assert res.materiality.verdict in (VERDICT_MATERIAL, VERDICT_CRITICAL)  # unaffected by persistence


# ---------------------------------------------------------------------------
# 10. One-off shock -- can still be material despite not persisting
# ---------------------------------------------------------------------------

def test_10_one_off_shock_can_still_be_material(registry):
    hist = months(9, 650000.0, step=1500.0, sample_size=4500)
    subsequent = [PeriodObservation("2017-12", 665000.0, sample_size=4600)]  # settles right back
    req = AnomalyRequest(kpi_id="revenue", period="2017-11", observed_value=1010271.37,
                          observed_sample_size=7480, observed_coverage=0.99,
                          levels=[global_level(hist)], subsequent=subsequent)
    res = anomaly_engine.detect(registry, req)
    assert res.persistence.persistence_class == PERSISTENCE_ONE_OFF
    assert res.materiality.verdict in (VERDICT_MATERIAL, VERDICT_CRITICAL), (
        "task §6: a one-off shock must still be able to reach MATERIAL/CRITICAL"
    )


# ---------------------------------------------------------------------------
# 11. Baseline disagreement
# ---------------------------------------------------------------------------

def test_11_contradictory_baselines_produce_baseline_disagreement(registry):
    hist = [PeriodObservation(f"2017-{m:02d}", 1000.0, sample_size=200) for m in range(1, 9)]
    hist.append(PeriodObservation("2017-09", 400.0, sample_size=200))  # one unusually low prior month
    req = AnomalyRequest(kpi_id="revenue", period="2017-10", observed_value=1010.0,
                          observed_sample_size=200, observed_coverage=0.99, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.materiality.verdict == VERDICT_BASELINE_DISAGREEMENT
    assert res.materiality.score is None
    assert "method_verdicts" in res.materiality.baseline_signals


# ---------------------------------------------------------------------------
# 12. Low-quality data
# ---------------------------------------------------------------------------

def test_12_low_quality_current_period_downgrades_and_is_disclosed(registry):
    hist = months(9, 4.10, step=0.001, sample_size=5000)
    req = AnomalyRequest(kpi_id="avg_review_score", period="2017-10", observed_value=4.30,
                          observed_sample_size=8, observed_coverage=0.10,  # far below thresholds
                          levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.data_quality.downgraded
    assert any("8" in r for r in res.data_quality.reasons)
    assert res.materiality.verdict != VERDICT_CRITICAL


# ---------------------------------------------------------------------------
# 13. NULL KPI
# ---------------------------------------------------------------------------

def test_13_null_kpi_value_is_insufficient_data_not_a_crash(registry):
    hist = months(9, 100.0, sample_size=50)
    req = AnomalyRequest(kpi_id="aov", period="2018-01", observed_value=None,
                          observed_sample_size=0, observed_coverage=None, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.materiality.verdict == VERDICT_INSUFFICIENT_DATA
    assert res.movement.absolute is None and res.movement.percentage is None


# ---------------------------------------------------------------------------
# 14. Zero denominator (same NULL-value contract, different KPI/scenario)
# ---------------------------------------------------------------------------

def test_14_zero_denominator_ratio_is_insufficient_data(registry):
    hist = months(9, 0.85, step=0.0, sample_size=4000)
    req = AnomalyRequest(kpi_id="on_time_delivery_rate", period="2018-01", observed_value=None,
                          observed_sample_size=0, observed_coverage=None, levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)
    assert res.materiality.verdict == VERDICT_INSUFFICIENT_DATA
    assert res.business_impact.magnitude is None


# ---------------------------------------------------------------------------
# 15. November 2017 revenue movement -- REAL data via kpi.engine.KPIEngine
# ---------------------------------------------------------------------------

def test_15_november_2017_revenue_is_flagged_material_or_critical(engine, registry):
    """`engine` is the Step 3B KPIEngine fixture (conftest.py). Builds a real
    Jan-Oct 2017 history and evaluates the real November 2017 observed value --
    nothing here is hardcoded; every number comes from KPIEngine.compute()
    against data/processed/*.parquet, per Step 3B's own discipline."""
    # calendar month boundaries, same pattern as scripts/step3b_validate_engine.py's OCT_2017/NOV_2017
    import calendar
    hist = []
    for m in range(1, 11):
        last_day = calendar.monthrange(2017, m)[1]
        r = engine.compute(KPIRequest(kpi_id="revenue", start_date=f"2017-{m:02d}-01",
                                       end_date=f"2017-{m:02d}-{last_day:02d}", override_analytical_window=True))
        hist.append(PeriodObservation(period=f"2017-{m:02d}", value=r.value, sample_size=r.sample_size))

    nov = engine.compute(KPIRequest(kpi_id="revenue", start_date="2017-11-01", end_date="2017-11-30",
                                     override_analytical_window=True))

    req = AnomalyRequest(kpi_id="revenue", period="2017-11", observed_value=nov.value,
                          observed_sample_size=nov.sample_size, observed_coverage=nov.coverage,
                          levels=[global_level(hist)])
    res = anomaly_engine.detect(registry, req)

    assert res.observed_value == pytest.approx(1010271.37, abs=0.01)
    assert res.materiality.verdict in (VERDICT_MATERIAL, VERDICT_CRITICAL), (
        f"Expected November 2017 revenue to be flagged as a strong investigation candidate, got {res.materiality.verdict}"
    )
    # this engine identifies MATERIALITY, not CAUSE -- see the causal-claim scan below


# ---------------------------------------------------------------------------
# No causal claims, anywhere (task §15)
# ---------------------------------------------------------------------------

CAUSAL_PATTERNS = re.compile(
    r"\b(caused by|causes|because of|due to|the reason (is|for)|as a result of|"
    r"black\s*friday|led to|driven by|drove the|responsible for)\b",
    re.IGNORECASE,
)


def _all_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _all_strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _all_strings(v)


@pytest.mark.parametrize("case_name,request_builder", [
    ("normal", lambda: AnomalyRequest(kpi_id="revenue", period="2017-10", observed_value=1009.0,
                                       observed_sample_size=200, observed_coverage=0.99,
                                       levels=[global_level(months(9, 1000.0, step=1.0, sample_size=200))])),
    ("large_movement", lambda: AnomalyRequest(kpi_id="revenue", period="2017-11", observed_value=1010271.37,
                                               observed_sample_size=7480, observed_coverage=0.99,
                                               levels=[global_level(months(10, 650000.0, step=1500.0, sample_size=4500))])),
    ("baseline_disagreement", lambda: AnomalyRequest(
        kpi_id="revenue", period="2017-10", observed_value=1010.0, observed_sample_size=200, observed_coverage=0.99,
        levels=[global_level([PeriodObservation(f"2017-{m:02d}", 1000.0, sample_size=200) for m in range(1, 9)]
                              + [PeriodObservation("2017-09", 400.0, sample_size=200)])])),
    ("null_kpi", lambda: AnomalyRequest(kpi_id="aov", period="2018-01", observed_value=None,
                                         observed_sample_size=0, levels=[global_level(months(9, 100.0, sample_size=50))])),
])
def test_no_result_contains_a_causal_claim(registry, case_name, request_builder):
    res = anomaly_engine.detect(registry, request_builder())
    offenders = [s for s in _all_strings(res.to_dict()) if CAUSAL_PATTERNS.search(s)]
    assert not offenders, f"[{case_name}] causal language found in result: {offenders}"
