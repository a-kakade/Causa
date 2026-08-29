"""
routes/feedback.py — POST/GET /api/feedback, learning/evaluation endpoints
(Step 9).

Every write goes through the REAL src/feedback/* pipeline
(capture.submit_feedback -> FeedbackStore.save_feedback); nothing here
invents a persistence mechanism of its own. Explicitly never triggers
retraining/redeployment -- there is no code path in src/feedback/ that does,
and this layer adds none.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.serializers import feedback_dict

router = APIRouter(prefix="/api", tags=["feedback"])

FEEDBACK_LIFECYCLE_NOTE = (
    "Feedback captured -> classified -> correction stored -> human review -> evaluation case -> "
    "regression test -> offline evaluation. Feedback does NOT automatically retrain or deploy the model."
)


def _store():
    from feedback.store import FeedbackStore
    return FeedbackStore()


class SubmitFeedbackRequest(BaseModel):
    rating: str
    output_type: str
    session_id: str
    investigation_id: Optional[str] = None
    user_id: Optional[str] = None
    story_id: Optional[str] = None
    comment: Optional[str] = None
    affected_evidence_ids: list[str] = []
    affected_claim_keys: list[str] = []
    affected_recommendation_id: Optional[str] = None


@router.post("/feedback")
def submit_feedback(body: SubmitFeedbackRequest):
    from feedback.capture import submit_feedback as capture_submit
    from feedback.classifier import classify_feedback
    from feedback.models import FeedbackRating, OutputType

    try:
        rating = FeedbackRating(body.rating)
        output_type = OutputType(body.output_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    feedback = capture_submit(
        rating=rating, output_type=output_type, session_id=body.session_id, user_id=body.user_id,
        story_id=body.story_id or body.investigation_id, comment=body.comment,
        affected_evidence_ids=body.affected_evidence_ids, affected_claim_keys=body.affected_claim_keys,
        affected_recommendation_id=body.affected_recommendation_id,
    )
    categories, generated_by = classify_feedback(feedback, comment=body.comment)
    feedback.categories = categories
    saved = _store().save_feedback(feedback)
    return {**feedback_dict(saved), "classification_generated_by": generated_by.value,
            "lifecycle": FEEDBACK_LIFECYCLE_NOTE}


@router.get("/feedback/{feedback_id}")
def get_feedback(feedback_id: str):
    fb = _store().get_feedback(feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail=f"No feedback {feedback_id!r}")
    correction = _store().get_correction_for_feedback(feedback_id)
    return {**feedback_dict(fb), "correction": correction.to_dict() if correction else None,
            "lifecycle": FEEDBACK_LIFECYCLE_NOTE}


@router.get("/feedback")
def list_feedback(story_id: Optional[str] = None, status: Optional[str] = None, review_status: Optional[str] = None):
    filters = {}
    if story_id:
        filters["story_id"] = story_id
    records = _store().list_feedback(**filters)
    if status:
        records = [r for r in records if r.status.value == status]
    if review_status:
        records = [r for r in records if r.review_status.value == review_status]
    return {"count": len(records), "feedback": [feedback_dict(r) for r in records]}


@router.get("/investigations/{investigation_id}/feedback")
def list_investigation_feedback(investigation_id: str):
    records = _store().list_feedback(story_id=investigation_id)
    return {"investigation_id": investigation_id, "count": len(records), "feedback": [feedback_dict(r) for r in records]}


class ReviewFeedbackRequest(BaseModel):
    decision: str
    reviewer: str
    rationale: Optional[str] = None


@router.post("/feedback/{feedback_id}/review")
def review_feedback_route(feedback_id: str, body: ReviewFeedbackRequest):
    from feedback.models import ReviewStatus
    from feedback.review import ReviewError, review_feedback

    try:
        decision = ReviewStatus(body.decision)
        updated = review_feedback(feedback_id, decision, body.reviewer, _store(), rationale=body.rationale)
    except (ValueError, ReviewError) as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return feedback_dict(updated)


@router.get("/learning/evaluation-cases")
def list_evaluation_cases(dataset_version: Optional[str] = None):
    filters = {"dataset_version": dataset_version} if dataset_version else {}
    cases = _store().list_evaluation_cases(**filters)
    return {"count": len(cases), "cases": [c.to_dict() for c in cases]}


@router.get("/learning/regressions")
def list_regressions():
    tests = _store().list_regression_tests()
    return {"count": len(tests), "regression_tests": [t.to_dict() for t in tests]}


@router.get("/learning/evaluations")
def list_evaluations():
    # There is no persisted "offline evaluation run log" store in src/feedback/
    # -- run_offline_evaluation()/compare_baseline_candidate() in
    # feedback/evaluator.py are on-demand functions, not a durable table.
    # Report that honestly rather than fabricating a history.
    return {
        "runs": [],
        "note": "Offline evaluation runs (src/feedback/evaluator.py::run_offline_evaluation) are executed "
                "on demand against a dataset_version's evaluation cases; this prototype does not yet persist "
                "a log of past runs, so an empty list here means 'not yet run/stored', not 'zero evaluations "
                "were ever computed'.",
    }
