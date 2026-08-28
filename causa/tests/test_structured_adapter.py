"""Structured adapter tests (Step 4 §5/§6).

Verifies that structured_adapter.py converts REAL Step 3B/3C/3D engine output
into EvidenceObjects without recomputing anything, preserves lineage/values
exactly, and never fabricates a T4/T5 or reserved evidence type. Uses the
real KPIEngine/SemanticRegistry/anomaly.engine/drivers.engine against
data/processed/*.parquet -- same discipline as tests/test_driver_engine.py.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from anomaly import engine as anomaly_engine  # noqa: E402
from anomaly.models import AnomalyRequest, BaselineLevel, PeriodObservation  # noqa: E402
from drivers import engine as driver_engine  # noqa: E402
from drivers.models import DriverDecompositionRequest  # noqa: E402
from kpi.engine import KPIEngine  # noqa: E402
from kpi.models import KPIRequest  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from evidence import structured_adapter as adapter  # noqa: E402
from evidence.models import Confidence, EvidenceTier, EvidenceType, SecurityClassification  # noqa: E402

OCT_2017 = ("2017-10-01", "2017-10-31", "2017-10")
NOV_2017 = ("2017-11-01", "2017-11-30", "2017-11")


@pytest.fixture(scope="module")
def registry() -> SemanticRegistry:
    r = SemanticRegistry.load()
    r.validate()
    return r


@pytest.fixture(scope="module")
def kpi_engine() -> KPIEngine:
    return KPIEngine()


@pytest.fixture(scope="module")
def revenue_comparison(kpi_engine):
    return kpi_engine.compare_periods("revenue", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])


@pytest.fixture(scope="module")
def driver_result(kpi_engine, registry):
    request = DriverDecompositionRequest(
        kpi_id="revenue",
        period_current_start=NOV_2017[0], period_current_end=NOV_2017[1], period_current_label=NOV_2017[2],
        period_previous_start=OCT_2017[0], period_previous_end=OCT_2017[1], period_previous_label=OCT_2017[2],
        override_analytical_window=True, requester_clearance="INTERNAL",
        segment_dimensions=["product_category", "seller", "customer_state", "seller_state"],
        top_n=10,
    )
    return driver_engine.decompose(kpi_engine, registry, request)


@pytest.fixture(scope="module")
def anomaly_result(kpi_engine, registry):
    from calendar import monthrange
    history = []
    for month in ["2017-01", "2017-02", "2017-03", "2017-04", "2017-05", "2017-06",
                  "2017-07", "2017-08", "2017-09", "2017-10"]:
        year, mon = (int(x) for x in month.split("-"))
        start, end = f"{month}-01", f"{month}-{monthrange(year, mon)[1]:02d}"
        r = kpi_engine.compute(KPIRequest(kpi_id="revenue", start_date=start, end_date=end))
        history.append(PeriodObservation(period=month, value=r.value, sample_size=r.sample_size,
                                          coverage=r.coverage))
    nov_result = kpi_engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    request = AnomalyRequest(
        kpi_id="revenue", period="2017-11", observed_value=nov_result.value,
        observed_sample_size=nov_result.sample_size, observed_coverage=nov_result.coverage,
        levels=[BaselineLevel(level="global", label="all_revenue", history=history)],
    )
    return anomaly_engine.detect(registry, request)


# ---------------------------------------------------------------------------
# No recomputation (task §5)
# ---------------------------------------------------------------------------

def test_adapter_module_has_no_pandas_import():
    tree = ast.parse((REPO_ROOT / "src" / "evidence" / "structured_adapter.py").read_text())
    imported_modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module.split(".")[0])
    assert "pandas" not in imported_modules, "structured_adapter.py must never import pandas -- it converts already-computed results, it does not touch canonical data."
    assert "query_planner" not in imported_modules


# ---------------------------------------------------------------------------
# KPIResult / ComparisonResult -> evidence
# ---------------------------------------------------------------------------

def test_comparison_result_to_evidence_matches_november_revenue_movement(revenue_comparison, registry):
    ev = adapter.comparison_result_to_evidence(revenue_comparison, registry)
    assert ev.evidence_type == EvidenceType.KPI_MOVEMENT
    assert ev.evidence_tier == EvidenceTier.T1_DESCRIPTIVE
    assert ev.value.value == pytest.approx(346051.94, abs=0.01)
    assert ev.metadata["percentage_change"] == pytest.approx(52.1, abs=0.1)
    assert ev.security.classification == SecurityClassification.PUBLIC_ANALYTICAL


def test_kpi_result_to_evidence_preserves_lineage_verbatim(kpi_engine, registry):
    from kpi.models import KPIRequest
    result = kpi_engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    ev = adapter.kpi_result_to_evidence(result, registry)
    assert ev.lineage == [dict(item) for item in result.lineage]
    assert ev.lineage == registry.get_lineage_chain("revenue")


def test_evidence_id_is_deterministic_across_reruns(revenue_comparison, registry):
    ev1 = adapter.comparison_result_to_evidence(revenue_comparison, registry)
    ev2 = adapter.comparison_result_to_evidence(revenue_comparison, registry)
    assert ev1.evidence_id == ev2.evidence_id


# ---------------------------------------------------------------------------
# DriverDecompositionResult -> evidence
# ---------------------------------------------------------------------------

def test_driver_contribution_to_evidence_pvm_values_match_step3d(driver_result, registry):
    bundle = adapter.driver_decomposition_result_to_evidence_bundle(driver_result, registry)
    by_driver = {ev.dimensions["driver"]: ev.value.value for ev in bundle
                 if ev.evidence_type == EvidenceType.DRIVER_CONTRIBUTION}
    assert by_driver["volume"] == pytest.approx(417227.65, abs=0.01)
    assert by_driver["price"] == pytest.approx(4674.63, abs=0.01)
    assert by_driver["mix"] == pytest.approx(-75850.34, abs=0.01)
    for ev in bundle:
        if ev.evidence_type == EvidenceType.DRIVER_CONTRIBUTION:
            assert ev.evidence_tier == EvidenceTier.T2_ARITHMETIC


def test_segment_contribution_seller_evidence_is_internal_classified(driver_result, registry):
    bundle = adapter.driver_decomposition_result_to_evidence_bundle(driver_result, registry)
    seller_evidence = [ev for ev in bundle if ev.evidence_type == EvidenceType.SEGMENT_CONTRIBUTION
                        and ev.dimensions.get("segment_type") == "seller"]
    assert seller_evidence, "expected at least one seller segment_contribution evidence object"
    for ev in seller_evidence:
        assert ev.security.classification == SecurityClassification.INTERNAL


def test_segment_contribution_evidence_matches_top_category(driver_result, registry):
    bundle = adapter.driver_decomposition_result_to_evidence_bundle(driver_result, registry)
    cat_evidence = {ev.dimensions["segment_value"]: ev.value.value for ev in bundle
                    if ev.evidence_type == EvidenceType.SEGMENT_CONTRIBUTION
                    and ev.dimensions.get("segment_type") == "product_category"}
    assert cat_evidence["bed_bath_table"] == pytest.approx(43214.54, abs=1.0)


def test_concurrent_kpi_evidence_present_for_orders(driver_result, registry):
    bundle = adapter.driver_decomposition_result_to_evidence_bundle(driver_result, registry)
    concurrent = [ev for ev in bundle if ev.evidence_type == EvidenceType.CONCURRENT_KPI]
    assert any("orders" in ev.claim for ev in concurrent)
    for ev in concurrent:
        assert "not combined into a conclusion" in ev.claim


# ---------------------------------------------------------------------------
# AnomalyResult -> evidence
# ---------------------------------------------------------------------------

def test_anomaly_result_to_evidence_produces_two_types(anomaly_result, registry):
    evidences = adapter.anomaly_result_to_evidence(anomaly_result, registry)
    types = {ev.evidence_type for ev in evidences}
    assert types == {EvidenceType.ANOMALY_SIGNAL, EvidenceType.STATISTICAL_RESULT}
    for ev in evidences:
        assert ev.evidence_tier == EvidenceTier.T3_STATISTICAL


def test_anomaly_signal_evidence_verdict_is_material_or_critical(anomaly_result, registry):
    evidences = adapter.anomaly_result_to_evidence(anomaly_result, registry)
    signal = next(ev for ev in evidences if ev.evidence_type == EvidenceType.ANOMALY_SIGNAL)
    assert signal.metadata["verdict"] in ("MATERIAL", "CRITICAL")


# ---------------------------------------------------------------------------
# No fabricated T4/T5 evidence (task §1)
# ---------------------------------------------------------------------------

def test_populated_evidence_types_never_include_reserved_ones():
    from evidence.models import POPULATED_IN_STEP4
    reserved = {EvidenceType.EXTERNAL_CONTEXT, EvidenceType.BUSINESS_RULE,
                EvidenceType.CAUSAL_RESULT, EvidenceType.ACTION_RESULT}
    assert not (POPULATED_IN_STEP4 & reserved)


def test_assert_populated_rejects_reserved_type():
    with pytest.raises(ValueError, match="POPULATED_IN_STEP4"):
        adapter._assert_populated(EvidenceType.CAUSAL_RESULT)
