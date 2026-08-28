"""
graph.py — Step 4: the Evidence Fabric's NetworkX evidence graph (task §16-19).

Nodes: INVESTIGATION, KPI, MOVEMENT, DRIVER, SEGMENT, EVIDENCE,
BUSINESS_CONTEXT, CONFIDENCE, ACTION (task §16). Edges: HAS_MOVEMENT,
EXPLAINED_BY, SUPPORTED_BY, CONTRADICTS, CONTEXTUALIZED_BY, DERIVED_FROM,
HAS_CONFIDENCE, RECOMMENDS (evidence.models.RelationshipType).

A `MultiDiGraph` is used deliberately (not `DiGraph`) so a CONTRADICTS edge
and a SUPPORTED_BY edge can coexist between the same two nodes (task §18) --
a single DiGraph would force one relationship to overwrite the other.

CONTRADICTS edges are added only by add_contradiction_check(), which runs a
real, deterministic two-proportion comparison (never a fabricated edge -- see
that function's docstring) and are never auto-resolved anywhere in this
module (task §18: "Resolution belongs to the future Investigation/Judge
layer.").

Every read path (query_graph) routes through access_control.filter_graph()
-- see that module for how leakage via nodes/edges/counts/errors is
prevented.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import networkx as nx

from evidence.access_control import filter_graph
from evidence.models import Confidence, EvidenceType, GRAPH_NODE_TYPES, RelationshipType
from evidence.schema import EvidenceObject

_NODE_TYPE_FOR_EVIDENCE_TYPE = {
    EvidenceType.KPI_OBSERVATION: "EVIDENCE",
    EvidenceType.KPI_MOVEMENT: "MOVEMENT",
    EvidenceType.DRIVER_CONTRIBUTION: "DRIVER",
    EvidenceType.SEGMENT_CONTRIBUTION: "SEGMENT",
    EvidenceType.ANOMALY_SIGNAL: "EVIDENCE",
    EvidenceType.STATISTICAL_RESULT: "EVIDENCE",
    EvidenceType.CONCURRENT_KPI: "EVIDENCE",
    EvidenceType.CUSTOMER_REVIEW: "EVIDENCE",
}


def new_graph() -> nx.MultiDiGraph:
    return nx.MultiDiGraph()


def add_evidence_node(g: nx.MultiDiGraph, evidence: EvidenceObject) -> str:
    node_type = _NODE_TYPE_FOR_EVIDENCE_TYPE.get(evidence.evidence_type, "EVIDENCE")
    assert node_type in GRAPH_NODE_TYPES
    g.add_node(
        evidence.evidence_id, node_type=node_type, evidence_type=evidence.evidence_type.value,
        evidence_tier=evidence.evidence_tier.value, claim=evidence.claim,
        value=evidence.value.value, unit=evidence.value.unit,
        security_classification=evidence.security.classification.value,
        confidence=evidence.confidence.value, dimensions=dict(evidence.dimensions),
    )
    return evidence.evidence_id


def add_kpi_node(g: nx.MultiDiGraph, kpi_id: str) -> str:
    node_id = f"kpi_{kpi_id}"
    g.add_node(node_id, node_type="KPI", kpi_id=kpi_id)
    return node_id


def add_investigation_node(g: nx.MultiDiGraph, investigation_id: str, question: str) -> str:
    node_id = f"investigation_{investigation_id}"
    g.add_node(node_id, node_type="INVESTIGATION", investigation_id=investigation_id, question=question)
    return node_id


def add_confidence_node(g: nx.MultiDiGraph, evidence_id: str, confidence: Confidence) -> str:
    node_id = f"confidence_of_{evidence_id}"
    g.add_node(node_id, node_type="CONFIDENCE", confidence=confidence.value)
    g.add_edge(evidence_id, node_id, relationship_type=RelationshipType.HAS_CONFIDENCE.value)
    return node_id


def add_edge(g: nx.MultiDiGraph, source: str, target: str, relationship_type: RelationshipType,
             note: Optional[str] = None) -> None:
    g.add_edge(source, target, relationship_type=relationship_type.value, note=note)


# ---------------------------------------------------------------------------
# November 2017 worked example (task §17)
# ---------------------------------------------------------------------------

def build_november_2017_graph(kpi_movement_evidence: dict[str, EvidenceObject],
                               driver_evidence: list[EvidenceObject],
                               delivery_review_evidence: list[EvidenceObject],
                               investigation_id: str = "november_2017_revenue",
                               question: str = "Why did Revenue move in November 2017, and what "
                                                "concurrent signals accompany that movement?") -> nx.MultiDiGraph:
    """kpi_movement_evidence: {kpi_id: KPI_MOVEMENT EvidenceObject}, one per
    tracked KPI (revenue, orders, aov, freight_revenue, avg_delivery_days,
    avg_review_score). driver_evidence: the revenue PVM DRIVER_CONTRIBUTION
    evidence (volume/price/mix). delivery_review_evidence: CUSTOMER_REVIEW
    evidence objects selected (by retrieval.py, upstream of this function) as
    delivery-related for the affected period."""
    g = new_graph()
    inv_node = add_investigation_node(g, investigation_id, question)

    movement_nodes: dict[str, str] = {}
    for kpi_id, movement_ev in kpi_movement_evidence.items():
        kpi_node = add_kpi_node(g, kpi_id)
        movement_node = add_evidence_node(g, movement_ev)
        add_edge(g, kpi_node, movement_node, RelationshipType.HAS_MOVEMENT)
        add_edge(g, inv_node, movement_node, RelationshipType.HAS_MOVEMENT)
        add_confidence_node(g, movement_node, movement_ev.confidence)
        movement_nodes[kpi_id] = movement_node

    if "revenue" in movement_nodes:
        for driver_ev in driver_evidence:
            driver_node = add_evidence_node(g, driver_ev)
            add_edge(g, movement_nodes["revenue"], driver_node, RelationshipType.EXPLAINED_BY)
            add_confidence_node(g, driver_node, driver_ev.confidence)

    if "avg_delivery_days" in movement_nodes:
        for review_ev in delivery_review_evidence:
            review_node = add_evidence_node(g, review_ev)
            add_edge(g, movement_nodes["avg_delivery_days"], review_node, RelationshipType.SUPPORTED_BY)

    return g


# ---------------------------------------------------------------------------
# Contradiction model (task §18)
# ---------------------------------------------------------------------------

@dataclass
class ContradictionCheckResult:
    previous_low_score_rate: Optional[float]
    current_low_score_rate: Optional[float]
    n_previous: int
    n_current: int
    z_score: Optional[float]
    contradicts: bool
    detail: str


def _two_proportion_z(x1: int, n1: int, x2: int, n2: int) -> Optional[float]:
    """Standard two-proportion z-test (pooled variance). A real, deterministic
    statistical computation -- not a fabricated signal. |z| > 1.96
    corresponds to the conventional 95% two-sided threshold; this function
    itself only returns the statistic, the caller decides what to do with it."""
    if n1 == 0 or n2 == 0:
        return None
    p1, p2 = x1 / n1, x2 / n2
    p_pool = (x1 + x2) / (n1 + n2)
    se = math.sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2)) if 0 < p_pool < 1 else 0.0
    if se == 0:
        return None
    return (p2 - p1) / se


def check_low_score_rate_contradiction(previous_scores: list[int], current_scores: list[int],
                                        low_score_threshold: int = 2) -> ContradictionCheckResult:
    """Compares the share of review_score <= low_score_threshold between two
    periods (e.g. October vs November 2017, restricted to one affected
    category upstream). `contradicts` is True only when the rate did NOT
    increase (flat or decreased) despite some other movement (e.g. delivery
    days) increasing -- the caller (add_contradiction_check) is responsible
    for deciding that comparison is meaningful before calling this."""
    n1, n2 = len(previous_scores), len(current_scores)
    x1 = sum(1 for s in previous_scores if s <= low_score_threshold)
    x2 = sum(1 for s in current_scores if s <= low_score_threshold)
    p1 = x1 / n1 if n1 else None
    p2 = x2 / n2 if n2 else None
    z = _two_proportion_z(x1, n1, x2, n2)

    rate_did_not_increase = p1 is not None and p2 is not None and p2 <= p1
    detail = (
        f"Low-score (<= {low_score_threshold}) rate moved from {p1} (n={n1}) to {p2} (n={n2}); "
        f"two-proportion z={z}."
    )
    return ContradictionCheckResult(
        previous_low_score_rate=p1, current_low_score_rate=p2, n_previous=n1, n_current=n2,
        z_score=z, contradicts=bool(rate_did_not_increase), detail=detail,
    )


def add_contradiction_check(g: nx.MultiDiGraph, movement_node_id: str, check: ContradictionCheckResult,
                             statistical_evidence_node_id: str) -> bool:
    """Adds a CONTRADICTS edge from `movement_node_id` to
    `statistical_evidence_node_id` only if `check.contradicts` is True. Never
    removes, downgrades, or otherwise "resolves" the movement node -- the
    edge is left in the graph for a future Investigation/Judge layer (task
    §18: "Do NOT automatically resolve contradictions.")."""
    if check.contradicts:
        add_edge(g, movement_node_id, statistical_evidence_node_id, RelationshipType.CONTRADICTS,
                 note=check.detail)
    return check.contradicts


# ---------------------------------------------------------------------------
# Access-controlled read path (task §16/§22)
# ---------------------------------------------------------------------------

def query_graph(g: nx.MultiDiGraph, requester_clearance: str) -> nx.MultiDiGraph:
    """The only sanctioned way to read a built graph from outside this
    module -- always routes through access_control.filter_graph()."""
    return filter_graph(g, requester_clearance)
