"""Step 9: capture.py tests -- valid feedback accepted, invalid rating
rejected, comment-only feedback supported, story/claim references
preserved."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.models import (  # noqa: E402
    FeedbackRating,
    FeedbackStatus,
    InvalidFeedbackError,
    OutputType,
    ReviewStatus,
)


def test_valid_feedback_accepted():
    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="sess1")
    assert fb.feedback_id
    assert fb.status == FeedbackStatus.UNREVIEWED
    assert fb.review_status == ReviewStatus.PENDING


def test_comment_only_requires_comment():
    try:
        submit_feedback(FeedbackRating.COMMENT_ONLY, OutputType.STORY_CLAIM, session_id="sess1")
        assert False, "expected InvalidFeedbackError"
    except InvalidFeedbackError:
        pass


def test_comment_only_with_comment_accepted():
    fb = submit_feedback(FeedbackRating.COMMENT_ONLY, OutputType.STORY_CLAIM, session_id="sess1",
                          comment="Just a note.")
    assert fb.comment == "Just a note."


def test_invalid_rating_type_rejected():
    try:
        submit_feedback("NOT_A_RATING", OutputType.STORY_CLAIM, session_id="sess1")
        assert False, "expected InvalidFeedbackError"
    except InvalidFeedbackError:
        pass


def test_invalid_output_type_rejected():
    try:
        submit_feedback(FeedbackRating.CORRECT, "NOT_AN_OUTPUT_TYPE", session_id="sess1")
        assert False, "expected InvalidFeedbackError"
    except InvalidFeedbackError:
        pass


def test_empty_session_id_rejected():
    try:
        submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="")
        assert False, "expected InvalidFeedbackError"
    except InvalidFeedbackError:
        pass


def test_user_id_optional_no_auth_required():
    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="sess1")
    assert fb.user_id is None


def test_story_and_claim_references_preserved():
    fb = submit_feedback(
        FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="sess1", story_id="STORY_001",
        affected_claim_keys=["STORY_001:0:2"], affected_evidence_ids=["EV006", "EV007"],
    )
    assert fb.story_id == "STORY_001"
    assert fb.affected_claim_keys == ["STORY_001:0:2"]
    assert fb.affected_evidence_ids == ["EV006", "EV007"]


def test_recommendation_reference_preserved():
    fb = submit_feedback(
        FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="sess1",
        affected_recommendation_id="rec_delivery_delay_expedite_high_risk_shipments",
    )
    assert fb.affected_recommendation_id == "rec_delivery_delay_expedite_high_risk_shipments"


def test_to_dict_round_trip():
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="sess1",
                          comment="wrong driver")
    from feedback.models import Feedback
    restored = Feedback.from_dict(fb.to_dict())
    assert restored.feedback_id == fb.feedback_id
    assert restored.rating == fb.rating
    assert restored.comment == fb.comment
