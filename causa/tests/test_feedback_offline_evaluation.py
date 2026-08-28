"""Step 9: evaluator.py tests -- metrics calculated correctly, baseline vs
candidate comparison works, regressions identified. Reuses
story.claim_verifier under the hood (no LLM required anywhere)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.evaluator import (  # noqa: E402
    CandidateOutput,
    compare_baseline_candidate,
    evaluate_case,
    run_offline_evaluation,
)
from feedback.models import EvaluationCase  # noqa: E402
from story.models import ClaimType, EvidenceItem, EvidencePackage, NarrativeClaim  # noqa: E402


def _case(case_id="EC1", **kwargs):
    return EvaluationCase(case_id=case_id, dataset_version="v1", source_feedback_id="FB1", created_at="t", **kwargs)


def _item(evidence_id, metric, value, unit, claim_type):
    return EvidenceItem(
        evidence_id=evidence_id, metric=metric, value=value, unit=unit, direction="decrease", period="2017-11",
        source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00", analytical_method="x",
        confidence="HIGH", claim_type=claim_type,
    )


def test_forbidden_claim_detected_as_failure():
    case = _case(forbidden_claims=["delivery caused review decline"])

    def bad_runner(c):
        return CandidateOutput(claim_texts=["Delivery deterioration caused review decline this month."])

    result = evaluate_case(case, bad_runner)
    assert result.passed is False
    assert result.checks["forbidden_claims"] is False


def test_association_language_passes_forbidden_claim_check():
    case = _case(forbidden_claims=["delivery caused review decline"])

    def good_runner(c):
        return CandidateOutput(claim_texts=["Delivery deterioration coincided with lower reviews."])

    result = evaluate_case(case, good_runner)
    assert result.passed is True
    assert result.checks["forbidden_claims"] is True


def test_expected_claims_missing_detected():
    case = _case(expected_claims=["holiday campaign"])

    def runner(c):
        return CandidateOutput(claim_texts=["Something unrelated."])

    result = evaluate_case(case, runner)
    assert result.passed is False
    assert result.checks["expected_claims"] is False


def test_claim_verifier_reuse_rejects_bad_claim():
    package = EvidencePackage(package_id="pkg1", kpi_id="reviews", period="2017-11", items=[
        _item("EV006", "on_time_delivery_rate", 27.9, "percent", ClaimType.ASSOCIATION),
    ])
    case = _case()

    def runner(c):
        claim = NarrativeClaim(text="Delivery deterioration coincided with lower reviews.",
                                claim_type=ClaimType.ASSOCIATION, evidence_ids=["EV006"])
        return CandidateOutput(claims=[claim], evidence_package=package)

    result = evaluate_case(case, runner)
    assert result.checks["claim_verification"] is True


def test_claim_verifier_reuse_rejects_fact_from_association_evidence():
    package = EvidencePackage(package_id="pkg1", kpi_id="reviews", period="2017-11", items=[
        _item("EV006", "on_time_delivery_rate", 27.9, "percent", ClaimType.ASSOCIATION),
    ])
    case = _case()

    def bad_runner(c):
        claim = NarrativeClaim(text="Delivery deterioration was 27.9%.", claim_type=ClaimType.FACT,
                                evidence_ids=["EV006"])
        return CandidateOutput(claims=[claim], evidence_package=package)

    result = evaluate_case(bad_runner and case, bad_runner)
    assert result.checks["claim_verification"] is False
    assert result.passed is False


def test_recommendation_correctness_check():
    case = _case(expected_recommendation={"tier": "BLOCKED"})

    def runner(c):
        return CandidateOutput(recommendation={"tier": "BLOCKED", "recommendation_id": "rec_x"})

    result = evaluate_case(case, runner)
    assert result.checks["recommendation"] is True


def test_recommendation_incorrectness_detected():
    case = _case(expected_recommendation={"tier": "BLOCKED"})

    def runner(c):
        return CandidateOutput(recommendation={"tier": "TOP"})

    result = evaluate_case(case, runner)
    assert result.checks["recommendation"] is False


def test_confidence_range_check():
    case = _case(expected_confidence_range=(0.0, 0.5))

    def runner(c):
        return CandidateOutput(confidence=0.92)

    result = evaluate_case(case, runner)
    assert result.checks["confidence"] is False


def test_metrics_not_fabricated_only_from_declared_expectations():
    case = _case()  # no expectations declared at all

    def runner(c):
        return CandidateOutput(claim_texts=["anything"])

    report = run_offline_evaluation([case], runner)
    assert report.metrics == {}
    assert report.total_cases == 1
    assert report.passed == 1  # no checks failed because none were run


def test_metrics_computed_from_real_cases():
    good_case = _case(case_id="EC1", forbidden_claims=["x caused y"])
    bad_case = _case(case_id="EC2", forbidden_claims=["x caused y"])

    def runner(c):
        if c.case_id == "EC1":
            return CandidateOutput(claim_texts=["x was associated with y"])
        return CandidateOutput(claim_texts=["x caused y"])

    report = run_offline_evaluation([good_case, bad_case], runner)
    assert report.total_cases == 2
    assert report.passed == 1
    assert report.failed == 1
    assert report.metrics["causal_correctness"] == 0.5


def test_baseline_vs_candidate_comparison_detects_regression():
    case = _case(forbidden_claims=["x caused y"])

    def baseline_runner(c):
        return CandidateOutput(claim_texts=["x was associated with y"])

    def candidate_runner(c):
        return CandidateOutput(claim_texts=["x caused y"])

    baseline_report = run_offline_evaluation([case], baseline_runner, dataset_version="baseline")
    candidate_report = run_offline_evaluation([case], candidate_runner, dataset_version="candidate")

    comparison = compare_baseline_candidate(baseline_report, candidate_report)
    assert "causal_correctness" in comparison.regressions
    assert comparison.deltas["causal_correctness"] < 0


def test_baseline_vs_candidate_comparison_detects_improvement():
    case = _case(forbidden_claims=["x caused y"])

    def baseline_runner(c):
        return CandidateOutput(claim_texts=["x caused y"])

    def candidate_runner(c):
        return CandidateOutput(claim_texts=["x was associated with y"])

    baseline_report = run_offline_evaluation([case], baseline_runner, dataset_version="baseline")
    candidate_report = run_offline_evaluation([case], candidate_runner, dataset_version="candidate")

    comparison = compare_baseline_candidate(baseline_report, candidate_report)
    assert "causal_correctness" in comparison.improvements
    assert comparison.regressions == []


def test_unsupported_claim_rate_lower_is_better():
    """A lower unsupported_claim_rate in the candidate must register as an
    improvement, not a regression -- this metric's direction is inverted
    relative to the others."""
    package = EvidencePackage(package_id="pkg1", kpi_id="reviews", period="2017-11", items=[
        _item("EV006", "on_time_delivery_rate", 27.9, "percent", ClaimType.ASSOCIATION),
    ])
    case = _case()

    def baseline_runner(c):
        bad_claim = NarrativeClaim(text="Delivery deterioration was 27.9%.", claim_type=ClaimType.FACT,
                                    evidence_ids=["EV006"])
        return CandidateOutput(claims=[bad_claim], evidence_package=package)

    def candidate_runner(c):
        good_claim = NarrativeClaim(text="Delivery deterioration coincided with lower reviews.",
                                     claim_type=ClaimType.ASSOCIATION, evidence_ids=["EV006"])
        return CandidateOutput(claims=[good_claim], evidence_package=package)

    baseline_report = run_offline_evaluation([case], baseline_runner, dataset_version="baseline")
    candidate_report = run_offline_evaluation([case], candidate_runner, dataset_version="candidate")
    assert baseline_report.metrics["unsupported_claim_rate"] == 1.0
    assert candidate_report.metrics["unsupported_claim_rate"] == 0.0

    comparison = compare_baseline_candidate(baseline_report, candidate_report)
    assert "unsupported_claim_rate" in comparison.improvements
    assert "unsupported_claim_rate" not in comparison.regressions
