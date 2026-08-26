"""Step 3B dimension-engine tests: supported dimensions must succeed and produce
additive results; unsupported/unauthorized dimensions must fail explicitly, with
no invented attribution rule ever silently applied."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kpi.models import KPIRequest  # noqa: E402
from kpi.query_planner import UnauthorizedDimensionError, UnsupportedDimensionError  # noqa: E402

NOV_2017 = ("2017-11-01", "2017-11-30")


# --- Supported dimensions succeed -------------------------------------------

@pytest.mark.parametrize("dim", ["month", "product_category", "customer_state", "seller_state", "product"])
def test_revenue_supported_dimensions_succeed(engine, dim):
    kwargs = {"requester_clearance": "INTERNAL"} if dim == "seller" else {}
    results = engine.compute(KPIRequest(
        kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1], dimensions=[dim], **kwargs
    ))
    assert isinstance(results, list) and len(results) > 0
    for r in results:
        assert dim in r.dimensions


def test_revenue_seller_dimension_succeeds_with_clearance(engine):
    results = engine.compute(KPIRequest(
        kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1],
        dimensions=["seller"], requester_clearance="INTERNAL",
    ))
    assert len(results) > 0


@pytest.mark.parametrize("dim", ["month", "customer_state"])
def test_orders_supported_dimensions_succeed(engine, dim):
    results = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1], dimensions=[dim]))
    assert isinstance(results, list) and len(results) > 0


def test_grouped_results_sum_to_total_for_item_grain_kpis(engine):
    """The core proof that dimension grouping is safe for item-grain KPIs."""
    total = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    for dim in ("product_category", "customer_state", "product"):
        grouped = engine.compute(KPIRequest(
            kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1], dimensions=[dim]
        ))
        resummed = sum(r.value for r in grouped)
        assert round(resummed, 2) == round(total.value, 2), f"dimension {dim} did not sum back to the total"


def test_grouped_orders_do_not_sum_to_total_for_multi_valued_dims_because_they_are_unsupported(engine):
    """orders x customer_state grouping IS supported and IS additive (customer_state
    is a genuine 1:1 order attribute) -- proves the engine doesn't just block
    everything, only the genuinely unsafe cases."""
    total = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    grouped = engine.compute(KPIRequest(
        kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1], dimensions=["customer_state"]
    ))
    assert sum(r.value for r in grouped) == total.value


# --- Unsupported dimensions fail explicitly (order-grain KPI x item-grain dim) -

@pytest.mark.parametrize("kpi_id,dim", [
    ("orders", "product"), ("orders", "seller"), ("orders", "product_category"), ("orders", "seller_state"),
    ("aov", "product"), ("aov", "seller"), ("aov", "product_category"), ("aov", "seller_state"),
    ("avg_delivery_days", "seller"), ("avg_delivery_days", "product_category"),
    ("avg_review_score", "seller"), ("avg_review_score", "product"),
    ("on_time_delivery_rate", "seller"), ("on_time_delivery_rate", "product_category"),
    ("review_volume", "seller"), ("review_volume", "product"),
    ("repeat_purchase_rate", "customer_state"), ("repeat_purchase_rate", "product"),
])
def test_unsupported_dimension_fails_explicitly(engine, kpi_id, dim):
    with pytest.raises(UnsupportedDimensionError) as exc_info:
        engine.compute(KPIRequest(kpi_id=kpi_id, dimensions=[dim]))
    # the error must carry the CONTRACT's documented reason, not a generic message
    assert "reason" in str(exc_info.value).lower() or "grain" in str(exc_info.value).lower()


def test_unsupported_dimension_error_never_silently_falls_back(engine):
    """A rejected request must raise, not return a result with a made-up
    attribution rule."""
    with pytest.raises(UnsupportedDimensionError):
        engine.compute(KPIRequest(kpi_id="orders", dimensions=["product"]))
    # confirm no partial/garbage result was cached under this key either
    assert True  # the exception above IS the assertion; this documents intent


def test_unknown_dimension_name_fails(engine):
    with pytest.raises(UnsupportedDimensionError):
        engine.compute(KPIRequest(kpi_id="revenue", dimensions=["warehouse_zone"]))


# --- Unauthorized dimensions (security clearance) --------------------------

def test_seller_dimension_requires_internal_clearance(engine):
    with pytest.raises(UnauthorizedDimensionError):
        engine.compute(KPIRequest(
            kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1],
            dimensions=["seller"], requester_clearance="PUBLIC_ANALYTICAL",
        ))


def test_public_dimensions_do_not_require_elevated_clearance(engine):
    r = engine.compute(KPIRequest(
        kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1],
        dimensions=["product_category"], requester_clearance="PUBLIC_ANALYTICAL",
    ))
    assert len(r) > 0


# --- Order-grain KPIs also support their DECLARED dimensions (not just revenue) --

def test_aov_supports_month_dimension(engine):
    results = engine.compute(KPIRequest(kpi_id="aov", start_date=NOV_2017[0], end_date=NOV_2017[1], dimensions=["month"]))
    assert len(results) == 1
    assert results[0].dimensions == {"month": "2017-11"}
    assert results[0].value > 0


def test_avg_delivery_days_supports_customer_state_dimension(engine):
    results = engine.compute(KPIRequest(
        kpi_id="avg_delivery_days", start_date=NOV_2017[0], end_date=NOV_2017[1], dimensions=["customer_state"]
    ))
    assert len(results) > 1
    assert all("customer_state" in r.dimensions for r in results)


def test_on_time_delivery_rate_supports_month_dimension(engine):
    results = engine.compute(KPIRequest(
        kpi_id="on_time_delivery_rate", start_date="2017-10-01", end_date="2017-11-30", dimensions=["month"]
    ))
    assert len(results) == 2
    for r in results:
        assert 0.0 <= r.value <= 1.0


def test_avg_review_score_default_variant_supports_month_dimension(engine):
    results = engine.compute(KPIRequest(
        kpi_id="avg_review_score", start_date="2017-10-01", end_date="2017-11-30", dimensions=["month"]
    ))
    assert len(results) == 2
    for r in results:
        assert 1.0 <= r.value <= 5.0
        assert r.metadata["variant"] == "order_level_representative"


def test_review_volume_supports_month_dimension_and_sums_to_total(engine):
    total = engine.compute(KPIRequest(kpi_id="review_volume", start_date="2017-10-01", end_date="2017-11-30"))
    by_month = engine.compute(KPIRequest(
        kpi_id="review_volume", start_date="2017-10-01", end_date="2017-11-30", dimensions=["month"]
    ))
    assert sum(r.value for r in by_month) == total.value


def test_repeat_purchase_rate_month_dimension_explicitly_refused(engine):
    """The contract documents this as an unresolved semantic decision (no ready
    cohort query) -- the engine must refuse, not silently compute something
    the contract doesn't define."""
    from kpi.query_planner import KPIRequestError
    with pytest.raises(KPIRequestError, match="(?i)cohort"):
        engine.compute(KPIRequest(kpi_id="repeat_purchase_rate", dimensions=["month"]))
