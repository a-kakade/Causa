"""
context.py — Step 5: the one reuse seam over Step 4's Evidence Fabric that
every governed tool (analytics_tools.py / evidence_tools.py) reads from.

Not one of the file names literally listed in the task spec, but a necessary
plumbing module for the same reason src/evidence/engine.py exists in Step 4:
something has to build the KPIEngine + SemanticRegistry + review corpus +
vector index + BM25 index + evidence graph ONCE per investigation and hand
governed tools a read-only handle to all of it, rather than each tool
function re-deriving its own copy.

STRICT RULE: this module NEVER computes a KPI, NEVER decides a business
conclusion, and NEVER performs access control itself -- it only assembles
handles to the REAL Step 3B/3C/3D engines and the REAL Step 4/4A evidence
fabric (evidence.engine.build_november_2017_evidence_package,
evidence.engine.build_review_index, evidence.bm25_retriever.BM25Index). Every
number a tool later returns still traces to those exact engines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import networkx as nx
import pandas as pd

from kpi.engine import KPIEngine
from kpi.semantic_registry import SemanticRegistry

from evidence import engine as evidence_engine
from evidence.bm25_retriever import BM25Index
from evidence.vector_index import FlatCosineIndex


@dataclass
class ToolContext:
    """Read-only (by convention -- nothing here is a frozen dataclass because
    `evidence_store` legitimately grows as tools run, see below) handle set
    every governed tool function receives as its first argument. Never
    exposed to an agent module directly -- only tools/gateway.py holds a
    ToolContext; agents only ever see ToolCallResult objects."""
    investigation_id: str
    kpi_engine: KPIEngine
    registry: SemanticRegistry
    canonical: dict[str, pd.DataFrame]
    review_corpus: list[Any]                      # evidence.review_ingestion.ReviewOrderJoinRow
    review_evidence: list[Any]                     # evidence.schema.EvidenceObject (CUSTOMER_REVIEW)
    evidence_by_review_row_id: dict[int, Any]
    vector_index: FlatCosineIndex
    bm25_index: BM25Index
    graph: nx.MultiDiGraph
    # evidence_id -> EvidenceObject | EvidenceResult-shaped dict. Pre-seeded
    # from the Step 4 package build; tool functions APPEND to this as they
    # run (never remove, never mutate an existing entry -- see
    # evidence_tools.py). This is the only mutable field on this dataclass.
    evidence_store: dict[str, Any] = field(default_factory=dict)
    # governed KPI coverage thresholds, read once at build time so
    # counter_evidence_agent.py can compare a KPI's own quality.coverage
    # against its contract WITHOUT holding a live SemanticRegistry handle
    # itself (agents only ever see tool results, never the registry --
    # keeps "agents only see tool results" a structural property, not a
    # convention). {kpi_id: coverage_threshold_fraction}
    coverage_thresholds: dict[str, float] = field(default_factory=dict)


def _coverage_thresholds(registry: SemanticRegistry) -> dict[str, float]:
    out = {}
    for kpi_id in registry.list_kpi_ids():
        contract = registry.get(kpi_id)
        pct = (contract.get("data_quality_requirements") or {}).get("coverage_threshold_pct")
        if pct is not None:
            out[kpi_id] = pct / 100.0
    return out


def build_tool_context(canonical: dict[str, pd.DataFrame], kpi_engine: Optional[KPIEngine] = None,
                        registry: Optional[SemanticRegistry] = None,
                        investigation_id: str = "november_2017_revenue") -> ToolContext:
    """Builds one ToolContext for an investigation. Reuses
    evidence.engine.build_november_2017_evidence_package (structured evidence
    + graph + contradiction checks) and evidence.engine.build_review_index
    (review corpus + FlatCosineIndex) rather than re-deriving either -- the
    cost is one extra pass over the October-November 2017 review window
    (~12K rows) versus reusing a single combined build, a known, documented
    inefficiency (see docs/MULTI_AGENT_ARCHITECTURE.md), not a hidden one."""
    registry = registry or SemanticRegistry.load()
    registry.validate()
    kpi_engine = kpi_engine or KPIEngine(registry=registry)

    package = evidence_engine.build_november_2017_evidence_package(canonical, kpi_engine, registry)
    review_corpus, review_evidence, evidence_by_review_row_id, vector_index, _cache = \
        evidence_engine.build_review_index(canonical)

    # BM25Index built over the IDENTICAL text_rows filter build_review_index
    # uses ([r for r in review_corpus if r.text]) so BM25 positions and
    # vector_index positions/metadata line up 1:1 by construction -- required
    # for evidence_tools.search_evidence to reuse retrieval.apply_structured_filters'
    # candidate POSITIONS against either index interchangeably.
    text_rows = [r for r in review_corpus if r.text]
    bm25_index = BM25Index.build([r.text for r in text_rows])

    evidence_store: dict[str, Any] = {}
    for ev in package.structured_evidence:
        evidence_store[ev.evidence_id] = ev
    for ev in review_evidence:
        evidence_store[ev.evidence_id] = ev

    return ToolContext(
        investigation_id=investigation_id, kpi_engine=kpi_engine, registry=registry, canonical=canonical,
        review_corpus=review_corpus, review_evidence=review_evidence,
        evidence_by_review_row_id=evidence_by_review_row_id, vector_index=vector_index, bm25_index=bm25_index,
        graph=package.graph, evidence_store=evidence_store, coverage_thresholds=_coverage_thresholds(registry),
    )
