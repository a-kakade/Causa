"""
schema.py — Step 4: the strict, machine-readable Evidence Fabric schema
(task §3/§4/§14/§15).

Every model here uses `model_config = ConfigDict(extra="forbid")`: no caller,
adapter, or future agent may attach an arbitrary field to an evidence object.
The only two genuinely open-ended containers (`EvidenceObject.dimensions` and
`EvidenceObject.metadata` / `EvidenceResult.metadata`) are bounded to flat
dicts of primitive values by a field_validator, so `extra="forbid"` can't be
routed around by stuffing an unvalidated nested object into one of them.

This module holds zero calculation logic and zero hashing/ID-generation logic
(that lives in structured_adapter.py / review_ingestion.py, the two places
that actually build EvidenceObjects) -- same "definitions only" posture as
src/kpi/models.py, src/anomaly/models.py, src/drivers/models.py.

Claim vs Evidence (task §4): a Claim is a distinct, separately-validated type
that points at evidence by id (`supported_by`). Nothing in this package
auto-populates a Claim with real business content -- Step 4 only proves the
type exists and is usable; assembling an actual claim from evidence is Step
5's job (task §31: "Do NOT ... decide whether a hypothesis is true").
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

from evidence.models import (
    CAUSAL_LANGUAGE_PATTERN,
    Confidence,
    EvidenceTier,
    EvidenceType,
    RelationshipType,
    SecurityClassification,
    SecurityStatus,
    TrustLevel,
)

Primitive = Union[str, int, float, bool, None]


def _reject_causal_language(v: str, field_name: str) -> str:
    if CAUSAL_LANGUAGE_PATTERN.search(v):
        raise ValueError(
            f"{field_name} contains causal language ({CAUSAL_LANGUAGE_PATTERN.pattern!r} matched). "
            "Evidence claims may describe an observed movement, an arithmetic decomposition, or a "
            "statistical signal -- never assert why something happened (task §31)."
        )
    return v


def _reject_nested(v: dict[str, Primitive], field_name: str) -> dict[str, Primitive]:
    for key, val in v.items():
        if isinstance(val, (dict, list, tuple, set)):
            raise ValueError(
                f"{field_name}[{key!r}] is a nested {type(val).__name__}; {field_name} must be a flat "
                "dict of primitive values. Nested structures would let extra='forbid' be routed around "
                "by smuggling an unvalidated object through this field."
            )
    return v


def _validate_iso_datetime(v: str, field_name: str) -> str:
    text = v[:-1] + "+00:00" if v.endswith("Z") else v
    try:
        datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name}={v!r} is not a valid ISO datetime string") from exc
    return v


# ---------------------------------------------------------------------------
# Leaf value objects (task §3)
# ---------------------------------------------------------------------------

class ValueSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Optional[Union[float, int, str, bool]] = None
    unit: Optional[str] = None   # e.g. "BRL", "days", "count", "ratio", "score_1_5", "percent"


class TimeRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str    # "YYYY-MM-DD" or "YYYY-MM", matching KPIResult.period's own string convention
    end: str


class SourceInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    system: str          # "kpi_engine" | "anomaly_engine" | "driver_engine" | "review_pipeline"
    component: str        # dotted path to the function/class that produced this evidence
    version: str = "1.0"  # this Step 4 adapter's own version, NOT the KPI contract's version (that's in lineage)


class FreshnessInfo(BaseModel):
    """Task §19: distinguishes event time / data-availability time / processing
    time explicitly, rather than pretending historical Olist data is
    real-time."""
    model_config = ConfigDict(extra="forbid")
    event_time: Optional[str] = None                # when the underlying business event happened
    data_availability_time: Optional[str] = None     # when this row became available in data/processed;
                                                      # None is honest here -- canonical build date isn't
                                                      # tracked per-row today (see docs/EVIDENCE_FABRIC.md)
    processing_time: str                             # ISO datetime this EvidenceObject was constructed
    is_historical: bool = True                       # hardcoded True for all Olist-derived evidence

    @field_validator("processing_time")
    @classmethod
    def _processing_time_is_iso(cls, v: str) -> str:
        return _validate_iso_datetime(v, "freshness.processing_time")


class QualityInfo(BaseModel):
    """Task §20: multiple independent sub-scores, never collapsed into one
    opaque number. Every field is 0..1 or None (None = not applicable /
    not computed for this evidence type, never faked as 1.0)."""
    model_config = ConfigDict(extra="forbid")
    completeness: Optional[float] = None
    freshness: Optional[float] = None
    source_reliability: Optional[float] = None
    coverage: Optional[float] = None
    historical_sufficiency: Optional[float] = None
    retrieval_quality: Optional[float] = None

    @field_validator("completeness", "freshness", "source_reliability", "coverage",
                      "historical_sufficiency", "retrieval_quality")
    @classmethod
    def _in_unit_interval(cls, v: Optional[float]) -> Optional[float]:
        if v is not None and not (0.0 <= v <= 1.0):
            raise ValueError(f"quality score {v} is out of the [0, 1] range")
        return v


class SecurityInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: SecurityClassification
    trust_level: TrustLevel
    security_status: SecurityStatus = SecurityStatus.SAFE
    pii_detected: bool = False
    pii_types: list[str] = Field(default_factory=list)
    redaction_status: str = "NOT_APPLICABLE"   # NOT_APPLICABLE | NOT_REDACTED | REDACTED_AT_RETRIEVAL


class RelationshipRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    relationship_type: RelationshipType
    target_evidence_id: str
    note: Optional[str] = None

    @field_validator("note")
    @classmethod
    def _note_no_causal_language(cls, v: Optional[str]) -> Optional[str]:
        if v:
            _reject_causal_language(v, "relationships[].note")
        return v


# ---------------------------------------------------------------------------
# EvidenceObject (task §3)
# ---------------------------------------------------------------------------

class EvidenceObject(BaseModel):
    """The strict, machine-readable evidence schema every Step 4 adapter
    produces and every future agent (Step 5+) must cite rather than
    inventing its own numbers."""
    model_config = ConfigDict(extra="forbid")

    evidence_id: str
    evidence_type: EvidenceType
    evidence_tier: EvidenceTier
    claim: str
    value: ValueSpec
    time: TimeRange
    dimensions: dict[str, str] = Field(default_factory=dict)
    confidence: Confidence
    source: SourceInfo
    lineage: list[dict[str, str]] = Field(default_factory=list)
    freshness: FreshnessInfo
    quality: QualityInfo
    security: SecurityInfo
    relationships: list[RelationshipRef] = Field(default_factory=list)
    metadata: dict[str, Primitive] = Field(default_factory=dict)
    created_at: str

    @field_validator("claim")
    @classmethod
    def _claim_no_causal_language(cls, v: str) -> str:
        return _reject_causal_language(v, "claim")

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_is_flat(cls, v: dict[str, Primitive]) -> dict[str, Primitive]:
        return _reject_nested(v, "metadata") if isinstance(v, dict) else v

    @field_validator("created_at")
    @classmethod
    def _created_at_is_iso(cls, v: str) -> str:
        return _validate_iso_datetime(v, "created_at")


# ---------------------------------------------------------------------------
# Claim (task §4) -- kept structurally separate from EvidenceObject
# ---------------------------------------------------------------------------

class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    claim_id: str
    text: str
    supported_by: list[str] = Field(default_factory=list)   # evidence_id values; empty is legal
    created_at: str

    @field_validator("text")
    @classmethod
    def _text_no_causal_language(cls, v: str) -> str:
        return _reject_causal_language(v, "text")

    @field_validator("created_at")
    @classmethod
    def _created_at_is_iso(cls, v: str) -> str:
        return _validate_iso_datetime(v, "created_at")


# ---------------------------------------------------------------------------
# EvidenceQuery / EvidenceResult (task §14/§15)
# ---------------------------------------------------------------------------

class EvidenceQuery(BaseModel):
    """Structured_filters are validated against governed KPI dimensions (and
    the small explicit set of review-pipeline-only filter keys) in
    retrieval.py::validate_structured_filters -- this schema only fixes the
    *shape* of a query, not which filter values are authorized."""
    model_config = ConfigDict(extra="forbid")
    investigation_id: str
    question: str
    kpi_id: Optional[str] = None
    time_range: Optional[TimeRange] = None
    dimensions: dict[str, str] = Field(default_factory=dict)
    structured_filters: dict[str, str] = Field(default_factory=dict)
    semantic_query: Optional[str] = None
    top_k: int = Field(default=10, ge=1, le=100)
    minimum_relevance: float = Field(default=0.0, ge=0.0, le=1.0)
    requester_clearance: SecurityClassification = SecurityClassification.PUBLIC_ANALYTICAL


class RetrievalInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rank: int
    score: float
    method: str   # e.g. "structured_filter" | "structured_filter+semantic_e5_cosine+mmr_rerank"


class ReviewSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_id: Optional[str] = None
    order_id: Optional[str] = None


class EvidenceResult(BaseModel):
    """Never a bare string (task §15). Every result carries provenance
    (`source`) and a retrieval explanation (`retrieval`) alongside its
    content."""
    model_config = ConfigDict(extra="forbid")
    evidence_id: str
    evidence_type: EvidenceType
    claim: str
    content: str
    retrieval: RetrievalInfo
    source: ReviewSourceRef
    metadata: dict[str, Primitive] = Field(default_factory=dict)
    evidence_tier: EvidenceTier
    security: SecurityInfo
    lineage: list[dict[str, str]] = Field(default_factory=list)

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_is_flat(cls, v: dict[str, Primitive]) -> dict[str, Primitive]:
        return _reject_nested(v, "metadata") if isinstance(v, dict) else v
