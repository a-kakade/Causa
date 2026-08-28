"""
evaluation_case.py — Step 9: turning an APPROVED correction into future
evaluation data (spec sections 11-14, 18).

create_evaluation_case() is gated: it only accepts a Feedback whose
review_status is already ReviewStatus.APPROVED_FOR_EVALUATION (set
exclusively by review.review_feedback(), a human-driven action). This is the
literal enforcement of "PENDING feedback does not alter system behaviour" --
there is no path from raw feedback to evaluation data that skips human
review.

Dataset versioning (spec section 14): every EvaluationCase is stamped with
a dataset_version. next_dataset_version() computes the next version from
what's already stored -- existing cases are never rewritten (store.py is
append-only), so a new dataset_version is how a change in expected outcomes
is expressed, never an edit to a prior version's cases.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import timezone
from typing import Any, Optional

from feedback.models import BusinessContext, Correction, EvaluationCase, Feedback, Persona, ReviewStatus
from feedback.store import FeedbackStore


class EvaluationCaseError(Exception):
    """Raised when create_evaluation_case() is called against a Feedback
    that has not been APPROVED_FOR_EVALUATION."""


def _now() -> str:
    return datetime.datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def next_dataset_version(store: FeedbackStore) -> str:
    """Monotonic vN version string, computed from every dataset_version any
    EvaluationCase has ever been stored under (including cases now
    superseded by a later version -- nothing is ever deleted). Returns "v1"
    when no case has been stored yet."""
    versions = store.list_dataset_versions()
    numbers = []
    for v in versions:
        if v.startswith("v") and v[1:].isdigit():
            numbers.append(int(v[1:]))
    next_n = (max(numbers) + 1) if numbers else 1
    return f"v{next_n}"


def create_evaluation_case(
    feedback: Feedback,
    correction: Optional[Correction],
    business_context: Optional[BusinessContext],
    store: FeedbackStore,
    *,
    dataset_version: Optional[str] = None,
    input_context: Optional[dict[str, Any]] = None,
    expected_behavior: Optional[dict[str, Any]] = None,
    expected_claims: Optional[list[str]] = None,
    forbidden_claims: Optional[list[str]] = None,
    expected_driver: Optional[str] = None,
    expected_recommendation: Optional[dict[str, Any]] = None,
    expected_confidence_range: Optional[tuple[float, float]] = None,
    expected_evidence_ids: Optional[list[str]] = None,
    persona: Optional[Persona] = None,
    case_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> EvaluationCase:
    """Builds and persists one EvaluationCase capturing what the system
    SHOULD have said, per spec section 12's worked example. Requires
    feedback.review_status == APPROVED_FOR_EVALUATION -- raises
    EvaluationCaseError otherwise. correction/business_context are optional
    (a COMMENT_ONLY or CORRECT-rating feedback may still be worth an
    evaluation case, e.g. a regression fixture proving current behavior is
    already right), but when supplied their content is folded into
    forbidden_claims/expected_behavior only via the caller-supplied
    parameters above -- this function performs no free-text parsing of its
    own, staying a pure "assemble and store" step like capture.py."""
    if feedback.review_status != ReviewStatus.APPROVED_FOR_EVALUATION:
        raise EvaluationCaseError(
            f"feedback {feedback.feedback_id!r} has review_status={feedback.review_status.value}; "
            f"only APPROVED_FOR_EVALUATION feedback may become an evaluation case"
        )

    case = EvaluationCase(
        case_id=case_id or _new_id("EVALCASE"),
        dataset_version=dataset_version or next_dataset_version(store),
        source_feedback_id=feedback.feedback_id, created_at=created_at or _now(),
        input_context=dict(input_context or {}), expected_behavior=dict(expected_behavior or {}),
        expected_claims=list(expected_claims or []), forbidden_claims=list(forbidden_claims or []),
        expected_driver=expected_driver, expected_recommendation=expected_recommendation,
        expected_confidence_range=expected_confidence_range, expected_evidence_ids=list(expected_evidence_ids or []),
        persona=persona, status=ReviewStatus.PENDING,
    )
    return store.save_evaluation_case(case)


def approve_evaluation_case(case_id: str, reviewer: str, store: FeedbackStore) -> EvaluationCase:
    """Separate, explicit approval step for the EvaluationCase itself (an
    analyst may want to review the GENERATED case text before it becomes
    regression-test material, distinct from having already approved the
    source feedback). Only an APPROVED case may be promoted to a
    RegressionTest (regression.py enforces this)."""
    case = next((c for c in store.list_evaluation_cases() if c.case_id == case_id), None)
    if case is None:
        raise EvaluationCaseError(f"no evaluation case found with id {case_id!r}")
    store.append_case_status_event(case_id=case_id, status=ReviewStatus.APPROVED_FOR_EVALUATION,
                                    reviewer=reviewer, created_at=_now())
    return next(c for c in store.list_evaluation_cases() if c.case_id == case_id)


def list_dataset(version: str, store: FeedbackStore) -> list[EvaluationCase]:
    return store.list_evaluation_cases(dataset_version=version)
