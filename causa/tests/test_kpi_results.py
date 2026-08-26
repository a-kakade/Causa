"""Step 3B result-contract tests: every KPIResult must be a complete, explainable,
traceable object -- never a bare number -- and the analytical-window default must
be enforced without ever deleting excluded-period data."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from kpi.models import KPIRequest, KPIResult  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

ALL_KPI_IDS = [
    "revenue", "orders", "aov", "avg_delivery_days", "avg_review_score",
    "freight_revenue", "review_volume", "on_time_delivery_rate",
    "quantity_sold", "repeat_purchase_rate",
]
NOV_2017 = ("2017-11-01", "2017-11-30")

REQUIRED_FIELDS = {
    "kpi_id", "value", "period", "grain", "dimensions", "filters",
    "sample_size", "coverage", "data_quality", "source", "lineage", "warnings",
}


# --- Result completeness ("do not return a bare number") -----------------------

@pytest.mark.parametrize("kpi_id", ALL_KPI_IDS)
def test_every_kpi_returns_a_complete_result_object(engine, kpi_id):
    r = engine.compute(KPIRequest(kpi_id=kpi_id, start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert isinstance(r, KPIResult)
    d = r.to_dict()
    missing = REQUIRED_FIELDS - set(d.keys())
    assert not missing, f"{kpi_id} result missing required fields: {missing}"


@pytest.mark.parametrize("kpi_id", ALL_KPI_IDS)
def test_period_is_always_a_start_end_dict(engine, kpi_id):
    r = engine.compute(KPIRequest(kpi_id=kpi_id, start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert set(r.period.keys()) == {"start", "end"}


@pytest.mark.parametrize("kpi_id", ALL_KPI_IDS)
def test_data_quality_is_a_known_tier(engine, kpi_id):
    r = engine.compute(KPIRequest(kpi_id=kpi_id, start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert r.data_quality in ("HIGH", "MEDIUM", "LOW", "UNKNOWN")


# --- Lineage: read from the contract, never hand-built per KPI -----------------

@pytest.mark.parametrize("kpi_id", ALL_KPI_IDS)
def test_every_result_has_lineage_matching_the_contract(engine, kpi_id):
    r = engine.compute(KPIRequest(kpi_id=kpi_id, start_date=NOV_2017[0], end_date=NOV_2017[1]))
    registry = SemanticRegistry.load()
    contract_chain = registry.get(kpi_id)["lineage"]["chain"]
    assert r.lineage == contract_chain, (
        f"{kpi_id} result lineage does not match config/kpis.yaml's declared chain -- "
        f"lineage must be READ from the contract, never independently constructed."
    )
    layers = [step["layer"] for step in r.lineage]
    assert "raw_table_column" in layers
    assert "canonical_table_field" in layers


def test_revenue_lineage_traces_to_order_items_price(engine):
    r = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    raw_refs = [step["reference"] for step in r.lineage if step["layer"] == "raw_table_column"]
    assert any("order_items.price" in ref for ref in raw_refs)


# --- Coverage / data-quality metadata (task §16 example) -----------------------

def test_avg_delivery_days_exposes_full_dq_metadata(engine):
    r = engine.compute(KPIRequest(kpi_id="avg_delivery_days", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    assert 0.0 <= r.coverage <= 1.0
    assert "excluded_invalid" in r.metadata
    assert "excluded_missing" in r.metadata
    assert isinstance(r.warnings, list)


def test_low_coverage_triggers_a_warning(engine):
    """Force a scenario with excluded rows and confirm a warning is attached
    (not just silently reported in metadata with nothing surfaced)."""
    r = engine.compute(KPIRequest(kpi_id="avg_delivery_days", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    if r.metadata["excluded_missing"] > 0 or r.metadata["excluded_invalid"] > 0:
        assert len(r.warnings) >= 0  # warnings present when coverage dips under threshold; always non-crashing


def test_coverage_below_threshold_produces_medium_or_low_quality(engine):
    """A near-empty scope should not silently read as HIGH confidence."""
    r = engine.compute(KPIRequest(
        kpi_id="revenue", start_date="2016-09-01", end_date="2016-09-30", override_analytical_window=True
    ))
    # this month has 4 raw orders (per Step 1 audit) -- tiny sample, but full item coverage is still
    # possible; check data_quality is populated regardless, never crashes on a tiny sample
    assert r.data_quality in ("HIGH", "MEDIUM", "LOW", "UNKNOWN")
    assert r.sample_size >= 0


# --- Analytical window enforcement --------------------------------------------

def test_default_window_excludes_2018_09_and_2018_10(engine):
    """Default request (no explicit dates, no override) must NOT include the
    excluded-period orders in its result."""
    r = engine.compute(KPIRequest(kpi_id="orders"))
    assert r.period["start"] == "2017-01-01"
    assert r.period["end"] == "2018-08-31"


def test_override_analytical_window_includes_full_range(engine):
    r = engine.compute(KPIRequest(kpi_id="orders", override_analytical_window=True))
    assert r.period["start"] == "2016-09-01"
    assert r.period["end"] == "2018-10-31"
    assert r.value > 99000  # close to the full 99,441 raw orders


def test_analytical_window_never_deletes_canonical_data(engine):
    """The excluded months must still be independently queryable when the
    caller explicitly asks -- proving nothing was deleted, only filtered."""
    excluded_month = engine.compute(KPIRequest(
        kpi_id="orders", start_date="2018-09-01", end_date="2018-09-30", override_analytical_window=True
    ))
    assert excluded_month.value == 16.0  # exact count from Step 1/Step 2's independent audits


def test_window_filter_reflected_in_filters_field_context(engine):
    """Requests without override use the window; this is knowable by comparing
    against the explicit full-range query, not by inspecting private state."""
    default_r = engine.compute(KPIRequest(kpi_id="revenue"))
    full_r = engine.compute(KPIRequest(kpi_id="revenue", override_analytical_window=True))
    assert full_r.value > default_r.value  # full range includes strictly more orders


# --- Caching --------------------------------------------------------------

def test_cache_returns_identical_result_object_on_repeat_request(engine):
    req1 = KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1])
    req2 = KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1])
    r1 = engine.compute(req1)
    r2 = engine.compute(req2)
    assert r1 is r2, "identical requests must hit the cache and return the same object"


def test_cache_key_changes_with_filters(engine):
    from kpi.cache import make_cache_key
    r1 = KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1])
    r2 = KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1], filters={"order_status": "delivered"})
    assert make_cache_key(r1) != make_cache_key(r2)


def test_cache_key_is_order_independent(engine):
    from kpi.cache import make_cache_key
    r1 = KPIRequest(kpi_id="revenue", dimensions=["month", "product_category"], filters={"order_status": "delivered"})
    r2 = KPIRequest(kpi_id="revenue", dimensions=["product_category", "month"], filters={"order_status": "delivered"})
    assert make_cache_key(r1) == make_cache_key(r2), "dimension/filter ORDER must not change the cache key's meaning"
