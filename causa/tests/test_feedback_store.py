"""Step 9: store.py tests -- append-only persistence, no in-place mutation
of historical records, status materialized correctly from folded event
logs."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.models import FeedbackRating, FeedbackStatus, OutputType, ReviewStatus  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402


def _store():
    return FeedbackStore(Path(tempfile.mkdtemp()))


def test_saved_feedback_is_retrievable():
    store = _store()
    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)
    retrieved = store.get_feedback(fb.feedback_id)
    assert retrieved is not None
    assert retrieved.feedback_id == fb.feedback_id


def test_status_event_never_rewrites_base_file():
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)

    base_path = store._path("feedback")
    original_bytes = base_path.read_bytes()

    store.append_feedback_status_event(fb.feedback_id, status=FeedbackStatus.ACCEPTED, created_at="t")

    # the ORIGINAL feedback.jsonl line(s) are untouched -- the base file's
    # original bytes must still be a PREFIX of the (possibly grown) file.
    new_bytes = base_path.read_bytes()
    assert new_bytes == original_bytes  # append_feedback_status_event writes to a different file


def test_folded_status_reflects_latest_event():
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)
    assert store.get_feedback(fb.feedback_id).review_status == ReviewStatus.PENDING

    store.append_feedback_status_event(fb.feedback_id, review_status=ReviewStatus.REVIEWED, created_at="t1")
    assert store.get_feedback(fb.feedback_id).review_status == ReviewStatus.REVIEWED

    store.append_feedback_status_event(fb.feedback_id, review_status=ReviewStatus.APPROVED_FOR_EVALUATION,
                                        created_at="t2")
    assert store.get_feedback(fb.feedback_id).review_status == ReviewStatus.APPROVED_FOR_EVALUATION


def test_list_feedback_filters_by_status():
    store = _store()
    fb1 = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="s1")
    fb2 = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s2")
    store.save_feedback(fb1)
    store.save_feedback(fb2)
    store.append_feedback_status_event(fb2.feedback_id, review_status=ReviewStatus.REVIEWED, created_at="t")

    reviewed = store.list_feedback(review_status=ReviewStatus.REVIEWED)
    assert len(reviewed) == 1
    assert reviewed[0].feedback_id == fb2.feedback_id


def test_multiple_stores_same_directory_see_each_others_writes():
    directory = Path(tempfile.mkdtemp())
    store_a = FeedbackStore(directory)
    store_b = FeedbackStore(directory)
    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store_a.save_feedback(fb)
    assert store_b.get_feedback(fb.feedback_id) is not None


def test_persistence_survives_across_store_instances():
    directory = Path(tempfile.mkdtemp())
    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="s1")
    FeedbackStore(directory).save_feedback(fb)

    # New instance, same directory -- should reload from disk.
    reloaded_store = FeedbackStore(directory)
    assert reloaded_store.get_feedback(fb.feedback_id) is not None
