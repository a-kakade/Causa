"""Step 9: full end-to-end pipeline test (spec section 35) --

AI STORY -> "Delivery deterioration caused review decline."
Human: "No. November holiday campaign changed review composition."
-> Feedback classification: DRIVER + NARRATIVE
-> Correction: driver interpretation rejected
-> Business context: Holiday campaign
-> Evaluation case: causal claim forbidden, association/hypothesis expected
-> Approved regression test
-> Future Step 8 generation: verifier/evaluation ensures the causal error
   does not recur.

Also covers the demo's 5 fixture cases (spec section 26) at a unit level to
prove the pipeline handles CORRECT, wrong-driver, wrong-recommendation,
wrong-confidence, and missing-driver feedback uniformly."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.classifier import classify_feedback  # noqa: E402
from feedback.correction import capture_business_context, store_correction  # noqa: E402
from feedback.evaluation_case import approve_evaluation_case, create_evaluation_case  # noqa: E402
from feedback.evaluator import CandidateOutput, run_offline_evaluation  # noqa: E402
from feedback.models import (  # noqa: E402
    ContextType,
    CorrectionType,
    FeedbackCategory,
    FeedbackRating,
    OutputType,
    ReviewStatus,
)
from feedback.regression import promote_to_regression_test, run_regression_tests  # noqa: E402
from feedback.review import review_feedback  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402
from story.models import ClaimType  # noqa: E402


def test_full_driver_narrative_correction_pipeline():
    store = FeedbackStore(Path(tempfile.mkdtemp()))

    # 1. AI story claim (simulated).
    ai_claim_text = "Delivery deterioration coincided with lower review scores."

    # 2. Human feedback.
    fb = submit_feedback(
        FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="analyst_session_1", story_id="STORY_NOV2017",
        affected_claim_keys=["STORY_NOV2017:1:0"], affected_evidence_ids=["EV006", "EV007"],
        comment="No. November holiday campaign changed review composition.",
    )
    store.save_feedback(fb)

    # 3. Classification.
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.NARRATIVE in categories

    # 4. Correction.
    correction = store_correction(
        fb.feedback_id, CorrectionType.WRONG_DRIVER, original_claim=ai_claim_text,
        corrected_claim="Holiday campaign changed customer mix and review composition.", store=store,
        original_claim_type=ClaimType.ASSOCIATION, corrected_claim_type=ClaimType.HYPOTHESIS,
        evidence_ids=["EV006", "EV007"], rationale="November had a major holiday campaign.",
    )
    assert correction.original_claim == ai_claim_text  # original preserved, never overwritten

    # 5. Business context.
    context = capture_business_context(
        fb.feedback_id, ContextType.HOLIDAY,
        "Holiday campaign changed customer mix and review composition.", store,
        affected_period="2017-11",
    )

    # 6. Human review -- required before any evaluation data is produced.
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="analyst_a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="analyst_a", store=store)
    current_fb = store.get_feedback(fb.feedback_id)

    # 7. Evaluation case generation.
    case = create_evaluation_case(
        current_fb, correction, context, store,
        input_context={"period": "2017-11", "delivery_change_pct": 27.9, "review_change_pct": -5.2},
        forbidden_claims=["delivery caused review decline", "delivery deterioration caused lower reviews"],
        expected_behavior={"causal_language": "association_or_hypothesis", "mention_business_context": True},
        expected_claims=["holiday campaign"],
    )
    assert case.dataset_version == "v1"

    # 8. Approve the case, promote to regression test.
    approve_evaluation_case(case.case_id, reviewer="analyst_a", store=store)
    regression_test = promote_to_regression_test(case.case_id, store)

    # 9. Offline evaluation against a GOOD candidate (never repeats the causal error).
    def good_candidate(c):
        return CandidateOutput(claim_texts=[
            "Delivery deterioration coincided with lower review scores.",
            "A holiday campaign in November is a plausible explanation for the shift in review composition.",
        ])

    report = run_offline_evaluation([case], good_candidate)
    assert report.passed == 1
    assert report.metrics["causal_correctness"] == 1.0

    # 10. Regression test also passes for the good candidate.
    reg_report = run_regression_tests([regression_test], store, good_candidate)
    assert reg_report.passed == 1

    # 11. A REGRESSED candidate that reintroduces the causal error is caught.
    def regressed_candidate(c):
        return CandidateOutput(claim_texts=["Delivery deterioration caused lower reviews."])

    reg_report_bad = run_regression_tests([regression_test], store, regressed_candidate)
    assert reg_report_bad.failed == 1
    assert "forbidden" in reg_report_bad.results[0].failure_reasons[0]


def test_case1_correct_feedback_requires_no_correction():
    store = FeedbackStore(Path(tempfile.mkdtemp()))
    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="s1", story_id="STORY1")
    store.save_feedback(fb)
    categories, _ = classify_feedback(fb)
    assert categories == []  # no correction needed, no category implied


def test_case3_wrong_recommendation_carrier_capacity():
    store = FeedbackStore(Path(tempfile.mkdtemp()))
    fb = submit_feedback(
        FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="s1",
        affected_recommendation_id="rec_delivery_delay_expedite_high_risk_shipments",
        comment="Carrier capacity is exhausted.",
    )
    store.save_feedback(fb)
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.RECOMMENDATION in categories

    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    case = create_evaluation_case(current, None, None, store,
                                   input_context={"business_context": {"operational_capacity_available": False}},
                                   expected_recommendation={"tier": "BLOCKED"})
    assert case.expected_recommendation["tier"] == "BLOCKED"


def test_case4_wrong_confidence():
    store = FeedbackStore(Path(tempfile.mkdtemp()))
    fb = submit_feedback(FeedbackRating.WRONG_CONFIDENCE, OutputType.STORY_CLAIM, session_id="s1",
                          comment="Evidence is weak; confidence should be lower.")
    store.save_feedback(fb)
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.CONFIDENCE in categories

    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    case = create_evaluation_case(current, None, None, store, expected_confidence_range=(0.0, 0.5))

    def over_confident_candidate(c):
        return CandidateOutput(confidence=0.92)

    report = run_offline_evaluation([case], over_confident_candidate)
    assert report.passed == 0


def test_case5_missing_driver_pricing():
    store = FeedbackStore(Path(tempfile.mkdtemp()))
    fb = submit_feedback(FeedbackRating.MISSING_DRIVER, OutputType.STORY_CLAIM, session_id="s1",
                          comment="Pricing change was another important driver.")
    store.save_feedback(fb)
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.DRIVER in categories

    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    case = create_evaluation_case(current, None, None, store, expected_claims=["pricing change"])

    def missing_pricing_candidate(c):
        return CandidateOutput(claim_texts=["Product mix explains the AOV decline."])

    report = run_offline_evaluation([case], missing_pricing_candidate)
    assert report.passed == 0
    assert report.metrics["numeric_accuracy"] == 0.0
