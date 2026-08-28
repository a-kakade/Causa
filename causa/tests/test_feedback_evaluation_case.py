"""Step 9: evaluation_case.py tests -- evaluation case created from approved
correction, expected/forbidden behaviour preserved, dataset versioning
works."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.correction import capture_business_context, store_correction  # noqa: E402
from feedback.evaluation_case import (  # noqa: E402
    approve_evaluation_case,
    create_evaluation_case,
    list_dataset,
    next_dataset_version,
)
from feedback.models import ContextType, CorrectionType, FeedbackRating, OutputType, ReviewStatus  # noqa: E402
from feedback.review import review_feedback  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402


def _store():
    return FeedbackStore(Path(tempfile.mkdtemp()))


def _approved_feedback(store, comment="wrong driver"):
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1", comment=comment)
    store.save_feedback(fb)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    return store.get_feedback(fb.feedback_id)


def test_evaluation_case_created_from_approved_feedback():
    store = _store()
    fb = _approved_feedback(store)
    corr = store_correction(fb.feedback_id, CorrectionType.WRONG_DRIVER, original_claim="Delivery caused decline",
                             corrected_claim="Holiday campaign changed composition", store=store)
    ctx = capture_business_context(fb.feedback_id, ContextType.HOLIDAY, "Holiday campaign", store)

    case = create_evaluation_case(
        fb, corr, ctx, store,
        forbidden_claims=["delivery caused review decline"],
        expected_behavior={"causal_language": "association_or_hypothesis", "mention_business_context": True},
    )
    assert case.source_feedback_id == fb.feedback_id
    assert case.forbidden_claims == ["delivery caused review decline"]
    assert case.expected_behavior["mention_business_context"] is True


def test_expected_and_forbidden_behaviour_both_preserved():
    store = _store()
    fb = _approved_feedback(store)
    case = create_evaluation_case(
        fb, None, None, store,
        expected_claims=["Delivery deterioration coincided with lower reviews."],
        forbidden_claims=["Delivery deterioration caused lower reviews."],
    )
    assert case.expected_claims == ["Delivery deterioration coincided with lower reviews."]
    assert case.forbidden_claims == ["Delivery deterioration caused lower reviews."]


def test_dataset_versioning_monotonic():
    store = _store()
    assert next_dataset_version(store) == "v1"
    fb1 = _approved_feedback(store)
    create_evaluation_case(fb1, None, None, store)
    assert next_dataset_version(store) == "v2"
    fb2 = _approved_feedback(store)
    create_evaluation_case(fb2, None, None, store, dataset_version="v2")
    assert next_dataset_version(store) == "v3"


def test_dataset_versioning_does_not_mutate_prior_versions():
    store = _store()
    fb1 = _approved_feedback(store)
    case_v1 = create_evaluation_case(fb1, None, None, store, expected_claims=["v1 claim"])
    fb2 = _approved_feedback(store)
    create_evaluation_case(fb2, None, None, store, dataset_version="v2", expected_claims=["v2 claim"])

    v1_cases = list_dataset("v1", store)
    assert len(v1_cases) == 1
    assert v1_cases[0].expected_claims == ["v1 claim"]
    assert v1_cases[0].case_id == case_v1.case_id


def test_approve_evaluation_case_moves_status():
    store = _store()
    fb = _approved_feedback(store)
    case = create_evaluation_case(fb, None, None, store)
    assert case.status == ReviewStatus.PENDING
    approved = approve_evaluation_case(case.case_id, reviewer="a", store=store)
    assert approved.status == ReviewStatus.APPROVED_FOR_EVALUATION


def test_evaluation_case_created_with_step7_style_input_context():
    """Integration with Step 7: an EvaluationCase for a RECOMMENDATION
    feedback should carry the business_context dict shape
    decision.constraint_engine.py consumes."""
    store = _store()
    fb = submit_feedback(FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="s1",
                          comment="Carrier capacity is exhausted.",
                          affected_recommendation_id="rec_delivery_delay_expedite_high_risk_shipments")
    store.save_feedback(fb)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)

    case = create_evaluation_case(
        current, None, None, store,
        input_context={"business_context": {"operational_capacity_available": False}},
        expected_recommendation={"tier": "BLOCKED"},
    )
    assert case.input_context["business_context"]["operational_capacity_available"] is False
    assert case.expected_recommendation == {"tier": "BLOCKED"}
