"""Step 9: conflicting feedback tests -- multiple hypotheses preserved,
contested state handled correctly, no winner silently declared."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.models import FeedbackRating, FeedbackStatus, OutputType  # noqa: E402
from feedback.review import ReviewError, contest_feedback  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402


def _store():
    return FeedbackStore(Path(tempfile.mkdtemp()))


def test_conflicting_hypotheses_both_preserved():
    store = _store()
    fb_a = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="analyst_a",
                            comment="Promotion caused the AOV decline.")
    fb_b = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="analyst_b",
                            comment="Competitor pricing caused the AOV decline.")
    store.save_feedback(fb_a)
    store.save_feedback(fb_b)

    conflict = contest_feedback(fb_a.feedback_id, fb_b.feedback_id, "Promotion caused the AOV decline.",
                                 "Competitor pricing caused the AOV decline.", store)

    assert len(conflict.hypotheses) == 2
    assert "Promotion caused the AOV decline." in conflict.hypotheses
    assert "Competitor pricing caused the AOV decline." in conflict.hypotheses


def test_no_hypothesis_silently_chosen_as_winner():
    store = _store()
    fb_a = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="a")
    fb_b = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="b")
    store.save_feedback(fb_a)
    store.save_feedback(fb_b)

    contest_feedback(fb_a.feedback_id, fb_b.feedback_id, "hyp A", "hyp B", store)

    a_current = store.get_feedback(fb_a.feedback_id)
    b_current = store.get_feedback(fb_b.feedback_id)
    # Neither side is marked ACCEPTED -- both are CONTESTED, symmetric.
    assert a_current.status == FeedbackStatus.CONTESTED
    assert b_current.status == FeedbackStatus.CONTESTED
    assert a_current.status == b_current.status


def test_conflict_record_persisted_and_listable():
    store = _store()
    fb_a = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="a")
    fb_b = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="b")
    store.save_feedback(fb_a)
    store.save_feedback(fb_b)
    conflict = contest_feedback(fb_a.feedback_id, fb_b.feedback_id, "hyp A", "hyp B", store)

    all_conflicts = store.list_conflicts()
    assert any(c.conflict_id == conflict.conflict_id for c in all_conflicts)


def test_contest_unknown_feedback_raises():
    store = _store()
    fb_a = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="a")
    store.save_feedback(fb_a)
    try:
        contest_feedback(fb_a.feedback_id, "FB_does_not_exist", "hyp A", "hyp B", store)
        assert False, "expected ReviewError"
    except ReviewError:
        pass
