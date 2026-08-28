"""
capture.py — Step 9: Feedback Capture + Validator.

submit_feedback() is the single entry point for turning a human's rating/
comment/reference selections into a validated Feedback record. Performs
validation and construction only -- no storage (store.py's job), no
classification (classifier.py's job), no correction handling
(correction.py's job). Same "one responsibility per module" split as
story/planner.py vs story/generator.py vs story/claim_verifier.py.

No authentication requirement: user_id is optional throughout (spec section
3's "Do not require identifying user information if the application does
not already have authentication" -- this repo has none). session_id is the
only required identity-ish field, and it may be any caller-supplied opaque
string (e.g. a demo-script-generated UUID) -- never validated against a
user directory that doesn't exist.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import timezone
from typing import Optional

from feedback.models import (
    Feedback,
    FeedbackCategory,
    FeedbackRating,
    FeedbackStatus,
    InvalidFeedbackError,
    OutputType,
    ReviewStatus,
)


def _now() -> str:
    return datetime.datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def submit_feedback(
    rating: FeedbackRating,
    output_type: OutputType,
    session_id: str,
    *,
    user_id: Optional[str] = None,
    story_id: Optional[str] = None,
    comment: Optional[str] = None,
    categories: Optional[list[FeedbackCategory]] = None,
    affected_evidence_ids: Optional[list[str]] = None,
    affected_claim_keys: Optional[list[str]] = None,
    affected_recommendation_id: Optional[str] = None,
    feedback_id: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> Feedback:
    """Validates and constructs a Feedback record. Raises
    InvalidFeedbackError (via Feedback.__post_init__) for a structurally
    invalid rating/comment combination -- never for a disagreement about
    content, which is what FeedbackStatus/ReviewStatus exist to carry
    instead. Newly submitted feedback always starts
    status=UNREVIEWED/review_status=PENDING: submission itself never alters
    system behavior (spec section 18)."""
    if not isinstance(rating, FeedbackRating):
        raise InvalidFeedbackError(f"rating must be a FeedbackRating, got {rating!r}")
    if not isinstance(output_type, OutputType):
        raise InvalidFeedbackError(f"output_type must be an OutputType, got {output_type!r}")

    return Feedback(
        feedback_id=feedback_id or _new_id("FB"),
        timestamp=timestamp or _now(),
        output_type=output_type,
        rating=rating,
        session_id=session_id,
        user_id=user_id,
        story_id=story_id,
        comment=comment,
        categories=list(categories or []),
        affected_evidence_ids=list(affected_evidence_ids or []),
        affected_claim_keys=list(affected_claim_keys or []),
        affected_recommendation_id=affected_recommendation_id,
        status=FeedbackStatus.UNREVIEWED,
        review_status=ReviewStatus.PENDING,
    )
