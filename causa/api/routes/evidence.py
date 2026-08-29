"""
routes/evidence.py — GET /api/evidence, /api/evidence/{id}, /api/evidence/graph,
/api/evidence/contradictions.

Every evidence/graph-returning route filters through
evidence.access_control.filter_evidence_objects / filter_graph using the
clearance derived server-side by get_requester_clearance -- never a second,
API-local authorization rule.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.bootstrap import EngineBundle
from api.dependencies import get_engine_bundle, get_requester_clearance
from api.serializers import evidence_object_dict, evidence_result_dict

router = APIRouter(prefix="/api/evidence", tags=["evidence"])


@router.get("")
def list_evidence(
    evidence_type: str | None = Query(default=None),
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    from evidence.access_control import filter_evidence_objects
    from evidence.schema import EvidenceObject

    objects = [v for v in bundle.ctx.evidence_store.values() if isinstance(v, EvidenceObject)]
    if evidence_type:
        objects = [o for o in objects if o.evidence_type.value == evidence_type]
    allowed = filter_evidence_objects(objects, requester_clearance)
    return {"count": len(allowed), "requester_clearance": requester_clearance,
            "evidence": [evidence_object_dict(o) for o in allowed]}


@router.get("/{evidence_id}")
def get_evidence_by_id(
    evidence_id: str,
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    from evidence.access_control import clearance_sufficient
    from evidence.schema import EvidenceObject

    obj = bundle.ctx.evidence_store.get(evidence_id)
    if obj is None:
        raise HTTPException(status_code=404, detail=f"No evidence {evidence_id!r}")
    if isinstance(obj, EvidenceObject):
        if not clearance_sufficient(obj.security.classification.value, requester_clearance):
            raise HTTPException(status_code=403, detail="Requester clearance is insufficient for this evidence item.")
        return evidence_object_dict(obj)
    return obj  # already-classified EvidenceResult-shaped dict from a prior retrieval


@router.get("/graph/full")
def get_evidence_graph(
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    from evidence.access_control import filter_graph

    g = filter_graph(bundle.ctx.graph, requester_clearance)
    nodes = [{"id": n, **attrs} for n, attrs in g.nodes(data=True)]
    edges = [{"source": u, "target": v, "key": k, **attrs} for u, v, k, attrs in g.edges(keys=True, data=True)]
    return {"requester_clearance": requester_clearance, "node_count": len(nodes), "edge_count": len(edges),
            "nodes": nodes, "edges": edges}


@router.get("/search/reviews")
def search_review_evidence(
    question: str = Query(...), semantic_query: str | None = Query(default=None),
    month: str | None = Query(default=None), category: str | None = Query(default=None), top_k: int = Query(default=10),
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    from evidence.retrieval import UnauthorizedFilterError, UnsupportedFilterError, retrieve
    from evidence.schema import EvidenceQuery

    structured_filters = {}
    if month:
        structured_filters["month"] = month
    if category:
        structured_filters["category"] = category

    query = EvidenceQuery(
        investigation_id=bundle.ctx.investigation_id, question=question, structured_filters=structured_filters,
        semantic_query=semantic_query, top_k=top_k, requester_clearance=requester_clearance,
    )
    try:
        results, telemetry = retrieve(query, bundle.ctx.vector_index, bundle.registry,
                                       bundle.ctx.evidence_by_review_row_id)
    except (UnsupportedFilterError, UnauthorizedFilterError) as exc:
        raise HTTPException(status_code=400 if isinstance(exc, UnsupportedFilterError) else 403, detail=str(exc))
    return {
        "results": [evidence_result_dict(r) for r in results],
        "telemetry": {
            "candidates_before_filter": telemetry.candidates_before_filter,
            "candidates_after_filter": telemetry.candidates_after_filter,
            "vector_searches_performed": telemetry.vector_searches_performed,
            "total_latency_ms": telemetry.total_latency_ms,
            "llm_calls_made": telemetry.llm_calls_made,
        },
    }


@router.get("/contradictions/checks")
def get_contradiction_checks(bundle: EngineBundle = Depends(get_engine_bundle)):
    # ToolContext does not carry the Step 4 package's contradiction_checks
    # directly (only its graph output) -- expose what IS real and available:
    # any CONTRADICTS-typed edges already in the governed evidence graph.
    from evidence.access_control import filter_graph

    g = filter_graph(bundle.ctx.graph, "INTERNAL")
    contradiction_edges = [
        {"source": u, "target": v, **attrs}
        for u, v, k, attrs in g.edges(keys=True, data=True)
        if attrs.get("relationship_type") == "CONTRADICTS"
    ]
    return {"contradiction_edges": contradiction_edges, "count": len(contradiction_edges)}
