"""
review.py — Step 9: the human review workflow gate.

Enforces spec section 18: "A feedback submission should NOT automatically
alter system behavior." review_feedback() is the ONLY function in this
package that may move a Feedback's review_status away from PENDING, and it
always requires an explicit reviewer + decision -- there is no code path
anywhere in src/feedback/ that a Feedback can reach APPROVED_FOR_EVALUATION
through except this function being called by a human-driven caller.

contest_feedback() implements spec sections 21-22: when two Feedback records
disagree about the same target (same story_id/claim_key or same
recommendation_id), the system must represent competing hypotheses rather
than silently picking a winner. Both feedback records are marked CONTESTED;
a ConflictRecord is stored capturing both hypotheses for later
research/evaluation -- never turned into an automatic business rule.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import timezone
from typing import Optional

from feedback.models import ConflictRecord, Feedback, FeedbackStatus, ReviewStatus
from feedback.store import FeedbackStore


class ReviewError(Exception):
    """Raised when a review transition is not allowed from the current
    state (e.g. approving feedback that is already REJECTED)."""


def _now() -> str:
    return datetime.datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


_TERMINAL_REVIEW_STATUSES = (ReviewStatus.APPROVED_FOR_EVALUATION, ReviewStatus.REJECTED)


def review_feedback(
    feedback_id: str, decision: ReviewStatus, reviewer: str, store: FeedbackStore,
    rationale: Optional[str] = None, feedback_status: Optional[FeedbackStatus] = None,
) -> Feedback:
    """Moves a Feedback's review_status forward. decision must be REVIEWED,
    APPROVED_FOR_EVALUATION, or REJECTED (PENDING is the only starting
    state, never a valid decision). Once a Feedback reaches
    APPROVED_FOR_EVALUATION or REJECTED it is terminal for this workflow --
    re-review requires a fresh Feedback submission, not a state reversal
    (preserves history, spec section 10). feedback_status optionally also
    records the human's trust judgment (ACCEPTED/REJECTED/CONTESTED) in the
    same call, since a reviewer typically forms both opinions together."""
    if decision not in (ReviewStatus.REVIEWED, ReviewStatus.APPROVED_FOR_EVALUATION, ReviewStatus.REJECTED):
        raise ReviewError(f"decision must be REVIEWED, APPROVED_FOR_EVALUATION, or REJECTED, got {decision!r}")

    current = store.get_feedback(feedback_id)
    if current is None:
        raise ReviewError(f"no feedback found with id {feedback_id!r}")
    if current.review_status in _TERMINAL_REVIEW_STATUSES:
        raise ReviewError(
            f"feedback {feedback_id!r} is already terminal (review_status={current.review_status.value}); "
            f"review decisions cannot be reversed, only a new Feedback submission can supersede it"
        )
    if decision == ReviewStatus.APPROVED_FOR_EVALUATION and current.review_status == ReviewStatus.PENDING:
        raise ReviewError(
            f"feedback {feedback_id!r} must pass through REVIEWED before APPROVED_FOR_EVALUATION"
        )

    store.append_feedback_status_event(
        feedback_id=feedback_id, status=feedback_status, review_status=decision,
        reviewer=reviewer, rationale=rationale, created_at=_now(),
    )
    return store.get_feedback(feedback_id)


def contest_feedback(
    feedback_id_a: str, feedback_id_b: str, hypothesis_a: str, hypothesis_b: str, store: FeedbackStore,
) -> ConflictRecord:
    """Marks both feedback records CONTESTED and stores a ConflictRecord
    preserving both hypotheses. Never picks a winner -- resolving a
    conflict (if it ever happens) is a distinct, explicit human action, not
    something this function attempts."""
    for fid in (feedback_id_a, feedback_id_b):
        if store.get_feedback(fid) is None:
            raise ReviewError(f"no feedback found with id {fid!r}")
        store.append_feedback_status_event(feedback_id=fid, status=FeedbackStatus.CONTESTED, created_at=_now())

    conflict = ConflictRecord(
        conflict_id=_new_id("CONFLICT"), feedback_ids=[feedback_id_a, feedback_id_b],
        hypotheses=[hypothesis_a, hypothesis_b], created_at=_now(),
    )
    return store.save_conflict(conflict)
