"""
evidence_package.py — Step 8: builds an EvidencePackage from real Step 4/6/7
objects.

This is the "reuse, never duplicate" integration point (task's own words):
the functions here WRAP existing evidence.schema.EvidenceObject /
causal.models.CausalResult / decision.models.ActionRecommendation instances
into story.models.EvidenceItem, copying every number verbatim. Nothing in
this module computes a KPI value, a driver contribution, or a causal
estimate -- that is Steps 3B/3D/6's job, already done upstream.

_infer_claim_type() is the one piece of genuinely new logic here: a fixed,
mechanical mapping from (evidence_type, evidence_tier) or (CausalStatus,
CausalTier) to story.models.ClaimType, documented in full in
docs/STORYTELLING_ARCHITECTURE.md and pinned by tests/test_evidence_package.py
so the mapping table is a tested contract, not just a comment.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from story.models import ClaimType, EvidenceItem, EvidencePackage


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidencePackageError(Exception):
    """Raised on a structurally invalid package build (e.g. duplicate
    evidence_id) -- never for a downstream generation/verification error."""


# ---------------------------------------------------------------------------
# ClaimType inference (the fixed mapping table)
# ---------------------------------------------------------------------------

# evidence.models.EvidenceType values that, at T1_DESCRIPTIVE tier, represent
# a directly observed/deterministically calculated fact.
_FACT_EVIDENCE_TYPES = frozenset({"KPI_OBSERVATION", "KPI_MOVEMENT", "CUSTOMER_REVIEW"})
# T2_ARITHMETIC evidence types -- an explicit analytical method (PVM etc.)
_ANALYTICAL_FINDING_EVIDENCE_TYPES = frozenset({"DRIVER_CONTRIBUTION", "SEGMENT_CONTRIBUTION"})
# T1_DESCRIPTIVE co-observation (no derivation) and T3_STATISTICAL signals --
# two things moving together, not yet a validated causal/arithmetic claim.
_ASSOCIATION_EVIDENCE_TYPES = frozenset({"CONCURRENT_KPI", "ANOMALY_SIGNAL", "STATISTICAL_RESULT"})


def _infer_claim_type_for_evidence_object(evidence_type: str, evidence_tier: str) -> ClaimType:
    if evidence_type in _FACT_EVIDENCE_TYPES:
        return ClaimType.FACT
    if evidence_type in _ANALYTICAL_FINDING_EVIDENCE_TYPES:
        return ClaimType.ANALYTICAL_FINDING
    if evidence_type in _ASSOCIATION_EVIDENCE_TYPES:
        return ClaimType.ASSOCIATION
    return ClaimType.UNKNOWN  # a reserved/unpopulated evidence_type (EXTERNAL_CONTEXT, BUSINESS_RULE, ...)


# causal.models.CausalStatus values -> ClaimType. A CausalResult never
# licenses an outright "caused" claim even when CAUSAL_SUPPORTED
# (causal_claim_allowed is a distinct, separately-checked gate) -- this
# mapping stays at ANALYTICAL_FINDING (a validated, method-backed finding),
# never a hidden upgrade to a "FACT" of causation. See
# docs/STORYTELLING_ARCHITECTURE.md for the full rationale.
_CAUSAL_STATUS_TO_CLAIM_TYPE: dict[str, ClaimType] = {
    "CAUSAL_SUPPORTED": ClaimType.ANALYTICAL_FINDING,
    "ARITHMETIC_ONLY": ClaimType.ANALYTICAL_FINDING,
    "DESCRIPTIVE_ONLY": ClaimType.FACT,
    "CAUSAL_INSUFFICIENT": ClaimType.HYPOTHESIS,
    "CAUSAL_REJECTED": ClaimType.UNKNOWN,
}


def _infer_claim_type_for_causal_result(status: str) -> ClaimType:
    return _CAUSAL_STATUS_TO_CLAIM_TYPE.get(status, ClaimType.UNKNOWN)


# ---------------------------------------------------------------------------
# Item builders -- one per source object type
# ---------------------------------------------------------------------------


def evidence_item_from_evidence_object(obj: Any) -> EvidenceItem:
    """obj: evidence.schema.EvidenceObject (pydantic). Every scalar copied
    verbatim from obj -- no recomputation."""
    evidence_type = obj.evidence_type.value if hasattr(obj.evidence_type, "value") else str(obj.evidence_type)
    evidence_tier = obj.evidence_tier.value if hasattr(obj.evidence_tier, "value") else str(obj.evidence_tier)
    confidence = obj.confidence.value if hasattr(obj.confidence, "value") else obj.confidence
    metric = obj.dimensions.get("metric") or obj.metadata.get("kpi_id") or obj.claim.split(" ")[0]
    return EvidenceItem(
        evidence_id=obj.evidence_id, metric=metric, value=obj.value.value if obj.value else None,
        unit=obj.value.unit if obj.value else None, direction=obj.dimensions.get("direction"),
        period=f"{obj.time.start}..{obj.time.end}", source_system=obj.source.system,
        timestamp=obj.created_at, analytical_method=obj.source.component,
        confidence=confidence, claim_type=_infer_claim_type_for_evidence_object(evidence_type, evidence_tier),
        evidence_type=evidence_type, evidence_tier=evidence_tier,
        supporting_evidence=[r.target_evidence_id for r in obj.relationships],
        limitations=[], source_evidence_object=obj,
    )


def evidence_item_from_causal_result(result: Any, kpi_id: str, period: str) -> EvidenceItem:
    """result: causal.models.CausalResult. Every scalar copied verbatim."""
    status = result.status.value if hasattr(result.status, "value") else str(result.status)
    tier = result.evidence_tier.value if hasattr(result.evidence_tier, "value") else str(result.evidence_tier)
    method = result.method.value if hasattr(result.method, "value") else str(result.method)
    value = None
    if result.estimate:
        for key in ("value", "volume_effect", "price_effect", "mix_effect"):
            if key in result.estimate and isinstance(result.estimate[key], (int, float)):
                value = result.estimate[key]
                break
    return EvidenceItem(
        evidence_id=result.hypothesis_id, metric=kpi_id, value=value, unit=None, direction=None,
        period=period, source_system="causal_engine", timestamp=_now_iso(), analytical_method=method,
        confidence=None,  # CausalResult carries no numeric or categorical confidence field -- never fabricated
        claim_type=_infer_claim_type_for_causal_result(status), evidence_type="CAUSAL_RESULT", evidence_tier=tier,
        supporting_evidence=list(result.evidence_ids), limitations=list(result.limitations),
        source_causal_result=result,
    )


def evidence_item_from_action_recommendation(rec: Any, period: str = "") -> EvidenceItem:
    """rec: decision.models.ActionRecommendation. Every scalar copied
    verbatim -- recommendations are not assigned a ClaimType in the
    epistemic sense (they are cited by recommendation_id, not narrated as a
    claim about a measurement); UNKNOWN is used here only as a structural
    placeholder since EvidenceItem.claim_type is non-optional, never
    interpreted as "insufficient evidence" for a recommendation. `period`
    defaults to the empty string when the caller has no better period to
    supply (a recommendation is not itself period-scoped the way a KPI
    observation is) -- never fabricated."""
    impact = rec.expected_impact
    return EvidenceItem(
        evidence_id=rec.recommendation_id, metric=impact.metric, value=impact.calculated_impact,
        unit=impact.effect_unit, direction=None, period=period, source_system="decision_engine",
        timestamp=_now_iso(), analytical_method="decision_pipeline",
        confidence=rec.score_breakdown.confidence_score, claim_type=ClaimType.UNKNOWN,
        evidence_type="ACTION_RESULT", evidence_tier=None, supporting_evidence=[],
        limitations=list(rec.assumptions), source_recommendation=rec,
    )


# ---------------------------------------------------------------------------
# Package builder
# ---------------------------------------------------------------------------


def _content_hash(items: list[EvidenceItem], recommendations: list[Any]) -> str:
    payload = json.dumps(
        {"items": [i.to_dict() for i in items],
         "recommendations": [r.to_dict() if hasattr(r, "to_dict") else str(r) for r in recommendations]},
        sort_keys=True, default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_evidence_package(
    kpi_id: str, period: str,
    evidence_objects: Optional[list[Any]] = None,
    causal_results: Optional[list[tuple[Any, str, str]]] = None,  # (CausalResult, kpi_id, period) tuples
    recommendations: Optional[list[Any]] = None,
    package_id: Optional[str] = None, version: str = "1.0",
) -> EvidencePackage:
    evidence_objects = evidence_objects or []
    causal_results = causal_results or []
    recommendations = recommendations or []

    items: list[EvidenceItem] = []
    for obj in evidence_objects:
        items.append(evidence_item_from_evidence_object(obj))
    for causal_result, c_kpi_id, c_period in causal_results:
        items.append(evidence_item_from_causal_result(causal_result, c_kpi_id, c_period))

    seen_ids = set()
    for item in items:
        if item.evidence_id in seen_ids:
            raise EvidencePackageError(f"Duplicate evidence_id in package: {item.evidence_id!r}")
        seen_ids.add(item.evidence_id)

    seen_rec_ids = set()
    for rec in recommendations:
        if rec.recommendation_id in seen_rec_ids:
            raise EvidencePackageError(f"Duplicate recommendation_id in package: {rec.recommendation_id!r}")
        seen_rec_ids.add(rec.recommendation_id)
        # Also wrapped as an EvidenceItem (not just kept in .recommendations) so
        # numeric_verifier.build_evidence_value_index() can match a narrative
        # claim's number against the recommendation's real expected_impact/
        # confidence -- otherwise a claim citing a recommendation's own
        # verbatim numbers would have nothing to verify against.
        items.append(evidence_item_from_action_recommendation(rec, period=period))

    return EvidencePackage(
        package_id=package_id or f"pkg_{kpi_id}_{period}", kpi_id=kpi_id, period=period, items=items,
        recommendations=list(recommendations), version=version,
        content_hash=_content_hash(items, recommendations), created_at=_now_iso(),
    )
