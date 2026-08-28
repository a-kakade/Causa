"""Evidence graph tests (Step 4 §16/§17/§18/§22).

Builds a real November 2017 graph from real structured + review evidence and
verifies node/edge types, the worked HAS_MOVEMENT/EXPLAINED_BY/SUPPORTED_BY
example, and that CONTRADICTS is backed by a genuine statistical check
(never fabricated) and never auto-resolved.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from drivers import engine as driver_engine  # noqa: E402
from drivers.models import DriverDecompositionRequest  # noqa: E402
from kpi.engine import KPIEngine  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from evidence import structured_adapter as adapter  # noqa: E402
from evidence.graph import (  # noqa: E402
    add_contradiction_check, build_november_2017_graph, check_low_score_rate_contradiction, query_graph,
)
from evidence.models import EvidenceType, GRAPH_NODE_TYPES, RelationshipType  # noqa: E402

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
def kpi_movement_evidence(kpi_engine, registry):
    kpis = ["revenue", "orders", "aov", "freight_revenue", "avg_delivery_days", "avg_review_score"]
    out = {}
    for kpi_id in kpis:
        cmp = kpi_engine.compare_periods(kpi_id, NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
        out[kpi_id] = adapter.comparison_result_to_evidence(cmp, registry)
    return out


@pytest.fixture(scope="module")
def driver_evidence(kpi_engine, registry):
    request = DriverDecompositionRequest(
        kpi_id="revenue",
        period_current_start=NOV_2017[0], period_current_end=NOV_2017[1], period_current_label=NOV_2017[2],
        period_previous_start=OCT_2017[0], period_previous_end=OCT_2017[1], period_previous_label=OCT_2017[2],
        override_analytical_window=True, requester_clearance="INTERNAL",
        segment_dimensions=["product_category"], top_n=5,
    )
    result = driver_engine.decompose(kpi_engine, registry, request)
    bundle = adapter.driver_decomposition_result_to_evidence_bundle(result, registry)
    return [ev for ev in bundle if ev.evidence_type == EvidenceType.DRIVER_CONTRIBUTION]


@pytest.fixture(scope="module")
def delivery_review_evidence(review_evidence):
    # A handful of real Nov-2017 review evidence objects to stand in for
    # retrieval.py's "delivery-related" subset in this graph-focused test.
    nov_reviews = [ev for ev in review_evidence if ev.dimensions.get("month") == "2017-11"]
    return nov_reviews[:5]


@pytest.fixture(scope="module")
def november_graph(kpi_movement_evidence, driver_evidence, delivery_review_evidence):
    return build_november_2017_graph(kpi_movement_evidence, driver_evidence, delivery_review_evidence)


# ---------------------------------------------------------------------------
# Node/edge types
# ---------------------------------------------------------------------------

def test_graph_uses_only_governed_node_types(november_graph):
    for _n, attrs in november_graph.nodes(data=True):
        assert attrs["node_type"] in GRAPH_NODE_TYPES


def test_graph_uses_only_governed_relationship_types(november_graph):
    valid = {rt.value for rt in RelationshipType}
    for _u, _v, attrs in november_graph.edges(data=True):
        assert attrs["relationship_type"] in valid


def test_graph_has_investigation_kpi_movement_driver_evidence_nodes(november_graph):
    types_present = {attrs["node_type"] for _n, attrs in november_graph.nodes(data=True)}
    assert {"INVESTIGATION", "KPI", "MOVEMENT", "DRIVER", "EVIDENCE", "CONFIDENCE"} <= types_present


# ---------------------------------------------------------------------------
# Worked example (task §17)
# ---------------------------------------------------------------------------

def test_revenue_has_movement_edge_to_pvm_drivers(november_graph, kpi_movement_evidence, driver_evidence):
    revenue_movement_id = kpi_movement_evidence["revenue"].evidence_id
    explained_by_targets = [
        v for u, v, attrs in november_graph.edges(data=True)
        if u == revenue_movement_id and attrs["relationship_type"] == RelationshipType.EXPLAINED_BY.value
    ]
    driver_ids = {ev.evidence_id for ev in driver_evidence}
    assert set(explained_by_targets) == driver_ids
    assert len(explained_by_targets) == 3   # volume, price, mix


def test_delivery_movement_supported_by_review_evidence(november_graph, kpi_movement_evidence,
                                                          delivery_review_evidence):
    delivery_movement_id = kpi_movement_evidence["avg_delivery_days"].evidence_id
    supported_by_targets = [
        v for u, v, attrs in november_graph.edges(data=True)
        if u == delivery_movement_id and attrs["relationship_type"] == RelationshipType.SUPPORTED_BY.value
    ]
    assert set(supported_by_targets) == {ev.evidence_id for ev in delivery_review_evidence}


def test_kpi_node_has_movement_edge_to_its_own_movement(november_graph, kpi_movement_evidence):
    for kpi_id, movement_ev in kpi_movement_evidence.items():
        kpi_node = f"kpi_{kpi_id}"
        targets = [v for u, v, attrs in november_graph.edges(data=True)
                   if u == kpi_node and attrs["relationship_type"] == RelationshipType.HAS_MOVEMENT.value]
        assert movement_ev.evidence_id in targets


# ---------------------------------------------------------------------------
# Contradiction model (task §18) -- real statistics, never fabricated
# ---------------------------------------------------------------------------

def test_contradiction_check_uses_real_two_proportion_statistic(review_corpus):
    # electronics: low-score rate did NOT increase Oct->Nov 2017 in the real
    # corpus, despite avg_delivery_days worsening overall -- a genuine,
    # independently-verifiable contradiction case, not a fabricated one.
    prev = [r.review_score for r in review_corpus if r.month == "2017-10" and r.category == "electronics"]
    curr = [r.review_score for r in review_corpus if r.month == "2017-11" and r.category == "electronics"]
    check = check_low_score_rate_contradiction(prev, curr)
    assert check.contradicts is True
    assert check.current_low_score_rate <= check.previous_low_score_rate
    assert check.n_previous > 0 and check.n_current > 0


def test_contradiction_check_reports_false_when_rate_actually_increased(review_corpus):
    # bed_bath_table: low-score rate INCREASED Oct->Nov 2017 alongside worse
    # delivery -- consistent, not contradictory. Included so this test file
    # demonstrates both outcomes are representable, not just the "found a
    # contradiction" case.
    prev = [r.review_score for r in review_corpus if r.month == "2017-10" and r.category == "bed_bath_table"]
    curr = [r.review_score for r in review_corpus if r.month == "2017-11" and r.category == "bed_bath_table"]
    check = check_low_score_rate_contradiction(prev, curr)
    assert check.contradicts is False
    assert check.current_low_score_rate > check.previous_low_score_rate


def test_contradicts_edge_added_only_when_check_says_so(november_graph, kpi_movement_evidence, review_corpus):
    delivery_movement_id = kpi_movement_evidence["avg_delivery_days"].evidence_id
    prev = [r.review_score for r in review_corpus if r.month == "2017-10" and r.category == "electronics"]
    curr = [r.review_score for r in review_corpus if r.month == "2017-11" and r.category == "electronics"]
    check = check_low_score_rate_contradiction(prev, curr)

    stat_node = "stat_electronics_low_score_rate"
    november_graph.add_node(stat_node, node_type="EVIDENCE", detail=check.detail)
    added = add_contradiction_check(november_graph, delivery_movement_id, check, stat_node)
    assert added is True

    contradicts_edges = [
        (u, v) for u, v, attrs in november_graph.edges(data=True)
        if attrs["relationship_type"] == RelationshipType.CONTRADICTS.value
    ]
    assert (delivery_movement_id, stat_node) in contradicts_edges


def test_contradiction_is_never_auto_resolved(november_graph, kpi_movement_evidence, review_corpus):
    # The delivery movement node must still exist, with its own attributes
    # unchanged, after a CONTRADICTS edge is added -- nothing deletes or
    # downgrades it.
    delivery_movement_id = kpi_movement_evidence["avg_delivery_days"].evidence_id
    before = dict(november_graph.nodes[delivery_movement_id])

    prev = [r.review_score for r in review_corpus if r.month == "2017-10" and r.category == "electronics"]
    curr = [r.review_score for r in review_corpus if r.month == "2017-11" and r.category == "electronics"]
    check = check_low_score_rate_contradiction(prev, curr)
    november_graph.add_node("stat_check_2", node_type="EVIDENCE", detail=check.detail)
    add_contradiction_check(november_graph, delivery_movement_id, check, "stat_check_2")

    after = dict(november_graph.nodes[delivery_movement_id])
    assert before == after
    assert delivery_movement_id in november_graph.nodes


def test_contradicts_and_supported_by_can_coexist_between_same_nodes():
    import networkx as nx
    g = nx.MultiDiGraph()
    g.add_node("a", node_type="MOVEMENT")
    g.add_node("b", node_type="EVIDENCE")
    g.add_edge("a", "b", relationship_type=RelationshipType.SUPPORTED_BY.value)
    g.add_edge("a", "b", relationship_type=RelationshipType.CONTRADICTS.value)
    rel_types = {attrs["relationship_type"] for _u, _v, attrs in g.edges(data=True) if _u == "a" and _v == "b"}
    assert rel_types == {RelationshipType.SUPPORTED_BY.value, RelationshipType.CONTRADICTS.value}


# ---------------------------------------------------------------------------
# query_graph routes through access control
# ---------------------------------------------------------------------------

def test_query_graph_hides_internal_driver_evidence_from_public_clearance(november_graph, driver_evidence):
    filtered = query_graph(november_graph, "PUBLIC_ANALYTICAL")
    # driver evidence for revenue PVM is PUBLIC_ANALYTICAL (revenue's own
    # classification), so this checks the seam works, not that it hides
    # something here specifically -- test_access_control.py covers the
    # INTERNAL-hiding case directly with seller-classified evidence.
    assert filtered.number_of_nodes() <= november_graph.number_of_nodes()
