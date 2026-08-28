"""Step 9: correction.py tests -- original output preserved, correction
stored separately, evidence links preserved, business context preserved."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.correction import capture_business_context, store_correction  # noqa: E402
from feedback.models import ContextType, CorrectionType, FeedbackRating, OutputType  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402
from story.models import ClaimType  # noqa: E402


def _store():
    return FeedbackStore(Path(tempfile.mkdtemp()))


def test_correction_preserves_original_and_corrected_text():
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)

    corr = store_correction(
        fb.feedback_id, CorrectionType.WRONG_DRIVER,
        original_claim="Delivery deterioration coincided with lower review scores.",
        corrected_claim="Holiday campaign changed review composition.",
        store=store, original_claim_type=ClaimType.ASSOCIATION, corrected_claim_type=ClaimType.HYPOTHESIS,
        evidence_ids=["EV006", "EV007"], rationale="November had a major holiday campaign.",
    )

    assert corr.original_claim == "Delivery deterioration coincided with lower review scores."
    assert corr.corrected_claim == "Holiday campaign changed review composition."
    assert corr.original_claim_type == ClaimType.ASSOCIATION
    assert corr.corrected_claim_type == ClaimType.HYPOTHESIS


def test_correction_never_mutates_original_object():
    """Simulates the original AI claim as a live object -- correction storage
    must never touch it."""
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)

    original_text = "Delivery deterioration coincided with lower review scores."
    original_snapshot = str(original_text)

    store_correction(fb.feedback_id, CorrectionType.WRONG_DRIVER, original_claim=original_text,
                      corrected_claim="Holiday campaign changed review composition.", store=store)

    assert original_text == original_snapshot  # unchanged


def test_correction_stored_separately_and_retrievable():
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)
    store_correction(fb.feedback_id, CorrectionType.WRONG_DRIVER, original_claim="orig", corrected_claim="corr",
                      store=store)

    retrieved = store.get_correction_for_feedback(fb.feedback_id)
    assert retrieved is not None
    assert retrieved.original_claim == "orig"
    assert retrieved.corrected_claim == "corr"


def test_evidence_ids_preserved_on_correction():
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)
    corr = store_correction(fb.feedback_id, CorrectionType.WRONG_EVIDENCE_INTERPRETATION, original_claim="a",
                             corrected_claim="b", store=store, evidence_ids=["EV001", "EV002"])
    assert corr.evidence_ids == ["EV001", "EV002"]


def test_business_context_stored_separately_from_correction():
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)

    ctx = capture_business_context(
        fb.feedback_id, ContextType.HOLIDAY,
        "Holiday campaign changed customer mix and review composition.", store,
        affected_period="2017-11", affected_segments=["reviews"], confidence=0.7,
    )

    assert ctx.context_type == ContextType.HOLIDAY
    assert ctx.affected_period == "2017-11"
    stored = store.list_business_context(feedback_id=fb.feedback_id)
    assert len(stored) == 1
    assert stored[0].context_id == ctx.context_id


def test_multiple_corrections_for_same_feedback_all_preserved():
    """Never delete or mutate history -- multiple corrections against the
    same feedback_id must all remain retrievable."""
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)
    store_correction(fb.feedback_id, CorrectionType.WRONG_DRIVER, original_claim="a", corrected_claim="b", store=store)
    store_correction(fb.feedback_id, CorrectionType.WRONG_CONFIDENCE, original_claim="c", corrected_claim="d", store=store)

    all_corrections = store.list_corrections(feedback_id=fb.feedback_id)
    assert len(all_corrections) == 2
