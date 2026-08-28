"""
models.py — Step 8: data structures for the Persona-Aware KPI Storytelling
engine.

Same posture as src/decision/models.py, src/causal/models.py,
src/agents/models.py: this module holds definitions only -- no persona
selection, no planning, no LLM calls, no verification logic. Every dataclass
here is a plain, serializable container the rest of src/story/ builds and
returns.

NON-NEGOTIABLE PRINCIPLE (this step's own words): LLM = storyteller, Code =
source of truth, Verifier = gatekeeper. Never LLM = analyst + calculator +
storyteller. Every number a NarrativeClaim carries must trace back to a real
EvidenceItem's .value (itself copied verbatim from a real Step 4/6/7
object) -- nothing in this module computes a business number.

ClaimType is a NEW, deliberately separate axis from two enums that already
exist in this repo:
  - evidence.models.EvidenceType   -- WHAT KIND of measurement is this
                                       (KPI_OBSERVATION, DRIVER_CONTRIBUTION, ...)?
  - evidence.models.EvidenceTier   -- what METHODOLOGICAL RIGOR produced it
                                       (T1_DESCRIPTIVE .. T5_EXPERIMENTAL)?
  - story.models.ClaimType (here)  -- what EPISTEMIC STRENGTH may a NARRATIVE
                                       SENTENCE citing this evidence claim
                                       (FACT / ANALYTICAL_FINDING / ASSOCIATION /
                                       HYPOTHESIS / UNKNOWN)?
A T3_STATISTICAL anomaly signal and a T1_DESCRIPTIVE KPI movement are both
real Step 4 evidence, but a narrative sentence built from the former may
only ever be phrased as an ASSOCIATION, never a FACT -- ClaimType captures
that narrative-language constraint, which neither existing enum has any
vocabulary for. See docs/STORYTELLING_ARCHITECTURE.md for the full mapping
table (implemented in story/evidence_package.py::_infer_claim_type).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

from agents.models import assert_no_unsupported_causal_language

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ClaimType(str, Enum):
    FACT = "FACT"
    ANALYTICAL_FINDING = "ANALYTICAL_FINDING"
    ASSOCIATION = "ASSOCIATION"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


# Total order used by claim_verifier.py's epistemic-consistency check: a
# claim may be labeled weaker (hedged down) than its strongest cited
# evidence's ClaimType, never stronger. Higher rank = stronger claim.
CLAIM_TYPE_RANK: dict[ClaimType, int] = {
    ClaimType.UNKNOWN: 0,
    ClaimType.HYPOTHESIS: 1,
    ClaimType.ASSOCIATION: 2,
    ClaimType.ANALYTICAL_FINDING: 3,
    ClaimType.FACT: 4,
}


class Persona(str, Enum):
    EXECUTIVE = "EXECUTIVE"
    FINANCE = "FINANCE"
    OPERATIONS = "OPERATIONS"
    MARKETING = "MARKETING"


class ValidationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class GeneratedBy(str, Enum):
    DETERMINISTIC_TEMPLATE = "DETERMINISTIC_TEMPLATE"
    LLM_GENERATED_VERIFIED = "LLM_GENERATED_VERIFIED"


# ---------------------------------------------------------------------------
# Evidence layer -- thin wrappers over real Step 4/6/7 objects, never a
# re-derivation of their numbers
# ---------------------------------------------------------------------------


@dataclass
class EvidenceItem:
    """Wraps exactly one of source_evidence_object / source_recommendation /
    source_causal_result. All scalar fields below (value/unit/confidence/...)
    are copied verbatim from that source at construction time
    (story.evidence_package.py's job) -- this dataclass performs no
    computation of its own."""

    evidence_id: str
    metric: str
    value: Optional[float]
    unit: Optional[str]
    direction: Optional[str]  # "increase" | "decrease" | "stable" | None
    period: str
    source_system: str
    timestamp: str
    analytical_method: str
    confidence: Any  # whatever shape the source carries: evidence.models.Confidence (categorical
                      # str enum) or a numeric 0-1 float (decision.models.ScoreBreakdown.confidence_score)
                      # -- never coerced into a fabricated shape by this package
    claim_type: ClaimType
    evidence_type: Optional[str] = None  # echoed from evidence.models.EvidenceType.value, else None
    evidence_tier: Optional[str] = None  # echoed from evidence.models.EvidenceTier.value / causal.models.CausalTier.value
    supporting_evidence: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    source_evidence_object: Optional[Any] = None
    source_recommendation: Optional[Any] = None
    source_causal_result: Optional[Any] = None

    def to_dict(self) -> dict[str, Any]:
        d = {
            "evidence_id": self.evidence_id, "metric": self.metric, "value": self.value, "unit": self.unit,
            "direction": self.direction, "period": self.period, "source_system": self.source_system,
            "timestamp": self.timestamp, "analytical_method": self.analytical_method,
            "confidence": self.confidence.value if hasattr(self.confidence, "value") else self.confidence,
            "claim_type": self.claim_type.value, "evidence_type": self.evidence_type,
            "evidence_tier": self.evidence_tier, "supporting_evidence": list(self.supporting_evidence),
            "limitations": list(self.limitations),
        }
        return d


@dataclass
class EvidencePackage:
    package_id: str
    kpi_id: str
    period: str
    items: list[EvidenceItem]
    recommendations: list[Any] = field(default_factory=list)  # decision.models.ActionRecommendation
    version: str = "1.0"
    content_hash: str = ""
    created_at: str = ""

    def get(self, evidence_id: str) -> Optional[EvidenceItem]:
        return next((i for i in self.items if i.evidence_id == evidence_id), None)

    def all_ids(self) -> set[str]:
        return {i.evidence_id for i in self.items}

    def recommendation_ids(self) -> set[str]:
        return {r.recommendation_id for r in self.recommendations}

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id, "kpi_id": self.kpi_id, "period": self.period,
            "items": [i.to_dict() for i in self.items],
            "recommendations": [r.to_dict() if hasattr(r, "to_dict") else r for r in self.recommendations],
            "version": self.version, "content_hash": self.content_hash, "created_at": self.created_at,
        }


# ---------------------------------------------------------------------------
# Numeric claims -- extracted from generated narrative text, verified
# against the EvidencePackage (story.numeric_verifier.py)
# ---------------------------------------------------------------------------


@dataclass
class NumericClaim:
    raw_text: str
    normalized_value: float
    unit: str  # "BRL" | "percent" | "count" | "ratio" | "unitless"
    matched_evidence_id: Optional[str] = None
    status: ValidationStatus = ValidationStatus.PENDING
    rejection_reason: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


# ---------------------------------------------------------------------------
# Narrative claims -- one per substantive sentence, claim-level grounded
# ---------------------------------------------------------------------------


@dataclass
class NarrativeClaim:
    text: str
    claim_type: ClaimType
    evidence_ids: list[str] = field(default_factory=list)
    confidence: Any = None
    numeric_claims: list[NumericClaim] = field(default_factory=list)
    validation_status: ValidationStatus = ValidationStatus.PENDING
    rejection_reason: Optional[str] = None

    def __post_init__(self) -> None:
        assert_no_unsupported_causal_language(self.text, "NarrativeClaim.text")

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text, "claim_type": self.claim_type.value, "evidence_ids": list(self.evidence_ids),
            "confidence": self.confidence.value if hasattr(self.confidence, "value") else self.confidence,
            "numeric_claims": [n.to_dict() for n in self.numeric_claims],
            "validation_status": self.validation_status.value, "rejection_reason": self.rejection_reason,
        }


@dataclass
class StorySection:
    title: str
    statements: list[NarrativeClaim] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "statements": [s.to_dict() for s in self.statements]}


# ---------------------------------------------------------------------------
# Narrative plan -- the planner's output, evidence SELECTION only, never new
# content
# ---------------------------------------------------------------------------


@dataclass
class NarrativePlanSection:
    title: str
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "evidence_ids": list(self.evidence_ids)}


@dataclass
class NarrativePlan:
    persona: Persona
    sections: list[NarrativePlanSection] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"persona": self.persona.value, "sections": [s.to_dict() for s in self.sections]}


# ---------------------------------------------------------------------------
# Verification result and the final story object
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    status: ValidationStatus  # APPROVED | REJECTED, never PENDING at this level
    claims_checked: int
    claims_rejected: int
    rejected_claims: list[dict[str, Any]] = field(default_factory=list)  # [{"text": ..., "reason": ...}]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value, "claims_checked": self.claims_checked,
            "claims_rejected": self.claims_rejected, "rejected_claims": list(self.rejected_claims),
        }


@dataclass
class KPIStory:
    persona: Persona
    headline: str
    sections: list[StorySection]
    verification: VerificationResult
    generated_by: GeneratedBy
    generated_at: str
    model_info: dict[str, Any]
    evidence_package_id: str
    evidence_package_version: str
    evidence_package_hash: str
    generation_attempts: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona": self.persona.value, "headline": self.headline,
            "sections": [s.to_dict() for s in self.sections], "verification": self.verification.to_dict(),
            "generated_by": self.generated_by.value, "generated_at": self.generated_at,
            "model_info": dict(self.model_info), "evidence_package_id": self.evidence_package_id,
            "evidence_package_version": self.evidence_package_version,
            "evidence_package_hash": self.evidence_package_hash, "generation_attempts": self.generation_attempts,
        }


class StoryGenerationFailed(Exception):
    """Raised by story.engine.generate_kpi_story() when max_generation_retries
    is exhausted and no verified narrative could be produced, and
    config.fallback.allow_deterministic_fallback is False. Never swallowed
    silently -- a caller receiving this exception must not present any
    unverified narrative to a user."""
