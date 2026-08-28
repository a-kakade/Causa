"""
models.py — Step 9: data structures for the Human Feedback & Learning Loop.

Same posture as src/story/models.py, src/decision/models.py: this module
holds definitions only -- no capture, no classification, no storage, no
evaluation logic. Every dataclass here is a plain, serializable container
the rest of src/feedback/ builds and returns.

NON-NEGOTIABLE PRINCIPLE (this step's own words): human feedback becomes
evaluation data and controlled improvement, never automatic model training.
Nothing in this module (or the rest of src/feedback/) ever mutates a
story.models.KPIStory / story.models.NarrativeClaim / decision.models.
ActionRecommendation in place, retrains a model, or changes a prompt/config
value on its own -- it only ever produces new, additively-stored records
that a human-reviewed, offline evaluation process later consumes.

Reuse, not duplication: this package deliberately does NOT mint a new claim
identity system. story.models.NarrativeClaim has no standalone claim_id --
a claim is identified by its position within a KPIStory's sections. Rather
than bolt a claim_id field onto Step 8 (which would touch a "completed"
step's core model), this module defines claim_key() as a derived,
computable-anywhere reference string. affected_evidence_ids and
affected_recommendation_id reuse story.models.EvidenceItem.evidence_id and
decision.models.ActionRecommendation.recommendation_id verbatim -- real IDs
already minted upstream, never reinvented here.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

# story.models.ClaimType is reused directly (not redefined) for
# Correction.original_claim_type / corrected_claim_type, and story.models.
# Persona is reused directly for EvaluationCase.persona -- imported lazily
# inside type hints via string forward-refs would work too, but a direct
# import keeps this module honest about the dependency: Step 9 depends on
# Step 8's vocabulary, never the reverse.
from story.models import ClaimType, Persona

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class FeedbackRating(str, Enum):
    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"
    MISSING_DRIVER = "MISSING_DRIVER"
    WRONG_RECOMMENDATION = "WRONG_RECOMMENDATION"
    WRONG_CONFIDENCE = "WRONG_CONFIDENCE"
    COMMENT_ONLY = "COMMENT_ONLY"


class FeedbackCategory(str, Enum):
    """Deterministic classification buckets (spec section 5). A single
    Feedback may carry multiple categories -- this is why Feedback.categories
    is a list, not a single enum field."""
    DATA = "DATA"
    KPI_DEFINITION = "KPI_DEFINITION"
    DRIVER = "DRIVER"
    EVIDENCE = "EVIDENCE"
    CONFIDENCE = "CONFIDENCE"
    RECOMMENDATION = "RECOMMENDATION"
    NARRATIVE = "NARRATIVE"


class FeedbackStatus(str, Enum):
    """The trust-model axis (spec section 21): has this feedback itself been
    judged credible? Distinct from ReviewStatus below, which asks a
    different question ("has this feedback been promoted into evaluation
    data?") -- conflating the two would blur "is this correction believed"
    with "is this correction usable for evaluation," which the spec treats
    as separate decisions (a CONTESTED correction can still be preserved for
    future research without ever becoming a regression test)."""
    UNREVIEWED = "UNREVIEWED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONTESTED = "CONTESTED"


class ReviewStatus(str, Enum):
    """The eval-promotion workflow axis (spec sections 17-18). A Feedback (and
    any EvaluationCase created from it) starts PENDING; only a human
    reviewer can move it to APPROVED_FOR_EVALUATION. PENDING feedback must
    never alter system behavior."""
    PENDING = "PENDING"
    REVIEWED = "REVIEWED"
    APPROVED_FOR_EVALUATION = "APPROVED_FOR_EVALUATION"
    REJECTED = "REJECTED"


class ContextType(str, Enum):
    """Business-context categories the analytical pipeline could not see
    (spec section 8). Kept as an extensible-in-spirit closed set, same
    posture as decision.models.DriverCategory -- OTHER is always available
    as a safe fallback rather than raising on an unanticipated context."""
    PROMOTION = "PROMOTION"
    HOLIDAY = "HOLIDAY"
    CAMPAIGN = "CAMPAIGN"
    STOCKOUT = "STOCKOUT"
    PRICING_EVENT = "PRICING_EVENT"
    COMPETITOR_EVENT = "COMPETITOR_EVENT"
    OPERATIONAL_EVENT = "OPERATIONAL_EVENT"
    POLICY_CHANGE = "POLICY_CHANGE"
    MARKET_EVENT = "MARKET_EVENT"
    OTHER = "OTHER"


class OutputType(str, Enum):
    """What kind of AI output a Feedback record targets -- determines which
    ID fields (affected_claim_keys / affected_recommendation_id /
    affected_evidence_ids) are expected to be populated."""
    STORY_CLAIM = "STORY_CLAIM"
    RECOMMENDATION = "RECOMMENDATION"
    EVIDENCE_ITEM = "EVIDENCE_ITEM"


class CorrectionType(str, Enum):
    """Extensible correction taxonomy (spec section 7). Extensible in
    practice via config/feedback.yaml's correction_types list (documented
    there for governance visibility); this enum is the enforced closed set
    a Correction.correction_type must belong to -- OTHER is the safe
    escape hatch for anything not yet named."""
    WRONG_KPI_DEFINITION = "WRONG_KPI_DEFINITION"
    WRONG_METRIC_VALUE = "WRONG_METRIC_VALUE"
    WRONG_DRIVER = "WRONG_DRIVER"
    MISSING_DRIVER = "MISSING_DRIVER"
    WRONG_CAUSAL_RELATIONSHIP = "WRONG_CAUSAL_RELATIONSHIP"
    WRONG_EVIDENCE_INTERPRETATION = "WRONG_EVIDENCE_INTERPRETATION"
    WRONG_CONFIDENCE = "WRONG_CONFIDENCE"
    WRONG_RECOMMENDATION = "WRONG_RECOMMENDATION"
    WRONG_PRIORITY = "WRONG_PRIORITY"
    WRONG_NARRATIVE_WORDING = "WRONG_NARRATIVE_WORDING"
    MISSING_CONTEXT = "MISSING_CONTEXT"
    OTHER = "OTHER"


class GeneratedBy(str, Enum):
    """Mirrors story.models.GeneratedBy / decision.models.GeneratedBy's
    naming convention, but scoped to how a FeedbackCategory list was
    produced -- never how the underlying Feedback text was produced (that
    is always human-authored by construction)."""
    DETERMINISTIC_RULES = "DETERMINISTIC_RULES"
    LLM_CLASSIFIED_VALIDATED = "LLM_CLASSIFIED_VALIDATED"


# ---------------------------------------------------------------------------
# Claim identity helper -- derived, never stored on story.models.NarrativeClaim
# ---------------------------------------------------------------------------


def claim_key(story_id: str, section_index: int, claim_index: int) -> str:
    """The one deterministic reference string this package uses to point at
    a specific story.models.NarrativeClaim without requiring Step 8 to grow
    a claim_id field. Computable from a KPIStory's own sections list:
    claim_key(story_id, i, j) == story.sections[i].statements[j]."""
    return f"{story_id}:{section_index}:{claim_index}"


# ---------------------------------------------------------------------------
# Feedback -- the top-level capture record (spec section 3)
# ---------------------------------------------------------------------------


class InvalidFeedbackError(Exception):
    """Raised by Feedback.__post_init__ / capture.submit_feedback() when a
    rating/category/reference combination is structurally invalid. Never
    raised for a disagreement about content -- that is what FeedbackStatus/
    ReviewStatus exist to represent, not a validation error."""


@dataclass
class Feedback:
    feedback_id: str
    timestamp: str
    output_type: OutputType
    rating: FeedbackRating
    session_id: str
    user_id: Optional[str] = None  # None is a legitimate, expected value -- no auth requirement (spec section 32)
    story_id: Optional[str] = None
    comment: Optional[str] = None
    categories: list[FeedbackCategory] = field(default_factory=list)
    affected_evidence_ids: list[str] = field(default_factory=list)
    affected_claim_keys: list[str] = field(default_factory=list)
    affected_recommendation_id: Optional[str] = None
    status: FeedbackStatus = FeedbackStatus.UNREVIEWED
    review_status: ReviewStatus = ReviewStatus.PENDING

    def __post_init__(self) -> None:
        if self.rating == FeedbackRating.COMMENT_ONLY and not (self.comment and self.comment.strip()):
            raise InvalidFeedbackError("rating=COMMENT_ONLY requires a non-empty comment")
        if not self.feedback_id:
            raise InvalidFeedbackError("feedback_id must not be empty")
        if not self.session_id:
            raise InvalidFeedbackError("session_id must not be empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "feedback_id": self.feedback_id, "timestamp": self.timestamp,
            "output_type": self.output_type.value, "rating": self.rating.value,
            "session_id": self.session_id, "user_id": self.user_id, "story_id": self.story_id,
            "comment": self.comment, "categories": [c.value for c in self.categories],
            "affected_evidence_ids": list(self.affected_evidence_ids),
            "affected_claim_keys": list(self.affected_claim_keys),
            "affected_recommendation_id": self.affected_recommendation_id,
            "status": self.status.value, "review_status": self.review_status.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Feedback":
        return cls(
            feedback_id=d["feedback_id"], timestamp=d["timestamp"],
            output_type=OutputType(d["output_type"]), rating=FeedbackRating(d["rating"]),
            session_id=d["session_id"], user_id=d.get("user_id"), story_id=d.get("story_id"),
            comment=d.get("comment"),
            categories=[FeedbackCategory(c) for c in d.get("categories", [])],
            affected_evidence_ids=list(d.get("affected_evidence_ids", [])),
            affected_claim_keys=list(d.get("affected_claim_keys", [])),
            affected_recommendation_id=d.get("affected_recommendation_id"),
            status=FeedbackStatus(d.get("status", FeedbackStatus.UNREVIEWED.value)),
            review_status=ReviewStatus(d.get("review_status", ReviewStatus.PENDING.value)),
        )


# ---------------------------------------------------------------------------
# Correction -- explicit, never overwrites the original (spec sections 6-7)
# ---------------------------------------------------------------------------


@dataclass
class Correction:
    correction_id: str
    feedback_id: str
    correction_type: CorrectionType
    original_claim: str
    corrected_claim: str
    created_at: str
    original_claim_type: Optional[ClaimType] = None
    corrected_claim_type: Optional[ClaimType] = None
    evidence_ids: list[str] = field(default_factory=list)
    rationale: str = ""
    business_context_id: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "correction_id": self.correction_id, "feedback_id": self.feedback_id,
            "correction_type": self.correction_type.value,
            "original_claim": self.original_claim,
            "original_claim_type": self.original_claim_type.value if self.original_claim_type else None,
            "corrected_claim": self.corrected_claim,
            "corrected_claim_type": self.corrected_claim_type.value if self.corrected_claim_type else None,
            "evidence_ids": list(self.evidence_ids), "rationale": self.rationale,
            "business_context_id": self.business_context_id, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Correction":
        return cls(
            correction_id=d["correction_id"], feedback_id=d["feedback_id"],
            correction_type=CorrectionType(d["correction_type"]),
            original_claim=d["original_claim"],
            original_claim_type=ClaimType(d["original_claim_type"]) if d.get("original_claim_type") else None,
            corrected_claim=d["corrected_claim"],
            corrected_claim_type=ClaimType(d["corrected_claim_type"]) if d.get("corrected_claim_type") else None,
            evidence_ids=list(d.get("evidence_ids", [])), rationale=d.get("rationale", ""),
            business_context_id=d.get("business_context_id"), created_at=d["created_at"],
        )


# ---------------------------------------------------------------------------
# BusinessContext -- context the analytical pipeline could not see (spec section 8)
# ---------------------------------------------------------------------------


@dataclass
class BusinessContext:
    context_id: str
    feedback_id: str
    context_type: ContextType
    description: str
    created_at: str
    affected_period: Optional[str] = None
    affected_segments: list[str] = field(default_factory=list)
    confidence: Optional[float] = None
    evidence_ids: list[str] = field(default_factory=list)
    source: str = "analyst"

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id, "feedback_id": self.feedback_id,
            "context_type": self.context_type.value, "description": self.description,
            "affected_period": self.affected_period, "affected_segments": list(self.affected_segments),
            "confidence": self.confidence, "evidence_ids": list(self.evidence_ids),
            "source": self.source, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "BusinessContext":
        return cls(
            context_id=d["context_id"], feedback_id=d["feedback_id"],
            context_type=ContextType(d["context_type"]), description=d["description"],
            affected_period=d.get("affected_period"), affected_segments=list(d.get("affected_segments", [])),
            confidence=d.get("confidence"), evidence_ids=list(d.get("evidence_ids", [])),
            source=d.get("source", "analyst"), created_at=d["created_at"],
        )


# ---------------------------------------------------------------------------
# EvaluationCase -- what the system SHOULD have said (spec sections 11-14)
# ---------------------------------------------------------------------------


@dataclass
class EvaluationCase:
    case_id: str
    dataset_version: str
    source_feedback_id: str
    created_at: str
    input_context: dict[str, Any] = field(default_factory=dict)
    expected_behavior: dict[str, Any] = field(default_factory=dict)
    expected_claims: list[str] = field(default_factory=list)
    forbidden_claims: list[str] = field(default_factory=list)
    expected_driver: Optional[str] = None
    expected_recommendation: Optional[dict[str, Any]] = None
    expected_confidence_range: Optional[tuple[float, float]] = None
    expected_evidence_ids: list[str] = field(default_factory=list)
    persona: Optional[Persona] = None
    status: ReviewStatus = ReviewStatus.PENDING

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id, "dataset_version": self.dataset_version,
            "source_feedback_id": self.source_feedback_id, "created_at": self.created_at,
            "input_context": dict(self.input_context), "expected_behavior": dict(self.expected_behavior),
            "expected_claims": list(self.expected_claims), "forbidden_claims": list(self.forbidden_claims),
            "expected_driver": self.expected_driver, "expected_recommendation": self.expected_recommendation,
            "expected_confidence_range": list(self.expected_confidence_range) if self.expected_confidence_range else None,
            "expected_evidence_ids": list(self.expected_evidence_ids),
            "persona": self.persona.value if self.persona else None, "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "EvaluationCase":
        rng = d.get("expected_confidence_range")
        return cls(
            case_id=d["case_id"], dataset_version=d["dataset_version"],
            source_feedback_id=d["source_feedback_id"], created_at=d["created_at"],
            input_context=dict(d.get("input_context", {})), expected_behavior=dict(d.get("expected_behavior", {})),
            expected_claims=list(d.get("expected_claims", [])), forbidden_claims=list(d.get("forbidden_claims", [])),
            expected_driver=d.get("expected_driver"), expected_recommendation=d.get("expected_recommendation"),
            expected_confidence_range=tuple(rng) if rng else None,
            expected_evidence_ids=list(d.get("expected_evidence_ids", [])),
            persona=Persona(d["persona"]) if d.get("persona") else None,
            status=ReviewStatus(d.get("status", ReviewStatus.PENDING.value)),
        )


# ---------------------------------------------------------------------------
# RegressionTest -- an approved EvaluationCase promoted to a runnable check
# (spec section 17)
# ---------------------------------------------------------------------------


@dataclass
class RegressionTest:
    test_id: str
    source_evaluation_case_id: str
    assertion_summary: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RegressionTest":
        return cls(**d)


# ---------------------------------------------------------------------------
# Conflicting feedback -- competing hypotheses preserved, never arbitrated
# (spec section 22)
# ---------------------------------------------------------------------------


@dataclass
class ConflictRecord:
    conflict_id: str
    feedback_ids: list[str]
    hypotheses: list[str]
    created_at: str
    status: str = "CONTESTED"  # mirrors FeedbackStatus.CONTESTED.value; kept as a plain str here
                                # since a ConflictRecord always represents an unresolved state by
                                # construction (create_conflict() is the only way to make one)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id, "feedback_ids": list(self.feedback_ids),
            "hypotheses": list(self.hypotheses), "status": self.status, "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ConflictRecord":
        return cls(
            conflict_id=d["conflict_id"], feedback_ids=list(d["feedback_ids"]),
            hypotheses=list(d["hypotheses"]), status=d.get("status", "CONTESTED"), created_at=d["created_at"],
        )
