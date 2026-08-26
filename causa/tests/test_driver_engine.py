"""
Step 3D: end-to-end tests for src/drivers/engine.py -- the driver
decomposition engine. Covers every scenario required by this task's §18 not
already covered by tests/test_pvm.py / tests/test_contributions.py:

 2. November 2017 exact values (real data)
 3. category contribution reconciliation (real data)
 4. seller contribution reconciliation (real data)
 5. customer-state reconciliation (real data)
 6. seller-state reconciliation (real data)
12. unsupported dimensions
13. numerical tolerance / ReconciliationError
14. causal_claim always false
15. cross-KPI package completeness

(§1 PVM exact reconciliation, §7 NULL category handling, §8/9 zero-baseline
entities, §10 sparse-entity metadata, and §11 ranking are covered directly in
tests/test_pvm.py and tests/test_contributions.py at the unit level.)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from drivers import engine as driver_engine  # noqa: E402
from drivers.models import DriverDecompositionRequest  # noqa: E402
from drivers.pvm import compute_pvm_bridge  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

OCT_2017 = ("2017-10-01", "2017-10-31", "2017-10")
NOV_2017 = ("2017-11-01", "2017-11-30", "2017-11")


@pytest.fixture(scope="module")
def registry() -> SemanticRegistry:
    r = SemanticRegistry.load()
    r.validate()
    return r


def nov_2017_request(**overrides) -> DriverDecompositionRequest:
    kwargs = dict(
        kpi_id="revenue",
        period_current_start=NOV_2017[0], period_current_end=NOV_2017[1], period_current_label=NOV_2017[2],
        period_previous_start=OCT_2017[0], period_previous_end=OCT_2017[1], period_previous_label=OCT_2017[2],
        override_analytical_window=True,
    )
    kwargs.update(overrides)
    return DriverDecompositionRequest(**kwargs)


# ---------------------------------------------------------------------------
# 2. November 2017 exact values (task §2/§18.2)
# ---------------------------------------------------------------------------

def test_november_2017_pvm_matches_required_exact_values(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request())
    by_name = {d.driver: d.contribution_value for d in res.drivers}

    assert res.total_change["absolute"] == pytest.approx(346051.94, abs=0.01)
    assert by_name["volume"] == pytest.approx(417227.65, abs=0.01)
    assert by_name["price"] == pytest.approx(4674.63, abs=0.01)
    assert by_name["mix"] == pytest.approx(-75850.34, abs=0.01)
    checksum = by_name["volume"] + by_name["price"] + by_name["mix"]
    assert checksum == pytest.approx(346051.94, abs=0.01)


def test_november_2017_reconciliation_is_exact(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request())
    assert res.reconciliation.reconciled
    assert abs(res.reconciliation.error) < 0.01


def test_november_2017_drivers_are_not_causal(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request())
    for d in res.drivers:
        assert d.causal_claim is False
        assert d.method == "PVM"
        assert d.evidence_type == "deterministic"


# ---------------------------------------------------------------------------
# 3-6. Segment contribution reconciliation against REAL canonical data
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("segment_type", ["product_category", "customer_state", "seller_state"])
def test_segment_reconciles_exactly_against_real_data(engine, registry, segment_type):
    res = driver_engine.decompose(engine, registry, nov_2017_request(segment_dimensions=[segment_type], top_n=0))
    check = res.data_quality.segment_reconciliation[segment_type]
    assert check["reconciled"]
    assert abs(check["error"]) < 0.01
    assert check["sum_of_contributions"] == pytest.approx(346051.94, abs=0.01)


def test_seller_segment_reconciles_with_internal_clearance(engine, registry):
    res = driver_engine.decompose(
        engine, registry,
        nov_2017_request(segment_dimensions=["seller"], requester_clearance="INTERNAL", top_n=0),
    )
    check = res.data_quality.segment_reconciliation["seller"]
    assert check["reconciled"]
    assert "seller" in res.segment_contributions


def test_default_segment_dimensions_omit_seller_without_internal_clearance(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request())
    assert "seller" not in res.segment_contributions
    assert any("seller" in w for w in res.data_quality.warnings)


def test_top_n_limits_returned_segments_but_reconciliation_uses_full_set(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request(segment_dimensions=["product_category"], top_n=3))
    assert len(res.segment_contributions["product_category"]) == 3
    # reconciliation must still be against the FULL category set, not just top 3
    assert res.data_quality.segment_reconciliation["product_category"]["reconciled"]


def test_category_contribution_ranking_matches_real_top_contributors(engine, registry):
    # cross-check against the independently-computed, already-validated Step 1
    # top contributor (docs/INVESTIGATION_SCENARIOS.md §2): cama_mesa_banho
    # (English: bed_bath_table) +R$43,214.54 is the #1 category contributor.
    res = driver_engine.decompose(engine, registry, nov_2017_request(segment_dimensions=["product_category"], top_n=1))
    top = res.segment_contributions["product_category"][0]
    assert top.rank == 1
    assert top.absolute_change == pytest.approx(43214.54, abs=0.01)


# ---------------------------------------------------------------------------
# 12. Unsupported / unauthorized dimensions
# ---------------------------------------------------------------------------

def test_unsupported_dimension_name_raises(engine, registry):
    with pytest.raises(driver_engine.UnsupportedSegmentError):
        driver_engine.decompose(engine, registry, nov_2017_request(segment_dimensions=["warehouse_region"]))


def test_explicit_seller_request_without_clearance_raises(engine, registry):
    with pytest.raises(driver_engine.UnauthorizedSegmentError):
        driver_engine.decompose(engine, registry, nov_2017_request(segment_dimensions=["seller"]))


def test_non_revenue_kpi_is_rejected(engine, registry):
    with pytest.raises(driver_engine.DriverRequestError):
        driver_engine.decompose(engine, registry, nov_2017_request(kpi_id="orders"))


# ---------------------------------------------------------------------------
# 13. Numerical tolerance -- the engine MUST fail on a broken reconciliation
# ---------------------------------------------------------------------------

def test_reconcile_helper_flags_error_beyond_tolerance():
    check = driver_engine._reconcile(sum_of_contributions=100.0, actual_change=100.5, tolerance=0.01)
    assert not check.reconciled
    assert check.error == pytest.approx(-0.5)


def test_reconcile_helper_passes_within_tolerance():
    check = driver_engine._reconcile(sum_of_contributions=100.0049, actual_change=100.0, tolerance=0.01)
    assert check.reconciled


def test_engine_raises_reconciliation_error_on_a_deliberately_broken_bridge(monkeypatch, engine, registry):
    """Monkeypatch compute_pvm_bridge to return an internally-inconsistent
    bridge (volume+price+mix != delta) and verify the engine refuses to
    return it -- task §13's explicit "the engine MUST fail" requirement."""
    import drivers.engine as mod
    from drivers.pvm import PVMBridge

    def broken_bridge(items_previous, items_current):
        real = compute_pvm_bridge(items_previous, items_current)
        return PVMBridge(
            revenue_previous=real.revenue_previous, revenue_current=real.revenue_current,
            qty_previous=real.qty_previous, qty_current=real.qty_current,
            volume_effect=real.volume_effect, price_effect=real.price_effect,
            mix_effect=real.mix_effect + 10_000.0,  # deliberately break the checksum
            checksum_error=10_000.0, n_categories=real.n_categories, confidence=real.confidence,
        )

    monkeypatch.setattr(mod, "compute_pvm_bridge", broken_bridge)
    with pytest.raises(mod.ReconciliationError):
        mod.decompose(engine, registry, nov_2017_request())


# ---------------------------------------------------------------------------
# 14. causal_claim always false
# ---------------------------------------------------------------------------

def test_causal_claim_false_everywhere_in_the_result(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request(
        segment_dimensions=["product_category", "customer_state", "seller_state"], top_n=5))
    assert res.causal_claim is False
    for d in res.drivers:
        assert d.causal_claim is False
    for contributions in res.segment_contributions.values():
        for c in contributions:
            assert c.causal_claim is False


# "due to" is deliberately excluded when preceded by "excluded " -- that
# specific idiom is pre-existing Step 3B data-quality text (e.g. "153 rows
# excluded due to missing/invalid delivery timestamps", copied verbatim into
# ConcurrentKPIMovement.warnings from kpi.engine.py's own KPIResult.warnings),
# a mechanical exclusion reason, not a causal claim about a KPI movement.
CAUSAL_PATTERNS = re.compile(
    r"\b(caused by|causes|because of|(?<!excluded )due to|the reason (is|for)|as a result of|"
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


def test_no_result_contains_a_causal_claim(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request(
        segment_dimensions=["product_category", "customer_state", "seller_state"], top_n=5))
    offenders = [s for s in _all_strings(res.to_dict()) if CAUSAL_PATTERNS.search(s)]
    assert not offenders, f"causal language found in result: {offenders}"

    tree = driver_engine.build_contribution_tree(res)
    offenders_tree = [s for s in _all_strings(tree) if CAUSAL_PATTERNS.search(s)]
    assert not offenders_tree, f"causal language found in contribution tree: {offenders_tree}"


# ---------------------------------------------------------------------------
# 15. Cross-KPI package completeness (task §15/§16)
# ---------------------------------------------------------------------------

def test_concurrent_kpis_are_complete_and_match_known_november_2017_figures(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request())
    expected = {"orders", "aov", "freight_revenue", "avg_delivery_days", "avg_review_score"}
    assert set(res.concurrent_kpis.keys()) == expected

    orders = res.concurrent_kpis["orders"]
    assert orders.previous_value == 4631.0
    assert orders.current_value == 7544.0
    assert orders.percentage_change == pytest.approx(62.9, abs=0.1)

    # every concurrent KPI must carry deterministic arithmetic only -- no
    # materiality/anomaly field of any kind leaking in from Step 3C
    for movement in res.concurrent_kpis.values():
        d = movement.to_dict()
        assert "materiality" not in d and "verdict" not in d and "is_anomaly" not in d


def test_contribution_tree_matches_the_task_example_shape(engine, registry):
    res = driver_engine.decompose(engine, registry, nov_2017_request(segment_dimensions=["product_category"], top_n=3))
    tree = driver_engine.build_contribution_tree(res)
    assert set(tree.keys()) == {"kpi", "movement", "drivers", "segments", "reconciliation", "causal_claim"}
    assert tree["kpi"] == "revenue"
    assert set(tree["movement"].keys()) == {"absolute", "percentage"}
    assert {d["name"] for d in tree["drivers"]} == {"volume", "price", "mix"}
    assert "product_category" in tree["segments"]
    assert tree["causal_claim"] is False
