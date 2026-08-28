"""
step9_feedback_learning_demo.py — walks through the full Human Feedback &
Learning Loop against 5 deterministic fixtures (spec section 26):

  Case 1 — Correct               (no correction needed)
  Case 2 — Wrong Driver          (delivery -> holiday campaign, causal-language regression test)
  Case 3 — Wrong Recommendation  (expedite shipments -> carrier capacity exhausted, Step 7 integration)
  Case 4 — Wrong Confidence      (0.92 -> too high given weak evidence)
  Case 5 — Missing Driver        (product mix -> pricing change also matters)

Demonstrates, per fixture, the 9-stage pipeline:
  1. AI-generated story/recommendation (built the same way
     step7_/step8_..._demo.py build their demo objects)
  2. Human feedback (feedback.capture.submit_feedback)
  3. Feedback classification (feedback.classifier.classify_feedback)
  4. Analyst correction (feedback.correction.store_correction)
  5. Business context capture (feedback.correction.capture_business_context)
  6. Evaluation case generation (feedback.evaluation_case.create_evaluation_case)
  7. Evaluation dataset (versioned, feedback.evaluation_case.next_dataset_version)
  8. Regression test creation (feedback.regression.promote_to_regression_test)
  9. Offline evaluation result (feedback.evaluator.run_offline_evaluation),
     including a deliberately-regressed candidate to prove a caught failure
     is actually detectable, then a baseline-vs-candidate comparison.

Runs with llm_client=None throughout -- deterministic, reproducible, no live
API dependency, matching scripts/step7_decision_engine_demo.py and
scripts/step8_persona_storytelling_demo.py's own precedent. Writes
reports/step9_validation.json in the same shape as step7/8's reports.
"""

from __future__ import annotations

import datetime
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.classifier import classify_feedback  # noqa: E402
from feedback.config import FeedbackConfig  # noqa: E402
from feedback.correction import capture_business_context, store_correction  # noqa: E402
from feedback.evaluation_case import approve_evaluation_case, create_evaluation_case  # noqa: E402
from feedback.evaluator import CandidateOutput, compare_baseline_candidate, run_offline_evaluation  # noqa: E402
from feedback.models import (  # noqa: E402
    ContextType,
    CorrectionType,
    FeedbackCategory,
    FeedbackRating,
    OutputType,
    ReviewStatus,
    claim_key,
)
from feedback.regression import promote_to_regression_test, run_regression_tests  # noqa: E402
from feedback.review import review_feedback  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402
from story.models import ClaimType  # noqa: E402

TEST_FILES = [
    "tests/test_feedback_capture.py", "tests/test_feedback_classifier.py", "tests/test_feedback_correction.py",
    "tests/test_feedback_review.py", "tests/test_feedback_conflict.py", "tests/test_feedback_evaluation_case.py",
    "tests/test_feedback_regression.py", "tests/test_feedback_offline_evaluation.py", "tests/test_feedback_store.py",
    "tests/test_feedback_step7_integration.py", "tests/test_feedback_step8_integration.py",
    "tests/test_feedback_safety.py", "tests/test_feedback_end_to_end.py", "tests/test_feedback_config.py",
]

DEMO_STORE_DIR = REPO_ROOT / "data" / "feedback"


def _now() -> str:
    return datetime.datetime.now(timezone.utc).isoformat()


def _approve(store: FeedbackStore, feedback_id: str) -> None:
    review_feedback(feedback_id, ReviewStatus.REVIEWED, reviewer="analyst_a", store=store)
    review_feedback(feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="analyst_a", store=store)


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


# ---------------------------------------------------------------------------
# Case 1 — Correct
# ---------------------------------------------------------------------------

def demo_case1_correct(store: FeedbackStore) -> dict:
    _section("CASE 1 — Correct")
    ai_output = "Revenue increased 52.1% in November 2017, driven by a 62.9% increase in order volume."
    print(f"1. AI output: {ai_output!r}")

    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="demo_session",
                          story_id="STORY_NOV2017")
    store.save_feedback(fb)
    print(f"2. Human feedback: rating={fb.rating.value} (no comment needed)")

    categories, _ = classify_feedback(fb)
    print(f"3. Classification: {[c.value for c in categories]} (none -- nothing to correct)")

    print("4-8. No correction, no evaluation case, no regression test -- CORRECT feedback needs none of these.")
    return {"feedback_id": fb.feedback_id, "categories": [c.value for c in categories]}


# ---------------------------------------------------------------------------
# Case 2 — Wrong Driver (the spec's own worked example, sections 6/12/35)
# ---------------------------------------------------------------------------

def demo_case2_wrong_driver(store: FeedbackStore) -> dict:
    _section("CASE 2 — Wrong Driver")
    ai_claim = "Delivery deterioration coincided with lower review scores."
    print(f"1. AI story claim: {ai_claim!r}")

    key = claim_key("STORY_NOV2017", 1, 0)
    fb = submit_feedback(
        FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="demo_session", story_id="STORY_NOV2017",
        affected_claim_keys=[key], affected_evidence_ids=["EV006", "EV007"],
        comment="No — November had a major holiday campaign that changed review composition.",
    )
    store.save_feedback(fb)
    print(f"2. Human feedback: {fb.comment!r}")

    categories, generated_by = classify_feedback(fb)
    print(f"3. Classification ({generated_by.value}): {[c.value for c in categories]}")
    assert FeedbackCategory.NARRATIVE in categories

    correction = store_correction(
        fb.feedback_id, CorrectionType.WRONG_DRIVER, original_claim=ai_claim,
        corrected_claim="Holiday campaign changed customer mix and review composition.", store=store,
        original_claim_type=ClaimType.ASSOCIATION, corrected_claim_type=ClaimType.HYPOTHESIS,
        evidence_ids=["EV006", "EV007"], rationale="November had a major holiday campaign.",
    )
    print(f"4. Correction stored: original preserved={correction.original_claim == ai_claim!r}")
    print(f"   original: {correction.original_claim!r}")
    print(f"   corrected: {correction.corrected_claim!r}")

    context = capture_business_context(
        fb.feedback_id, ContextType.HOLIDAY,
        "Holiday campaign changed customer mix and review composition.", store, affected_period="2017-11",
    )
    print(f"5. Business context captured: {context.context_type.value} — {context.description!r}")

    _approve(store, fb.feedback_id)
    current_fb = store.get_feedback(fb.feedback_id)
    print(f"6. Human review: review_status={current_fb.review_status.value}")

    case = create_evaluation_case(
        current_fb, correction, context, store,
        input_context={"period": "2017-11", "delivery_change_pct": 27.9, "review_change_pct": -5.2},
        forbidden_claims=["delivery caused review decline", "delivery deterioration caused lower reviews"],
        expected_behavior={"causal_language": "association_or_hypothesis", "mention_business_context": True},
        expected_claims=["holiday campaign"],
    )
    print(f"7. Evaluation case created: dataset_version={case.dataset_version}, case_id={case.case_id}")

    approve_evaluation_case(case.case_id, reviewer="analyst_a", store=store)
    test = promote_to_regression_test(case.case_id, store)
    print(f"8. Regression test created: {test.test_id}")

    def good_candidate(c):
        return CandidateOutput(claim_texts=[
            "Delivery deterioration coincided with lower review scores.",
            "A holiday campaign in November is a plausible explanation for the shift in review composition.",
        ])

    def regressed_candidate(c):
        return CandidateOutput(claim_texts=["Delivery deterioration caused lower reviews."])

    good_report = run_offline_evaluation([case], good_candidate, dataset_version=case.dataset_version)
    reg_report_good = run_regression_tests([test], store, good_candidate)
    reg_report_bad = run_regression_tests([test], store, regressed_candidate)
    print(f"9. Offline evaluation (good candidate): passed={good_report.passed}/{good_report.total_cases}, "
          f"metrics={good_report.metrics}")
    print(f"   Regression test vs good candidate: passed={reg_report_good.passed}")
    print(f"   Regression test vs REGRESSED candidate (reintroduces causal claim): "
          f"passed={reg_report_good.passed}, failed={reg_report_bad.failed} "
          f"({reg_report_bad.results[0].failure_reasons[0] if reg_report_bad.results[0].failure_reasons else ''})")

    assert reg_report_good.passed == 1
    assert reg_report_bad.failed == 1
    return {"feedback_id": fb.feedback_id, "case_id": case.case_id, "test_id": test.test_id,
            "good_report": good_report.to_dict(), "regression_bad_report": reg_report_bad.to_dict()}


# ---------------------------------------------------------------------------
# Case 3 — Wrong Recommendation (Step 7 integration, spec section 25)
# ---------------------------------------------------------------------------

def demo_case3_wrong_recommendation(store: FeedbackStore) -> dict:
    _section("CASE 3 — Wrong Recommendation")
    ai_action = "Expedite high-risk shipments."
    print(f"1. AI recommendation: {ai_action!r} (tier=TOP)")

    fb = submit_feedback(
        FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="demo_session",
        affected_recommendation_id="rec_delivery_delay_expedite_high_risk_shipments",
        comment="Wrong recommendation. Carrier capacity is currently exhausted.",
    )
    store.save_feedback(fb)
    print(f"2. Human feedback: {fb.comment!r}")

    categories, _ = classify_feedback(fb)
    print(f"3. Classification: {[c.value for c in categories]}")
    assert FeedbackCategory.RECOMMENDATION in categories

    correction = store_correction(
        fb.feedback_id, CorrectionType.WRONG_RECOMMENDATION, original_claim=ai_action,
        corrected_claim="Do not recommend expedited shipments under current capacity constraint.", store=store,
        rationale="Carrier capacity constraint currently blocks execution.",
    )
    print(f"4. Correction stored: {correction.corrected_claim!r}")

    context = capture_business_context(
        fb.feedback_id, ContextType.OPERATIONAL_EVENT, "Carrier capacity constraint.", store,
    )
    print(f"5. Business context captured: {context.context_type.value}")

    _approve(store, fb.feedback_id)
    current_fb = store.get_feedback(fb.feedback_id)
    print(f"6. Human review: review_status={current_fb.review_status.value}")

    case = create_evaluation_case(
        current_fb, correction, context, store,
        input_context={"business_context": {"operational_capacity_available": False}, "owner": "ops_team"},
        expected_recommendation={"tier": "BLOCKED"},
        expected_behavior={"must_not_rank_as_executable": True},
    )
    print(f"7. Evaluation case created: dataset_version={case.dataset_version}, "
          f"expected_recommendation={case.expected_recommendation}")

    approve_evaluation_case(case.case_id, reviewer="analyst_a", store=store)
    test = promote_to_regression_test(case.case_id, store)
    print(f"8. Regression test created: {test.test_id}")

    def correctly_blocked(c):
        return CandidateOutput(recommendation={"tier": "BLOCKED"})

    def wrongly_still_top(c):
        return CandidateOutput(recommendation={"tier": "TOP"})

    report_good = run_offline_evaluation([case], correctly_blocked, dataset_version=case.dataset_version)
    report_bad = run_offline_evaluation([case], wrongly_still_top, dataset_version=case.dataset_version)
    print(f"9. Offline evaluation: correctly-blocked candidate passed={report_good.passed}, "
          f"wrongly-still-top candidate passed={report_bad.passed}")
    assert report_good.passed == 1 and report_bad.passed == 0
    return {"feedback_id": fb.feedback_id, "case_id": case.case_id, "test_id": test.test_id}


# ---------------------------------------------------------------------------
# Case 4 — Wrong Confidence
# ---------------------------------------------------------------------------

def demo_case4_wrong_confidence(store: FeedbackStore) -> dict:
    _section("CASE 4 — Wrong Confidence")
    print("1. AI output: confidence=0.92")

    fb = submit_feedback(FeedbackRating.WRONG_CONFIDENCE, OutputType.STORY_CLAIM, session_id="demo_session",
                          story_id="STORY_NOV2017", comment="Evidence is weak; confidence should be lower.")
    store.save_feedback(fb)
    print(f"2. Human feedback: {fb.comment!r}")

    categories, _ = classify_feedback(fb)
    print(f"3. Classification: {[c.value for c in categories]}")
    assert FeedbackCategory.CONFIDENCE in categories

    correction = store_correction(
        fb.feedback_id, CorrectionType.WRONG_CONFIDENCE, original_claim="confidence=0.92",
        corrected_claim="confidence should be <= 0.5 given weak/associative-only evidence", store=store,
        rationale="Evidence is only associative (T3), not causally validated.",
    )
    print(f"4. Correction stored: {correction.corrected_claim!r}")
    print("5. No new business context needed for this correction.")

    _approve(store, fb.feedback_id)
    current_fb = store.get_feedback(fb.feedback_id)
    print(f"6. Human review: review_status={current_fb.review_status.value}")

    case = create_evaluation_case(current_fb, correction, None, store, expected_confidence_range=(0.0, 0.5))
    print(f"7. Evaluation case created: expected_confidence_range={case.expected_confidence_range}")

    approve_evaluation_case(case.case_id, reviewer="analyst_a", store=store)
    test = promote_to_regression_test(case.case_id, store)
    print(f"8. Regression test created: {test.test_id}")

    def over_confident(c):
        return CandidateOutput(confidence=0.92)

    def appropriately_hedged(c):
        return CandidateOutput(confidence=0.4)

    report_bad = run_offline_evaluation([case], over_confident, dataset_version=case.dataset_version)
    report_good = run_offline_evaluation([case], appropriately_hedged, dataset_version=case.dataset_version)
    print(f"9. Offline evaluation: over-confident candidate passed={report_bad.passed}, "
          f"appropriately-hedged candidate passed={report_good.passed}")
    assert report_bad.passed == 0 and report_good.passed == 1
    return {"feedback_id": fb.feedback_id, "case_id": case.case_id, "test_id": test.test_id}


# ---------------------------------------------------------------------------
# Case 5 — Missing Driver
# ---------------------------------------------------------------------------

def demo_case5_missing_driver(store: FeedbackStore) -> dict:
    _section("CASE 5 — Missing Driver")
    ai_claim = "AOV decline is explained by product mix."
    print(f"1. AI output: {ai_claim!r}")

    fb = submit_feedback(FeedbackRating.MISSING_DRIVER, OutputType.STORY_CLAIM, session_id="demo_session",
                          story_id="STORY_NOV2017", comment="Pricing change was another important driver.")
    store.save_feedback(fb)
    print(f"2. Human feedback: {fb.comment!r}")

    categories, _ = classify_feedback(fb)
    print(f"3. Classification: {[c.value for c in categories]}")
    assert FeedbackCategory.DRIVER in categories

    correction = store_correction(
        fb.feedback_id, CorrectionType.MISSING_DRIVER, original_claim=ai_claim,
        corrected_claim="AOV decline is explained by product mix AND a pricing change.", store=store,
        rationale="Pricing change was omitted from the original narrative.",
    )
    print(f"4. Correction stored: {correction.corrected_claim!r}")
    context = capture_business_context(fb.feedback_id, ContextType.PRICING_EVENT, "Pricing change affected AOV.",
                                        store)
    print(f"5. Business context captured: {context.context_type.value}")

    _approve(store, fb.feedback_id)
    current_fb = store.get_feedback(fb.feedback_id)
    print(f"6. Human review: review_status={current_fb.review_status.value}")

    case = create_evaluation_case(current_fb, correction, context, store, expected_claims=["pricing change"])
    print(f"7. Evaluation case created: expected_claims={case.expected_claims}")

    approve_evaluation_case(case.case_id, reviewer="analyst_a", store=store)
    test = promote_to_regression_test(case.case_id, store)
    print(f"8. Regression test created: {test.test_id}")

    def still_missing(c):
        return CandidateOutput(claim_texts=["Product mix explains the AOV decline."])

    def fixed_candidate(c):
        return CandidateOutput(claim_texts=["Product mix and a pricing change explain the AOV decline."])

    report_bad = run_offline_evaluation([case], still_missing, dataset_version=case.dataset_version)
    report_good = run_offline_evaluation([case], fixed_candidate, dataset_version=case.dataset_version)
    print(f"9. Offline evaluation: still-missing candidate passed={report_bad.passed}, "
          f"fixed candidate passed={report_good.passed}")
    assert report_bad.passed == 0 and report_good.passed == 1
    return {"feedback_id": fb.feedback_id, "case_id": case.case_id, "test_id": test.test_id}


# ---------------------------------------------------------------------------
# Baseline vs candidate comparison across the whole dataset (spec section 19)
# ---------------------------------------------------------------------------

def demo_dataset_level_evaluation(store: FeedbackStore) -> dict:
    _section("DATASET-LEVEL OFFLINE EVALUATION (v1 vs a regressed v1-candidate)")
    all_cases = store.list_evaluation_cases(status=ReviewStatus.APPROVED_FOR_EVALUATION)
    print(f"Evaluating all {len(all_cases)} APPROVED_FOR_EVALUATION cases in the dataset.")

    def baseline_candidate(case):
        # A well-behaved candidate: avoids forbidden causal language, hits
        # expected claims, respects constraint-driven recommendation tiers,
        # and keeps confidence in range where declared.
        return CandidateOutput(
            claim_texts=[
                "Delivery deterioration coincided with lower review scores.",
                "A holiday campaign in November may explain the shift in review composition.",
                "Product mix and a pricing change explain the AOV decline.",
            ],
            recommendation={"tier": "BLOCKED"}, confidence=0.4,
        )

    def regressed_candidate(case):
        # Reintroduces the exact causal-language error Case 2 corrected.
        return CandidateOutput(
            claim_texts=["Delivery deterioration caused lower reviews."],
            recommendation={"tier": "TOP"}, confidence=0.92,
        )

    baseline_report = run_offline_evaluation(all_cases, baseline_candidate, dataset_version="baseline")
    candidate_report = run_offline_evaluation(all_cases, regressed_candidate, dataset_version="regressed_candidate")
    comparison = compare_baseline_candidate(baseline_report, candidate_report)

    print(f"Baseline:  passed={baseline_report.passed}/{baseline_report.total_cases}, "
          f"metrics={baseline_report.metrics}")
    print(f"Candidate: passed={candidate_report.passed}/{candidate_report.total_cases}, "
          f"metrics={candidate_report.metrics}")
    print(f"Regressions detected: {comparison.regressions}")
    print(f"Improvements detected: {comparison.improvements}")
    print("Deploy decision: NOT automatic -- this comparison is handed to a human, per spec section 19/20.")

    return {"baseline": baseline_report.to_dict(), "candidate": candidate_report.to_dict(),
            "comparison": comparison.to_dict()}


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TEST_FILES, "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
            "failed_tests": failed, "all_passed": proc.returncode == 0}


def main() -> None:
    t_start = time.time()

    # Fresh, isolated store for a reproducible demo run.
    if DEMO_STORE_DIR.exists():
        shutil.rmtree(DEMO_STORE_DIR)
    store = FeedbackStore(DEMO_STORE_DIR)

    config = FeedbackConfig.load()
    print(f"Loaded config/feedback.yaml (min_approvals_required={config.min_approvals_required()}, "
          f"evaluation_thresholds={config.evaluation_thresholds()})")

    case1 = demo_case1_correct(store)
    case2 = demo_case2_wrong_driver(store)
    case3 = demo_case3_wrong_recommendation(store)
    case4 = demo_case4_wrong_confidence(store)
    case5 = demo_case5_missing_driver(store)
    dataset_eval = demo_dataset_level_evaluation(store)

    run_seconds = round(time.time() - t_start, 2)

    all_feedback = store.list_feedback()
    all_corrections = store.list_corrections()
    all_contexts = store.list_business_context()
    all_cases = store.list_evaluation_cases()
    all_tests = store.list_regression_tests()

    value_checks = {
        "five_feedback_cases_submitted": len(all_feedback) == 5,
        "corrections_stored_for_4_non_correct_cases": len(all_corrections) == 4,
        "business_context_captured": len(all_contexts) >= 3,
        "evaluation_cases_created_for_4_corrections": len(all_cases) == 4,
        "regression_tests_created_for_4_cases": len(all_tests) == 4,
        "case2_regression_catches_causal_language_regression": (
            case2["regression_bad_report"]["failed"] == 1
        ),
        "dataset_level_regression_detected": "causal_correctness" in dataset_eval["comparison"]["regressions"],
        "no_case_evaluation_metrics_fabricated": all(
            isinstance(v, float) for v in dataset_eval["baseline"]["metrics"].values()
        ),
    }
    value_checks["all_checks_pass"] = all(value_checks.values())

    test_results = run_tests()

    report = {
        "generated_at": _now(),
        "run_seconds": run_seconds,
        "required_value_checks": value_checks,
        "feedback_summary": {
            "total_feedback": len(all_feedback),
            "total_corrections": len(all_corrections),
            "total_business_contexts": len(all_contexts),
            "total_evaluation_cases": len(all_cases),
            "total_regression_tests": len(all_tests),
        },
        "cases": {"case1_correct": case1, "case2_wrong_driver": case2, "case3_wrong_recommendation": case3,
                   "case4_wrong_confidence": case4, "case5_missing_driver": case5},
        "dataset_level_evaluation": dataset_eval,
        "tests": test_results,
    }

    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "step9_validation.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))

    _section("SUMMARY")
    print(f"Step 9 demo complete in {run_seconds}s. Report written to {report_path}\n")
    for key, value in value_checks.items():
        print(f"  [{'OK' if value else 'FAIL'}] {key}")
    print(f"\nRequired value checks all pass: {value_checks['all_checks_pass']}")
    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed "
          f"(all_passed={test_results['all_passed']})")

    if not value_checks["all_checks_pass"] or not test_results["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
