"""
correction.py — Step 9: Correction + BusinessContext capture (spec sections
6-8).

store_correction() / capture_business_context() are thin, validated
constructors + store writes -- same "capture, don't compute" posture as
capture.py's submit_feedback(). Neither function ever touches the original
AI output (story.models.KPIStory / decision.models.ActionRecommendation):
Correction.original_claim is always a plain string copy, never a live
reference, so there is no way calling this module could mutate Step 7/8
state even by accident.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import timezone
from typing import Optional

from feedback.models import BusinessContext, ClaimType, ContextType, Correction, CorrectionType
from feedback.store import FeedbackStore


def _now() -> str:
    return datetime.datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def store_correction(
    feedback_id: str,
    correction_type: CorrectionType,
    original_claim: str,
    corrected_claim: str,
    store: FeedbackStore,
    *,
    original_claim_type: Optional[ClaimType] = None,
    corrected_claim_type: Optional[ClaimType] = None,
    evidence_ids: Optional[list[str]] = None,
    rationale: str = "",
    business_context_id: Optional[str] = None,
    correction_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Correction:
    """Constructs and persists a Correction. original_claim is always the
    verbatim original text -- this function never overwrites or edits it;
    the correction is a NEW record that references the original by value,
    preserving both for auditability (spec section 6)."""
    correction = Correction(
        correction_id=correction_id or _new_id("CORR"), feedback_id=feedback_id,
        correction_type=correction_type, original_claim=original_claim, corrected_claim=corrected_claim,
        created_at=created_at or _now(), original_claim_type=original_claim_type,
        corrected_claim_type=corrected_claim_type, evidence_ids=list(evidence_ids or []),
        rationale=rationale, business_context_id=business_context_id,
    )
    return store.save_correction(correction)


def capture_business_context(
    feedback_id: str,
    context_type: ContextType,
    description: str,
    store: FeedbackStore,
    *,
    affected_period: Optional[str] = None,
    affected_segments: Optional[list[str]] = None,
    confidence: Optional[float] = None,
    evidence_ids: Optional[list[str]] = None,
    source: str = "analyst",
    context_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> BusinessContext:
    """Constructs and persists a BusinessContext record, stored SEPARATELY
    from ordinary textual feedback (spec section 8) so it can be queried and
    reused independently (e.g. by a future EvaluationCase's input_context)
    without re-parsing free-text comments."""
    context = BusinessContext(
        context_id=context_id or _new_id("CTX"), feedback_id=feedback_id, context_type=context_type,
        description=description, created_at=created_at or _now(), affected_period=affected_period,
        affected_segments=list(affected_segments or []), confidence=confidence,
        evidence_ids=list(evidence_ids or []), source=source,
    )
    return store.save_business_context(context)
