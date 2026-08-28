"""
evidence_tools.py — Step 5: governed unstructured/graph-evidence tools (task
§1C, §3, §16): get_evidence, get_graph_neighbors, search_evidence.

search_evidence's RETRIEVAL_INSUFFICIENT ladder (task §16) is entirely
DETERMINISTIC, reusing Step 4A's own primitives, never redesigning them:

    1. governed BM25 query (bm25_retriever.BM25Index), no expansion
    2. the SAME query, BM25's own governed bilingual expansion (expand=True)
    3. broaden structured filters ONE governed key at a time, fixed priority
       order, never touching the investigation's own month/time window
    4. optional dense E5 fallback via the existing, UNMODIFIED
       evidence.retrieval.retrieve() pipeline (off by default --
       allow_dense_fallback=False -- to avoid a model-load requirement in
       tests/CI; Step 4A already found BM25+expansion ahead of dense anyway)
    5. report insufficiency -- never pad results below either retriever's
       score floor (retriever_interface.MIN_BM25_SCORE_FLOOR /
       MIN_DENSE_SCORE_FLOOR)

This module NEVER bypasses the Evidence Fabric: candidate positions always
come from retrieval.apply_structured_filters (the same structured-first gate
Step 4's retrieval.py already enforces), and every governed-filter key is
validated by retrieval.validate_structured_filters before use -- this is the
concrete mechanism that makes an "evidence-filter bypass" attempt fail (an
unrecognized or under-clearance filter key raises before any search runs).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Optional

from evidence import pii as pii_module
from evidence import retrieval
from evidence import structured_adapter as adapter
from evidence.access_control import clearance_sufficient
from evidence.models import CLEARANCE_RANK
from evidence.retriever_interface import MIN_BM25_SCORE_FLOOR, MIN_DENSE_SCORE_FLOOR, RetrievalInsufficient
from evidence.schema import EvidenceQuery, EvidenceResult, ReviewSourceRef, RetrievalInfo, TimeRange

from tools.context import ToolContext

# Priority order for "broaden permitted structured filters if justified"
# (task §16 step 2) -- narrowest/most-identity-revealing keys dropped first,
# the investigation's own time window is NEVER in this list (broadening it
# would silently answer a different question, not the one asked).
_BROADEN_PRIORITY = ["category", "seller_state", "customer_state", "review_score_min", "review_score_max"]


def get_evidence(ctx: ToolContext, requester_clearance: str, evidence_id: str) -> dict:
    """Looks up ANY previously-produced evidence object (structured or
    review) by id. Raises KeyError if unknown, PermissionError if the
    requester's clearance is insufficient for THIS item -- both are caught
    and redacted by tools/gateway.py before reaching a low-clearance caller,
    so "the item exists but you can't see it" and "no such item" are
    indistinguishable from outside, by design.

    PII redaction (task §21 "PII extraction attempt"): a raw CUSTOMER_REVIEW
    EvidenceObject's own metadata["text"] is NOT redacted at the source (by
    design -- see evidence.review_ingestion.build_review_evidence's own
    docstring: redaction happens only at the retrieval layer, never on the
    underlying evidence). search_evidence's EvidenceResult objects already
    carry redacted `.content`; this function applies the SAME redaction here
    for a raw EvidenceObject fetched directly by id, so get_evidence can
    never be used as a PII-redaction bypass alongside search_evidence."""
    ev = ctx.evidence_store.get(evidence_id)
    if ev is None:
        raise KeyError(f"No evidence with id {evidence_id!r}.")
    classification = ev.security.classification.value
    if not clearance_sufficient(classification, requester_clearance):
        raise PermissionError(f"evidence_id {evidence_id!r} requires clearance {classification!r}.")

    dumped = ev.model_dump()
    metadata = dumped.get("metadata") or {}
    if ev.security.trust_level.value == "UNTRUSTED_DATA" and ev.security.pii_types and "text" in metadata:
        redacted = pii_module.redact_pii(str(metadata["text"]), ev.security.pii_types)
        dumped["metadata"] = {**metadata, "text": redacted}
        dumped["security"] = {**dumped["security"], "redaction_status": "REDACTED_AT_RETRIEVAL"}
    return dumped


def get_graph_neighbors(ctx: ToolContext, requester_clearance: str, node_id: str) -> list[dict]:
    """Both-direction neighbor listing over the ACCESS-CONTROLLED graph
    (evidence.graph.query_graph -> access_control.filter_graph): an
    unauthorized node is simply absent post-filter, never present-but-hidden.
    Both directions matter -- e.g. a MOVEMENT node has outgoing EXPLAINED_BY
    edges to DRIVER nodes and outgoing CONTRADICTS edges to statistical
    EVIDENCE nodes, both attached at the movement end."""
    from evidence import graph as graph_module

    g = graph_module.query_graph(ctx.graph, requester_clearance)
    if node_id not in g:
        raise KeyError(f"No node {node_id!r} visible at clearance {requester_clearance!r}.")

    neighbors = []
    for _, target, key, attrs in g.out_edges(node_id, keys=True, data=True):
        neighbors.append({"node_id": target, "direction": "outgoing", "relationship_type": attrs.get("relationship_type"),
                           "note": attrs.get("note"), **{k: v for k, v in g.nodes[target].items()}})
    for source, _, key, attrs in g.in_edges(node_id, keys=True, data=True):
        neighbors.append({"node_id": source, "direction": "incoming", "relationship_type": attrs.get("relationship_type"),
                           "note": attrs.get("note"), **{k: v for k, v in g.nodes[source].items()}})
    return neighbors


def _build_query(ctx: ToolContext, requester_clearance: str, structured_filters: dict,
                  time_range_start: Optional[str], time_range_end: Optional[str],
                  semantic_query: Optional[str] = None, top_k: int = 10) -> EvidenceQuery:
    return EvidenceQuery(
        investigation_id=ctx.investigation_id, question="", structured_filters=dict(structured_filters),
        time_range=TimeRange(start=time_range_start, end=time_range_end) if time_range_start and time_range_end else None,
        semantic_query=semantic_query, top_k=top_k, requester_clearance=requester_clearance,
    )


def _bm25_results_to_evidence(ctx: ToolContext, requester_clearance: str, scored: list,
                               method: str) -> list[str]:
    ids = []
    for rank, (pos, score) in enumerate(scored, start=1):
        meta = ctx.vector_index.metadata[pos]
        source_evidence = ctx.evidence_by_review_row_id.get(meta.review_row_id)
        if source_evidence is None:
            continue
        text = str(source_evidence.metadata.get("text", ""))
        pii_types = source_evidence.security.pii_types
        content = pii_module.redact_pii(text, pii_types) if pii_types else text
        redaction_status = "REDACTED_AT_RETRIEVAL" if pii_types else "NOT_REDACTED"
        security = source_evidence.security.model_copy(update={"redaction_status": redaction_status})
        result_id = adapter.evidence_id_for("evresult", source_evidence.evidence_id, method, rank)
        result = EvidenceResult(
            evidence_id=result_id, evidence_type=source_evidence.evidence_type, claim=source_evidence.claim,
            content=content, retrieval=RetrievalInfo(rank=rank, score=round(float(score), 6), method=method),
            source=ReviewSourceRef(review_id=meta.review_id, order_id=meta.order_id),
            metadata={k: v for k, v in source_evidence.metadata.items() if k != "text"},
            evidence_tier=source_evidence.evidence_tier, security=security, lineage=list(source_evidence.lineage),
        )
        ctx.evidence_store[result_id] = result
        ids.append(result_id)
    return ids


def search_evidence(ctx: ToolContext, requester_clearance: str, semantic_query: Optional[str] = None,
                     structured_filters: Optional[dict] = None, top_k: int = 10,
                     time_range_start: Optional[str] = None, time_range_end: Optional[str] = None,
                     allow_dense_fallback: bool = False) -> dict:
    """Returns {"sufficient": True, "evidence_ids": [...], "retrieval_method": ...}
    or {"sufficient": False, **RetrievalInsufficient fields} -- NEVER a bare
    list padded with sub-floor results (task §16: "Do not force a
    conclusion.")."""
    structured_filters = dict(structured_filters or {})
    attempts: list[str] = []

    query = _build_query(ctx, requester_clearance, structured_filters, time_range_start, time_range_end,
                          semantic_query=semantic_query, top_k=top_k)
    retrieval.validate_structured_filters(query.structured_filters, requester_clearance, ctx.registry)   # raises on bypass attempt
    positions = retrieval.apply_structured_filters(ctx.vector_index, query, requester_clearance)
    candidates_before = len(ctx.vector_index)

    def _try_bm25(pos: list, expand: bool) -> tuple:
        if not semantic_query:
            ranked = sorted(pos, key=lambda p: -ctx.vector_index.metadata[p].review_score)
            return [(p, 0.0) for p in ranked[:top_k]], "structured_filter+review_score_rank"
        scored = ctx.bm25_index.query(semantic_query, k=top_k, candidate_positions=pos, expand=expand)
        method = "bm25+expansion" if expand else "bm25"
        return scored, f"structured_filter+{method}"

    # Rung 1: governed BM25 query, no expansion.
    scored, method = _try_bm25(positions, expand=False)
    attempts.append(f"rung1 bm25 (no expansion): {len(scored)} candidate(s), best={scored[0][1] if scored else 0.0}")
    best = scored[0][1] if scored else 0.0

    # Rung 2: same query, governed bilingual expansion.
    if not scored or best < MIN_BM25_SCORE_FLOOR:
        scored2, method2 = _try_bm25(positions, expand=True)
        attempts.append(f"rung2 bm25+expansion: {len(scored2)} candidate(s), "
                         f"best={scored2[0][1] if scored2 else 0.0}")
        if scored2 and (not scored or scored2[0][1] > best):
            scored, method, best = scored2, method2, (scored2[0][1] if scored2 else 0.0)

    # Rung 3: broaden structured filters one governed key at a time.
    if (not scored or best < MIN_BM25_SCORE_FLOOR) and structured_filters:
        remaining = dict(structured_filters)
        for key in _BROADEN_PRIORITY:
            if key not in remaining:
                continue
            remaining = {k: v for k, v in remaining.items() if k != key}
            broadened_query = _build_query(ctx, requester_clearance, remaining, time_range_start, time_range_end)
            broadened_positions = retrieval.apply_structured_filters(ctx.vector_index, broadened_query, requester_clearance)
            scored3, method3 = _try_bm25(broadened_positions, expand=True)
            attempts.append(f"rung3 broadened (dropped {key!r}): {len(scored3)} candidate(s), "
                             f"best={scored3[0][1] if scored3 else 0.0}")
            if scored3 and scored3[0][1] >= MIN_BM25_SCORE_FLOOR:
                scored, method, positions, best = scored3, method3 + f"+broadened_dropped_{key}", broadened_positions, scored3[0][1]
                break

    is_bm25_sufficient = bool(scored) and best >= MIN_BM25_SCORE_FLOOR
    if is_bm25_sufficient:
        ids = _bm25_results_to_evidence(ctx, requester_clearance, scored[:top_k], method)
        return {"sufficient": True, "evidence_ids": ids, "retrieval_method": method}

    # Rung 4: optional dense fallback via the existing, unmodified pipeline.
    if allow_dense_fallback and semantic_query:
        try:
            results, telemetry = retrieval.retrieve(query, ctx.vector_index, ctx.registry,
                                                     ctx.evidence_by_review_row_id)
        except Exception as exc:   # model unavailable, offline sandbox, etc. -- never crash the investigation
            attempts.append(f"rung4 dense fallback unavailable: {exc}")
        else:
            best_dense = results[0].retrieval.score if results else 0.0
            attempts.append(f"rung4 dense fallback: {len(results)} candidate(s), best={best_dense}")
            if results and best_dense >= MIN_DENSE_SCORE_FLOOR:
                ids = []
                for r in results:
                    ctx.evidence_store[r.evidence_id] = r
                    ids.append(r.evidence_id)
                return {"sufficient": True, "evidence_ids": ids, "retrieval_method": r.retrieval.method}

    # Rung 5: report insufficiency -- never fill the gap with arbitrary reviews.
    insufficient = RetrievalInsufficient(
        candidate_count=len(positions), best_score=round(float(best), 6), retrieval_method=method,
        coverage=(len(positions) / candidates_before) if candidates_before else 0.0,
        reason="; ".join(attempts) or "no candidates matched the structured filters",
    )
    payload = asdict(insufficient)
    payload["sufficient"] = False
    return payload
