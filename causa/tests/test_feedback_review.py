"""Step 9: review.py tests -- pending feedback does not alter system
behaviour, approved feedback can become evaluation data, rejected feedback
does not become a regression test."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.evaluation_case import EvaluationCaseError, create_evaluation_case  # noqa: E402
from feedback.models import FeedbackRating, FeedbackStatus, OutputType, ReviewStatus  # noqa: E402
from feedback.review import ReviewError, contest_feedback, review_feedback  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402


def _store():
    return FeedbackStore(Path(tempfile.mkdtemp()))


def _submitted(store, rating=FeedbackRating.INCORRECT, comment="wrong"):
    fb = submit_feedback(rating, OutputType.STORY_CLAIM, session_id="s1", comment=comment)
    return store.save_feedback(fb)


def test_pending_feedback_cannot_become_evaluation_case():
    store = _store()
    fb = _submitted(store)
    try:
        create_evaluation_case(fb, None, None, store)
        assert False, "expected EvaluationCaseError"
    except EvaluationCaseError:
        pass


def test_reviewed_then_approved_workflow():
    store = _store()
    fb = _submitted(store)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="analyst_a", store=store)
    updated = review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="analyst_a", store=store)
    assert updated.review_status == ReviewStatus.APPROVED_FOR_EVALUATION


def test_cannot_skip_reviewed_straight_to_approved():
    store = _store()
    fb = _submitted(store)
    try:
        review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="analyst_a", store=store)
        assert False, "expected ReviewError"
    except ReviewError:
        pass


def test_approved_feedback_can_become_evaluation_case():
    store = _store()
    fb = _submitted(store)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    case = create_evaluation_case(current, None, None, store, forbidden_claims=["x caused y"])
    assert case.source_feedback_id == fb.feedback_id


def test_rejected_feedback_does_not_become_evaluation_case():
    store = _store()
    fb = _submitted(store)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.REJECTED, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    try:
        create_evaluation_case(current, None, None, store)
        assert False, "expected EvaluationCaseError"
    except EvaluationCaseError:
        pass


def test_terminal_status_cannot_be_reversed():
    store = _store()
    fb = _submitted(store)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.REJECTED, reviewer="a", store=store)
    try:
        review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
        assert False, "expected ReviewError"
    except ReviewError:
        pass


def test_review_unknown_feedback_raises():
    store = _store()
    try:
        review_feedback("FB_does_not_exist", ReviewStatus.REVIEWED, reviewer="a", store=store)
        assert False, "expected ReviewError"
    except ReviewError:
        pass


def test_history_preserved_across_review_transitions():
    """Never delete/mutate history -- the original feedback record must
    still be present after status transitions (folded, not overwritten)."""
    store = _store()
    fb = _submitted(store, comment="original comment text")
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    assert current.comment == "original comment text"
    assert current.feedback_id == fb.feedback_id


def test_contest_feedback_marks_both_contested():
    store = _store()
    fb_a = _submitted(store, comment="Promotion caused the AOV decline.")
    fb_b = _submitted(store, comment="Competitor pricing caused the AOV decline.")
    conflict = contest_feedback(fb_a.feedback_id, fb_b.feedback_id, "Promotion caused decline",
                                 "Competitor pricing caused decline", store)
    assert conflict.status == "CONTESTED"
    assert set(conflict.feedback_ids) == {fb_a.feedback_id, fb_b.feedback_id}
    a_current = store.get_feedback(fb_a.feedback_id)
    b_current = store.get_feedback(fb_b.feedback_id)
    assert a_current.status == FeedbackStatus.CONTESTED
    assert b_current.status == FeedbackStatus.CONTESTED
