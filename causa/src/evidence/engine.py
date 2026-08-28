"""
engine.py — Step 4: orchestration entry point for the Evidence Fabric
(task §6/§28).

build_november_2017_evidence_package() is the one function that ties
everything in src/evidence/ together: it calls the REAL Step 3B/3C/3D
engines (never recomputing anything itself), converts their output via
structured_adapter.py, runs the review pipeline over the October-November
2017 investigation window, retrieves four named review evidence subsets via
retrieval.py, and assembles the NetworkX graph via graph.py.

Scope note: the review pipeline here is bounded to the October-November 2017
window (the investigation's own scope), not the full historical corpus --
consistent with the test fixtures in tests/conftest.py and documented in
docs/EVIDENCE_FABRIC.md. A full-corpus build is possible (pass a wider
`review_months` set) but is not needed for this investigation and would cost
several minutes of embedding time for no benefit here.

STRICT BOUNDARY (task §31): this module NEVER decides whether a hypothesis
is true, infers a root cause, or drafts a narrative. It ends at a graph of
governed evidence -- constructing an actual investigative conclusion from
that graph is Step 5's job.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import networkx as nx
import pandas as pd

from anomaly import engine as anomaly_engine
from anomaly.models import AnomalyRequest, BaselineLevel, PeriodObservation
from drivers import engine as driver_engine
from drivers.models import DriverDecompositionRequest
from kpi.engine import KPIEngine
from kpi.models import KPIRequest
from kpi.semantic_registry import SemanticRegistry

from evidence import graph as graph_module
from evidence import retrieval, structured_adapter as adapter
from evidence.embeddings import EmbeddingCache, embed_reviews_batch, get_model
from evidence.language import detect_language
from evidence.reranking import DEFAULT_MMR_LAMBDA
from evidence.review_ingestion import build_review_evidence, build_review_order_join
from evidence.safety import classify_safety
from evidence.schema import EvidenceObject, EvidenceQuery, EvidenceResult, TimeRange
from evidence.vector_index import FlatCosineIndex, VectorIndexMetadata

OCT_2017 = ("2017-10-01", "2017-10-31", "2017-10")
NOV_2017 = ("2017-11-01", "2017-11-30", "2017-11")
INVESTIGATION_ID = "november_2017_revenue"
TRACKED_KPIS = ("revenue", "orders", "aov", "freight_revenue", "avg_delivery_days", "avg_review_score")
BASELINE_HISTORY_MONTHS = (
    "2017-01", "2017-02", "2017-03", "2017-04", "2017-05", "2017-06",
    "2017-07", "2017-08", "2017-09", "2017-10",
)


@dataclass
class EvidencePackage:
    investigation_id: str
    structured_evidence: list[EvidenceObject] = field(default_factory=list)
    review_evidence: list[EvidenceObject] = field(default_factory=list)
    retrieval_results: dict[str, list[EvidenceResult]] = field(default_factory=dict)
    retrieval_telemetry: dict[str, retrieval.RetrievalTelemetry] = field(default_factory=dict)
    graph: nx.MultiDiGraph = field(default_factory=nx.MultiDiGraph)
    contradiction_checks: dict[str, "graph_module.ContradictionCheckResult"] = field(default_factory=dict)


def _month_bounds(month: str) -> tuple[str, str]:
    from calendar import monthrange
    year, mon = (int(x) for x in month.split("-"))
    return f"{month}-01", f"{month}-{monthrange(year, mon)[1]:02d}"


def _build_kpi_movement_evidence(kpi_engine: KPIEngine, registry: SemanticRegistry) -> dict[str, EvidenceObject]:
    out = {}
    for kpi_id in TRACKED_KPIS:
        cmp = kpi_engine.compare_periods(kpi_id, NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
        out[kpi_id] = adapter.comparison_result_to_evidence(cmp, registry)
    return out


def _build_anomaly_evidence(kpi_engine: KPIEngine, registry: SemanticRegistry) -> list[EvidenceObject]:
    history = []
    for month in BASELINE_HISTORY_MONTHS:
        start, end = _month_bounds(month)
        r = kpi_engine.compute(KPIRequest(kpi_id="revenue", start_date=start, end_date=end))
        history.append(PeriodObservation(period=month, value=r.value, sample_size=r.sample_size,
                                          coverage=r.coverage))
    nov_result = kpi_engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    request = AnomalyRequest(
        kpi_id="revenue", period="2017-11", observed_value=nov_result.value,
        observed_sample_size=nov_result.sample_size, observed_coverage=nov_result.coverage,
        levels=[BaselineLevel(level="global", label="all_revenue", history=history)],
    )
    result = anomaly_engine.detect(registry, request)
    return adapter.anomaly_result_to_evidence(result, registry)


def _build_driver_evidence(kpi_engine: KPIEngine, registry: SemanticRegistry):
    request = DriverDecompositionRequest(
        kpi_id="revenue",
        period_current_start=NOV_2017[0], period_current_end=NOV_2017[1], period_current_label=NOV_2017[2],
        period_previous_start=OCT_2017[0], period_previous_end=OCT_2017[1], period_previous_label=OCT_2017[2],
        override_analytical_window=True, requester_clearance="INTERNAL",
        segment_dimensions=["product_category", "seller", "customer_state", "seller_state"],
        top_n=10,
    )
    result = driver_engine.decompose(kpi_engine, registry, request)
    bundle = adapter.driver_decomposition_result_to_evidence_bundle(result, registry)
    return bundle, result


def build_review_index(canonical: dict[str, pd.DataFrame], months=("2017-10", "2017-11")):
    # Force the embedding model to load HERE, unconditionally -- if
    # embed_reviews_batch below hits the disk cache for every row (0
    # misses), it never calls get_model() itself, which would otherwise
    # silently defer the ~10s one-time model-load cost to whichever
    # retrieval query happens to run the first semantic search, making that
    # query's telemetry misleadingly slow. Paying the cost predictably here
    # keeps per-query semantic_search_latency_ms numbers comparable.
    get_model()

    fact_reviews, fact_orders = canonical["fact_reviews"], canonical["fact_orders"]
    merged_months = fact_reviews.merge(fact_orders[["order_id", "purchase_timestamp"]], on="order_id", how="left")
    month = merged_months["purchase_timestamp"].dt.strftime("%Y-%m")
    in_window = fact_reviews[month.isin(months)].reset_index(drop=True)

    review_corpus = build_review_order_join(
        in_window, fact_orders, canonical["fact_order_items"], canonical["dim_product"], canonical["dim_seller"])
    review_evidence = [build_review_evidence(row) for row in review_corpus]
    evidence_by_review_row_id = {row.review_row_id: ev for row, ev in zip(review_corpus, review_evidence)}

    text_rows = [r for r in review_corpus if r.text]
    cache = EmbeddingCache()
    vectors = embed_reviews_batch([r.text for r in text_rows], cache)
    cache.save()
    metadata = [
        VectorIndexMetadata(
            review_row_id=r.review_row_id, review_id=r.review_id, order_id=r.order_id, month=r.month,
            category=r.category, seller=r.seller, customer_state=r.customer_state, seller_state=r.seller_state,
            review_score=r.review_score, language=detect_language(r.text).language,
            security_status=classify_safety(r.text).security_status,
        )
        for r in text_rows
    ]
    index = FlatCosineIndex.build(vectors, metadata)
    return review_corpus, review_evidence, evidence_by_review_row_id, index, cache


def build_november_2017_evidence_package(canonical: dict[str, pd.DataFrame], kpi_engine: KPIEngine,
                                          registry: SemanticRegistry) -> EvidencePackage:
    package = EvidencePackage(investigation_id=INVESTIGATION_ID)

    kpi_movement_evidence = _build_kpi_movement_evidence(kpi_engine, registry)
    anomaly_evidence = _build_anomaly_evidence(kpi_engine, registry)
    driver_bundle, driver_result = _build_driver_evidence(kpi_engine, registry)

    package.structured_evidence = list(kpi_movement_evidence.values()) + anomaly_evidence + driver_bundle

    review_corpus, review_evidence, evidence_by_row_id, index, _cache = build_review_index(canonical)
    package.review_evidence = review_evidence

    top_category = driver_result.segment_contributions["product_category"][0].segment_value

    # Most individual reviews resolve to exactly one seller (single_item_order
    # / single_category_order attribution -- ~97% of the corpus), and
    # review_ingestion.py classifies any review with an attributed seller as
    # INTERNAL (same rule the KPI/driver layers apply to the `seller`
    # dimension elsewhere). This investigation is an internal analysis --
    # the driver decomposition above already runs at INTERNAL clearance for
    # the same reason -- so its review queries do too. A PUBLIC_ANALYTICAL
    # caller would instead see only reviews from ambiguous/no-item orders;
    # see docs/RAG_GOVERNANCE.md.
    requester_clearance = "INTERNAL"
    queries = {
        "delivery_related": EvidenceQuery(
            investigation_id=INVESTIGATION_ID, question="Which reviews describe delivery delays in November 2017?",
            structured_filters={"month": "2017-11"}, semantic_query="atraso na entrega, demora", top_k=10,
            requester_clearance=requester_clearance,
        ),
        "low_score": EvidenceQuery(
            investigation_id=INVESTIGATION_ID, question="What are the lowest-scored reviews in November 2017?",
            structured_filters={"month": "2017-11", "review_score_max": "2"}, top_k=10,
            requester_clearance=requester_clearance,
        ),
        "category_specific": EvidenceQuery(
            investigation_id=INVESTIGATION_ID,
            question=f"What do customers say about {top_category} in November 2017?",
            structured_filters={"month": "2017-11", "category": top_category}, top_k=10,
            requester_clearance=requester_clearance,
        ),
        "product_quality": EvidenceQuery(
            investigation_id=INVESTIGATION_ID,
            question="Which reviews describe product quality or defect complaints in November 2017?",
            structured_filters={"month": "2017-11"}, semantic_query="produto com defeito, qualidade ruim",
            top_k=10, requester_clearance=requester_clearance,
        ),
    }
    for name, query in queries.items():
        results, telemetry = retrieval.retrieve(query, index, registry, evidence_by_row_id,
                                                 mmr_lambda=DEFAULT_MMR_LAMBDA)
        package.retrieval_results[name] = results
        package.retrieval_telemetry[name] = telemetry

    driver_evidence_only = [ev for ev in driver_bundle if ev.evidence_type.value == "DRIVER_CONTRIBUTION"]
    delivery_review_evidence = [evidence_by_row_id[r.review_row_id]
                                 for r in [rr for rr in review_corpus if rr.month == "2017-11"][:5]]
    g = graph_module.build_november_2017_graph(kpi_movement_evidence, driver_evidence_only,
                                                delivery_review_evidence, investigation_id=INVESTIGATION_ID)

    # Check every top-mover category with enough sample to be meaningful
    # (not just the single largest one) -- whether a contradiction exists is
    # a real, data-dependent outcome, not something engine.py should assume
    # in advance. Every check performed is recorded on the package (found a
    # contradiction or not) for full transparency in the validation report.
    delivery_movement_id = kpi_movement_evidence["avg_delivery_days"].evidence_id
    top_categories = [c.segment_value for c in driver_result.segment_contributions["product_category"]]
    for category in top_categories:
        prev_scores = [r.review_score for r in review_corpus if r.month == "2017-10" and r.category == category]
        curr_scores = [r.review_score for r in review_corpus if r.month == "2017-11" and r.category == category]
        if len(prev_scores) < 15 or len(curr_scores) < 15:
            continue
        check = graph_module.check_low_score_rate_contradiction(prev_scores, curr_scores)
        package.contradiction_checks[category] = check
        stat_node_id = f"stat_{category}_low_score_rate"
        g.add_node(stat_node_id, node_type="EVIDENCE", detail=check.detail,
                   security_classification="PUBLIC_ANALYTICAL")
        graph_module.add_contradiction_check(g, delivery_movement_id, check, stat_node_id)
    package.graph = g

    return package
