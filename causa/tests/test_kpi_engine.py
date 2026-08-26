"""Step 3B engine tests: core calculation correctness for every KPI, including
the exact November 2017 validation numbers (task §19-20). Nothing here is
hardcoded as an expected constant without also being derived independently in
the test itself where practical (e.g. AOV is re-derived from Revenue/Orders
inside the test, not just compared to a magic number)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kpi.models import KPIRequest  # noqa: E402
from kpi.query_planner import KPIRequestError  # noqa: E402

OCT_2017 = ("2017-10-01", "2017-10-31")
NOV_2017 = ("2017-11-01", "2017-11-30")


# --- Revenue ------------------------------------------------------------------

def test_revenue_october_2017_exact(engine):
    r = engine.compute(KPIRequest(kpi_id="revenue", start_date=OCT_2017[0], end_date=OCT_2017[1]))
    assert round(r.value, 2) == 664219.43


def test_revenue_november_2017_exact(engine):
    r = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert round(r.value, 2) == 1010271.37


def test_revenue_change_matches_task_spec(engine):
    oct_r = engine.compute(KPIRequest(kpi_id="revenue", start_date=OCT_2017[0], end_date=OCT_2017[1]))
    nov_r = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert round(nov_r.value - oct_r.value, 2) == 346051.94


def test_revenue_is_pvm_ready_totals(engine):
    """Revenue at item grain, grouped by product_category, must sum back
    exactly to the ungrouped total -- the precondition for any future PVM
    decomposition (not built here, but the totals must be additive)."""
    total = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    by_category = engine.compute(KPIRequest(
        kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1], dimensions=["product_category"]
    ))
    resummed = sum(r.value for r in by_category)
    assert round(resummed, 2) == round(total.value, 2)


def test_revenue_has_no_payment_dependency(engine):
    r = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert "fact_payments" not in r.source
    assert "agg_order_payments" not in r.source
    assert all("payment" not in s for s in r.source)


def test_revenue_no_fan_out_when_grouped_by_seller(engine):
    """Grouping revenue by an item-grain dimension (seller) must not inflate the
    total -- proves the engine aggregates fact_order_items directly rather than
    joining through a multi-row table first."""
    total = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    by_seller = engine.compute(KPIRequest(
        kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1],
        dimensions=["seller"], requester_clearance="INTERNAL",
    ))
    assert round(sum(r.value for r in by_seller), 2) == round(total.value, 2)


# --- Orders ---------------------------------------------------------------

def test_orders_october_2017_exact(engine):
    r = engine.compute(KPIRequest(kpi_id="orders", start_date=OCT_2017[0], end_date=OCT_2017[1]))
    assert r.value == 4631.0


def test_orders_november_2017_exact(engine):
    r = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert r.value == 7544.0


def test_orders_change_matches_task_spec(engine):
    oct_r = engine.compute(KPIRequest(kpi_id="orders", start_date=OCT_2017[0], end_date=OCT_2017[1]))
    nov_r = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    pct = (nov_r.value - oct_r.value) / oct_r.value * 100
    assert round(pct, 1) == 62.9


def test_orders_default_includes_all_statuses(engine):
    """Must not silently exclude canceled/unavailable/delivered."""
    all_orders = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    delivered_only = engine.compute(KPIRequest(
        kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1], filters={"order_status": "delivered"}
    ))
    assert all_orders.value > delivered_only.value, "all-statuses count must exceed the delivered-only subset"
    assert all_orders.filters == {}


def test_orders_status_filter_is_explicit_opt_in(engine):
    r = engine.compute(KPIRequest(
        kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1], filters={"order_status": "canceled"}
    ))
    assert r.value > 0
    assert r.filters["order_status"] == "canceled"


# --- AOV --------------------------------------------------------------------

def test_aov_correct_denominator(engine):
    """AOV's denominator is orders-with-item-data, not all orders."""
    aov = engine.compute(KPIRequest(kpi_id="aov", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    orders_kpi = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert aov.metadata["denominator"] < orders_kpi.value, (
        "AOV's denominator must be strictly less than total Orders in Nov 2017 "
        "(some orders lack item data)"
    )
    revenue = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert round(aov.value * aov.metadata["denominator"], 2) == round(revenue.value, 2)


def test_aov_zero_denominator_is_null(engine):
    r = engine.compute(KPIRequest(
        kpi_id="aov", start_date="2010-01-01", end_date="2010-01-31", override_analytical_window=True
    ))
    assert r.value is None
    assert r.metadata["denominator"] == 0
    assert any("NULL" in w for w in r.warnings)


def test_itemless_orders_do_not_dilute_aov(engine):
    """Directly re-derives AOV two ways and confirms they agree: (numerator/
    denominator restricted to orders-with-items) vs. a naive (revenue / ALL
    orders including itemless ones), which must be LOWER (diluted)."""
    aov = engine.compute(KPIRequest(kpi_id="aov", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    orders_kpi = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    naive_diluted_aov = aov.metadata["numerator"] / orders_kpi.value
    assert naive_diluted_aov < aov.value, "AOV must be higher than the naive (revenue / all-orders) figure"


# --- Average Delivery Days ---------------------------------------------------

def test_delivery_invalid_rows_excluded(engine):
    r = engine.compute(KPIRequest(kpi_id="avg_delivery_days", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert r.filters["delivery_data_quality_flag"] == "VALID"
    assert r.metadata["excluded_invalid"] >= 0


def test_delivery_missing_rows_excluded_and_disclosed(engine):
    r = engine.compute(KPIRequest(kpi_id="avg_delivery_days", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    total = r.metadata["total_in_scope"]
    assert r.sample_size + r.metadata["excluded_invalid"] + r.metadata["excluded_missing"] == total


def test_delivery_null_not_zero(engine):
    """A slice with zero VALID rows must return None, never 0.0 days."""
    r = engine.compute(KPIRequest(
        kpi_id="avg_delivery_days", start_date="2010-01-01", end_date="2010-01-31", override_analytical_window=True
    ))
    assert r.value is None
    assert r.sample_size == 0


def test_avg_delivery_days_matches_step1_finding(engine):
    """Cross-check against the number independently reported in the prior EDA
    (docs/INVESTIGATION_SCENARIOS.md): Nov 2017 avg delivery days ~15.16."""
    r = engine.compute(KPIRequest(kpi_id="avg_delivery_days", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert round(r.value, 2) == 15.16


# --- Reviews ------------------------------------------------------------------

def test_review_score_representative_variant(engine):
    r = engine.compute(KPIRequest(kpi_id="avg_review_score", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert r.metadata["variant"] == "order_level_representative"
    assert 1.0 <= r.value <= 5.0


def test_review_score_true_average_variant(engine):
    r = engine.compute(KPIRequest(
        kpi_id="avg_review_score", start_date=NOV_2017[0], end_date=NOV_2017[1],
        variant="order_level_true_average",
    ))
    assert r.metadata["variant"] == "order_level_true_average"
    assert 1.0 <= r.value <= 5.0


def test_review_score_review_level_variant_is_a_different_statistic(engine):
    order_level = engine.compute(KPIRequest(kpi_id="avg_review_score", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    review_level = engine.compute(KPIRequest(
        kpi_id="avg_review_score", start_date=NOV_2017[0], end_date=NOV_2017[1], variant="review_level_average"
    ))
    assert review_level.grain != order_level.grain
    assert review_level.sample_size != order_level.sample_size


def test_review_score_never_uses_max(engine):
    """Regression guard: source code must never call .max() to select a review
    score -- REVIEW_GOVERNANCE.md quantitatively rejected that strategy."""
    import inspect
    from kpi.engine import KPIEngine
    src = inspect.getsource(KPIEngine._compute_avg_review_score)
    assert "review_score'].max(" not in src.replace(" ", "")
    assert '"review_score"].max(' not in src.replace(" ", "")


# --- Repeat Purchase Rate -----------------------------------------------------

def test_repeat_purchase_uses_customer_unique_id(engine):
    r = engine.compute(KPIRequest(kpi_id="repeat_purchase_rate"))
    assert "customer_unique_id" in " ".join(r.source) or "customer_unique_id" in str(r.lineage)


def test_repeat_purchase_correct_definition(engine):
    r = engine.compute(KPIRequest(kpi_id="repeat_purchase_rate"))
    assert r.metadata["repeat_customers"] < r.metadata["total_customers"]
    assert round(r.value, 4) == round(r.metadata["repeat_customers"] / r.metadata["total_customers"], 4)
    # cross-check against Step 2's independently-verified figure
    assert r.metadata["total_customers"] == 96096
    assert r.metadata["repeat_customers"] == 2997


# --- Freight Revenue / Quantity Sold / Review Volume / On-Time -----------------

def test_freight_revenue_does_not_mix_with_payment_value(engine):
    r = engine.compute(KPIRequest(kpi_id="freight_revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert all("payment" not in s for s in r.source)


def test_quantity_sold_documents_the_unit_assumption(engine):
    r = engine.compute(KPIRequest(kpi_id="quantity_sold", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert r.value > 0
    assert r.grain.startswith("order_item")


def test_review_volume_distinguishes_review_level_from_order_level(engine):
    r = engine.compute(KPIRequest(kpi_id="review_volume", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert r.metadata["review_level_count"] >= r.metadata["distinct_orders_represented"]
    assert r.value == r.metadata["review_level_count"]


def test_on_time_delivery_rate_uses_only_valid_rows(engine):
    r = engine.compute(KPIRequest(kpi_id="on_time_delivery_rate", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert r.filters["delivery_data_quality_flag"] == "VALID"
    assert 0.0 <= r.value <= 1.0
    assert r.metadata["denominator"] == r.sample_size


# --- Comparison periods --------------------------------------------------------

def test_compare_periods_reproduces_task_spec_exactly(engine):
    cmp = engine.compare_periods("revenue", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
    assert round(cmp.current_value, 2) == 1010271.37
    assert round(cmp.previous_value, 2) == 664219.43
    assert round(cmp.absolute_change, 2) == 346051.94
    assert round(cmp.percentage_change, 1) == 52.1


def test_compare_periods_orders_reproduces_task_spec(engine):
    cmp = engine.compare_periods("orders", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
    assert round(cmp.percentage_change, 1) == 62.9


def test_compare_periods_is_not_labeled_an_anomaly(engine):
    """Deterministic change calculation only -- must not carry any
    anomaly/materiality/significance judgement."""
    cmp = engine.compare_periods("revenue", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
    d = cmp.to_dict()
    assert "is_anomaly" not in d and "anomaly" not in d and "significant" not in d


def test_compare_periods_zero_previous_value_handled(engine):
    cmp = engine.compare_periods(
        "revenue", NOV_2017[0], NOV_2017[1], "2010-01-01", "2010-01-31", override_analytical_window=True
    )
    assert cmp.previous_value is None or cmp.previous_value == 0
    assert cmp.percentage_change is None


# --- Request rejection ----------------------------------------------------

def test_missing_required_kpi_id_rejected(engine):
    with pytest.raises(KPIRequestError):
        engine.compute(KPIRequest(kpi_id=""))
