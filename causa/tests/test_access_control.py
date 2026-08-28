"""Access control tests (Step 4 §21/§22).

Verifies the clearance-rank policy filter over evidence objects and over
NetworkX graphs -- restricted/internal content must not leak via node
attributes, edges, aggregate counts, or error messages.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evidence.access_control import (  # noqa: E402
    clearance_sufficient, filter_evidence_objects, filter_graph, redact_error_message, safe_edge_count,
    safe_node_count,
)
from evidence.models import Confidence, EvidenceTier, EvidenceType, SecurityClassification, TrustLevel  # noqa: E402
from evidence.schema import EvidenceObject, FreshnessInfo, QualityInfo, SecurityInfo, SourceInfo, TimeRange, ValueSpec  # noqa: E402

NOW = datetime.now(timezone.utc).isoformat()


def _evidence(classification: SecurityClassification, evidence_id: str = "ev_1") -> EvidenceObject:
    return EvidenceObject(
        evidence_id=evidence_id, evidence_type=EvidenceType.SEGMENT_CONTRIBUTION,
        evidence_tier=EvidenceTier.T2_ARITHMETIC, claim="A segment moved.",
        value=ValueSpec(value=100.0, unit="BRL"), time=TimeRange(start="2017-10-01", end="2017-11-30"),
        confidence=Confidence.HIGH, source=SourceInfo(system="driver_engine", component="x"),
        freshness=FreshnessInfo(processing_time=NOW), quality=QualityInfo(),
        security=SecurityInfo(classification=classification, trust_level=TrustLevel.TRUSTED_SYSTEM),
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# clearance_sufficient / filter_evidence_objects
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("classification,clearance,expected", [
    ("PUBLIC_ANALYTICAL", "PUBLIC_ANALYTICAL", True),
    ("INTERNAL", "PUBLIC_ANALYTICAL", False),
    ("INTERNAL", "INTERNAL", True),
    ("RESTRICTED", "INTERNAL", False),
    ("RESTRICTED", "RESTRICTED", True),
])
def test_clearance_sufficient_matrix(classification, clearance, expected):
    assert clearance_sufficient(classification, clearance) is expected


def test_internal_evidence_hidden_from_public_analytical_clearance():
    evidence = [_evidence(SecurityClassification.PUBLIC_ANALYTICAL, "ev_pub"),
                _evidence(SecurityClassification.INTERNAL, "ev_int")]
    visible = filter_evidence_objects(evidence, "PUBLIC_ANALYTICAL")
    assert {e.evidence_id for e in visible} == {"ev_pub"}


def test_internal_evidence_visible_at_internal_clearance():
    evidence = [_evidence(SecurityClassification.INTERNAL, "ev_int")]
    visible = filter_evidence_objects(evidence, "INTERNAL")
    assert {e.evidence_id for e in visible} == {"ev_int"}


# ---------------------------------------------------------------------------
# filter_graph
# ---------------------------------------------------------------------------

def _sample_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    g.add_node("kpi_revenue", node_type="KPI")   # no classification -- always kept
    g.add_node("ev_pub", node_type="SEGMENT", security_classification="PUBLIC_ANALYTICAL",
               seller="abc", dimensions={"segment_type": "product_category"})
    g.add_node("ev_seller", node_type="SEGMENT", security_classification="INTERNAL",
               seller="seller_xyz123", dimensions={"segment_type": "seller", "seller": "seller_xyz123"})
    g.add_node("ev_customer", node_type="EVIDENCE", security_classification="RESTRICTED",
               customer_id="cust_1", customer_unique_id="cust_unique_1")
    g.add_edge("kpi_revenue", "ev_pub", relationship_type="HAS_MOVEMENT")
    g.add_edge("kpi_revenue", "ev_seller", relationship_type="HAS_MOVEMENT")
    g.add_edge("kpi_revenue", "ev_customer", relationship_type="HAS_MOVEMENT")
    return g


def test_restricted_node_removed_at_internal_clearance():
    g = _sample_graph()
    filtered = filter_graph(g, "INTERNAL")
    assert "ev_customer" not in filtered.nodes
    assert "ev_seller" in filtered.nodes   # INTERNAL clears INTERNAL


def test_internal_node_removed_at_public_analytical_clearance():
    g = _sample_graph()
    filtered = filter_graph(g, "PUBLIC_ANALYTICAL")
    assert "ev_seller" not in filtered.nodes
    assert "ev_pub" in filtered.nodes


def test_restricted_customer_id_never_appears_in_any_node_attrs_at_any_clearance():
    g = _sample_graph()
    for clearance in ("PUBLIC_ANALYTICAL", "INTERNAL", "RESTRICTED"):
        filtered = filter_graph(g, clearance)
        for _n, attrs in filtered.nodes(data=True):
            assert "customer_id" not in attrs
            assert "customer_unique_id" not in attrs


def test_seller_attr_stripped_below_internal_even_on_kept_node():
    g = _sample_graph()
    filtered = filter_graph(g, "PUBLIC_ANALYTICAL")
    assert "ev_pub" in filtered.nodes
    assert "seller" not in filtered.nodes["ev_pub"]


def test_seller_dimension_key_stripped_from_dimensions_dict_below_internal():
    g = nx.MultiDiGraph()
    g.add_node("ev_x", node_type="SEGMENT", security_classification="PUBLIC_ANALYTICAL",
               dimensions={"segment_type": "seller", "seller": "abc", "other": "keep_me"})
    filtered = filter_graph(g, "PUBLIC_ANALYTICAL")
    # Only the "seller" KEY (the actual seller identifier value) is stripped
    # -- "segment_type": "seller" is a taxonomy label, not a seller
    # identifier, and is not itself sensitive.
    assert filtered.nodes["ev_x"]["dimensions"] == {"segment_type": "seller", "other": "keep_me"}


def test_edges_to_removed_nodes_are_also_removed():
    g = _sample_graph()
    filtered = filter_graph(g, "PUBLIC_ANALYTICAL")
    edges = list(filtered.edges())
    assert ("kpi_revenue", "ev_seller") not in edges
    assert ("kpi_revenue", "ev_customer") not in edges
    assert ("kpi_revenue", "ev_pub") in edges


# ---------------------------------------------------------------------------
# Aggregate leakage (task §22)
# ---------------------------------------------------------------------------

def test_node_count_excludes_unauthorized_nodes():
    g = _sample_graph()
    assert safe_node_count(g, "PUBLIC_ANALYTICAL") < g.number_of_nodes()
    assert safe_node_count(g, "RESTRICTED") == g.number_of_nodes()


def test_edge_count_excludes_edges_to_unauthorized_nodes():
    g = _sample_graph()
    assert safe_edge_count(g, "PUBLIC_ANALYTICAL") < g.number_of_edges()


# ---------------------------------------------------------------------------
# Error message redaction
# ---------------------------------------------------------------------------

def test_error_message_redacts_id_looking_tokens_below_internal():
    message = "Unauthorized access to seller 53243585a1d117f5335f81a8f9be7d94"
    redacted = redact_error_message(message, "PUBLIC_ANALYTICAL")
    assert "53243585" not in redacted
    assert "[REDACTED_ID]" in redacted


def test_error_message_not_redacted_at_internal_clearance():
    message = "Unauthorized access to seller 53243585a1d117f5335f81a8f9be7d94"
    unredacted = redact_error_message(message, "INTERNAL")
    assert unredacted == message
