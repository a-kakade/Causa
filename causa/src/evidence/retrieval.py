"""
retrieval.py — Step 4: structured-first retrieval (task §13/§14/§15/§25).

Mandatory pipeline order, enforced by this module's own control flow (never
by convention alone):

    EvidenceQuery
        -> validate_structured_filters()   (governed dimensions only, no bypass)
        -> apply_structured_filters()      (candidate subset of the vector index)
        -> semantic search WITHIN that subset only, if a semantic_query is given
        -> drop below minimum_relevance
        -> reranking.py (MMR or metadata-diversity)
        -> wrap into EvidenceResult, with PII redaction applied HERE (never
           mutating the underlying EvidenceObject or cached text)

Zero LLM calls anywhere in this module (task §25) -- RetrievalTelemetry
carries `llm_calls_made=0` as a literal, permanently-zero field so a test can
assert on it, not just document it.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from evidence import pii as pii_module
from evidence.embeddings import embed_query
from evidence.models import CLEARANCE_RANK, SecurityStatus
from evidence.reranking import DEFAULT_MMR_LAMBDA, deterministic_metadata_diversity_rerank, mmr_rerank
from evidence.schema import EvidenceObject, EvidenceQuery, EvidenceResult, ReviewSourceRef, RetrievalInfo
from evidence.vector_index import FlatCosineIndex

# Governed KPI dimension names a structured_filters key maps to, checked via
# SemanticRegistry against a review-bearing KPI's own contract. "revenue" is
# used as the reference contract because it supports every governed
# dimension a review can be filtered by (month/product_category/
# customer_state/seller_state/seller) -- avg_review_score's own contract
# explicitly REFUSES product_category/seller/seller_state (see
# config/kpis.yaml), so it can't be the reference for those keys; using
# revenue's contract does not imply reviews are being joined at revenue's
# grain, it is only the governed source of dimension-level security
# classifications.
REFERENCE_KPI_FOR_DIMENSION_SECURITY = "revenue"
FILTER_KEY_TO_KPI_DIMENSION = {
    "month": "month", "category": "product_category", "seller": "seller",
    "customer_state": "customer_state", "seller_state": "seller_state",
}
# Review-pipeline-only filter keys: not a KPI dimension, so not looked up in
# SemanticRegistry, but explicitly whitelisted rather than silently allowed.
ALLOWED_REVIEW_FILTER_KEYS = {
    "language", "security_status", "category_attribution_method",
    "review_score_min", "review_score_max",
}


class UnsupportedFilterError(ValueError):
    pass


class UnauthorizedFilterError(PermissionError):
    pass


def validate_structured_filters(structured_filters: dict[str, str], requester_clearance: str, registry: Any) -> None:
    """Raises if a filter key is neither a governed KPI dimension nor a
    recognized review-pipeline key, or if the requester's clearance is below
    a governed dimension's security_classification (task §14: "Do not allow
    a caller to bypass governed KPI dimensions.")."""
    for key in structured_filters:
        if key in FILTER_KEY_TO_KPI_DIMENSION:
            dim_name = FILTER_KEY_TO_KPI_DIMENSION[key]
            dim = registry.get_dimension(REFERENCE_KPI_FOR_DIMENSION_SECURITY, dim_name)
            if dim is None or not dim.get("supported", False):
                raise UnsupportedFilterError(
                    f"structured_filters key {key!r} maps to dimension {dim_name!r}, which "
                    f"{REFERENCE_KPI_FOR_DIMENSION_SECURITY!r} does not support."
                )
            classification = dim["security_classification"]
            if CLEARANCE_RANK.get(requester_clearance, 0) < CLEARANCE_RANK.get(classification, 0):
                raise UnauthorizedFilterError(
                    f"structured_filters key {key!r} requires clearance {classification!r}; "
                    f"requester has {requester_clearance!r}."
                )
        elif key not in ALLOWED_REVIEW_FILTER_KEYS:
            raise UnsupportedFilterError(
                f"structured_filters key {key!r} is neither a governed KPI dimension nor a recognized "
                f"review-pipeline filter key ({sorted(ALLOWED_REVIEW_FILTER_KEYS)})."
            )


def _matches_filters(meta, structured_filters: dict[str, str]) -> bool:
    for key, value in structured_filters.items():
        if key == "review_score_min":
            if meta.review_score < int(value):
                return False
        elif key == "review_score_max":
            if meta.review_score > int(value):
                return False
        elif key == "category":
            if meta.category != value:
                return False
        else:
            field_name = key
            if getattr(meta, field_name, None) != value:
                return False
    return True


def apply_structured_filters(index: FlatCosineIndex, query: EvidenceQuery, requester_clearance: str) -> list[int]:
    """Returns candidate POSITIONS in `index` -- never text, never vectors --
    matching structured_filters/time_range/clearance. This is what makes
    "structured filter before semantic search" concrete: the semantic search
    step below only ever sees these positions, never the full index."""
    positions = []
    below_internal = CLEARANCE_RANK.get(requester_clearance, 0) < CLEARANCE_RANK["INTERNAL"]
    for i, meta in enumerate(index.metadata):
        if meta.security_status == SecurityStatus.BLOCKED.value:
            continue
        if below_internal and meta.seller is not None:
            continue
        if query.time_range and meta.month:
            if not (query.time_range.start[:7] <= meta.month <= query.time_range.end[:7]):
                continue
        if not _matches_filters(meta, query.structured_filters):
            continue
        positions.append(i)
    return positions


@dataclass
class RetrievalTelemetry:
    candidates_before_filter: int
    candidates_after_filter: int
    vector_searches_performed: int = 0
    embedding_cache_hits: int = 0
    embedding_cache_misses: int = 0
    structured_filter_latency_ms: float = 0.0
    semantic_search_latency_ms: float = 0.0
    reranking_latency_ms: float = 0.0
    total_latency_ms: float = 0.0
    estimated_embedding_cost_usd: float = 0.0
    llm_calls_made: int = 0


def retrieve(query: EvidenceQuery, index: FlatCosineIndex, registry: Any,
             evidence_by_review_row_id: dict[int, EvidenceObject],
             mmr_lambda: float = DEFAULT_MMR_LAMBDA) -> tuple[list[EvidenceResult], RetrievalTelemetry]:
    """The one governed entry point into the review vector index. Returns
    (results, telemetry) -- never a bare list of strings, always paired with
    provenance and cost/latency accounting (task §15/§25)."""
    t_start = time.perf_counter()
    requester_clearance = query.requester_clearance.value

    validate_structured_filters(query.structured_filters, requester_clearance, registry)

    t0 = time.perf_counter()
    candidates_before = len(index)
    candidate_positions = apply_structured_filters(index, query, requester_clearance)
    t1 = time.perf_counter()
    candidates_after = len(candidate_positions)

    cache_hits_before = _cache_hits_of(index)
    vector_searches = 0
    if query.semantic_query:
        query_vector = embed_query(query.semantic_query)
        vector_searches = 1
        pool_size = max(query.top_k * 5, query.top_k)
        scored = index.search(query_vector, k=pool_size, candidate_positions=candidate_positions)
        scored = [(pos, score) for pos, score in scored if score >= query.minimum_relevance]
    else:
        scored = [(pos, 0.0) for pos in
                  sorted(candidate_positions, key=lambda p: -index.metadata[p].review_score)]
    t2 = time.perf_counter()

    if query.semantic_query:
        reranked = mmr_rerank(index.vectors, scored, k=query.top_k, lambda_param=mmr_lambda)
        method = "structured_filter+semantic_e5_cosine+mmr_rerank"
    else:
        reranked = deterministic_metadata_diversity_rerank(
            scored, diversity_key=lambda pos: index.metadata[pos].category, k=query.top_k)
        method = "structured_filter+metadata_diversity_rerank"
    t3 = time.perf_counter()

    results: list[EvidenceResult] = []
    for rank, (pos, score) in enumerate(reranked, start=1):
        meta = index.metadata[pos]
        source_evidence = evidence_by_review_row_id.get(meta.review_row_id)
        if source_evidence is None:
            continue
        text = str(source_evidence.metadata.get("text", ""))
        pii_types = source_evidence.security.pii_types
        content = pii_module.redact_pii(text, pii_types) if pii_types else text
        redaction_status = "REDACTED_AT_RETRIEVAL" if pii_types else "NOT_REDACTED"

        security = source_evidence.security.model_copy(update={"redaction_status": redaction_status})
        results.append(EvidenceResult(
            evidence_id=source_evidence.evidence_id,
            evidence_type=source_evidence.evidence_type,
            claim=source_evidence.claim,
            content=content,
            retrieval=RetrievalInfo(rank=rank, score=round(float(score), 6), method=method),
            source=ReviewSourceRef(review_id=meta.review_id, order_id=meta.order_id),
            metadata={k: v for k, v in source_evidence.metadata.items() if k != "text"},
            evidence_tier=source_evidence.evidence_tier,
            security=security,
            lineage=list(source_evidence.lineage),
        ))

    t_end = time.perf_counter()
    cache_hits_after = _cache_hits_of(index)

    telemetry = RetrievalTelemetry(
        candidates_before_filter=candidates_before,
        candidates_after_filter=candidates_after,
        vector_searches_performed=vector_searches,
        embedding_cache_hits=max(0, cache_hits_after - cache_hits_before),
        embedding_cache_misses=0,
        structured_filter_latency_ms=round((t1 - t0) * 1000, 3),
        semantic_search_latency_ms=round((t2 - t1) * 1000, 3),
        reranking_latency_ms=round((t3 - t2) * 1000, 3),
        total_latency_ms=round((t_end - t_start) * 1000, 3),
        estimated_embedding_cost_usd=0.0,
        llm_calls_made=0,
    )
    return results, telemetry


def _cache_hits_of(index: FlatCosineIndex) -> int:
    # The index itself doesn't own an embedding cache (embeddings.py's
    # EmbeddingCache is separate and only used for building the index, not
    # for query-time embedding), so query-time cache stats are 0 unless a
    # caller wires one in. Kept as a seam rather than removed, since
    # `embed_query` calls could be cached in a future iteration.
    return 0
