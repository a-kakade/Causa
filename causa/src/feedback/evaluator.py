"""
evaluator.py — Step 9: the Offline Evaluation Engine (spec sections 15-19).

run_offline_evaluation() takes an EvaluationCase dataset plus a
candidate_runner callable and produces a computed, non-fabricated
EvaluationReport (spec section 16: "Do not fabricate metrics. Metrics must
be calculated from actual evaluation cases."). This module NEVER imports
story/decision pipeline modules at call time for its own sake -- the caller
supplies candidate_runner, exactly the "loosely coupled to Steps 1-8"
requirement (spec section 1.5): Step 9 can evaluate a Step 8 KPIStory
generator, a Step 7 decision pipeline, or a hand-built stub in a test, all
through the same interface.

candidate_runner contract: a callable taking one EvaluationCase and
returning a CandidateOutput (or any object/dict exposing the same
attributes -- see _coerce_output below). This keeps the interface a plain
data contract, not a class candidate implementations must inherit from.

Claim-level checks REUSE story.claim_verifier.verify_claim and
story.language_rules / story.numeric_verifier directly -- this module
computes zero new "is this claim causally sound" logic of its own. Where a
candidate's claims are supplied as raw NarrativeClaim/EvidencePackage
objects (the common case when candidate_runner wraps
story.engine.generate_kpi_story), the real Step 8 verifier runs unmodified;
where only claim text strings are supplied (e.g. a regression test built
purely from forbidden_claims substrings), this module falls back to the
same causal-language blacklist gate (agents.models.
contains_unsupported_causal_language) Step 8's own language_rules.py is
built on -- never a second, parallel regex.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from agents.models import contains_unsupported_causal_language
from feedback.models import EvaluationCase
from story.claim_verifier import verify_claim
from story.models import EvidencePackage, NarrativeClaim, ValidationStatus


@dataclass
class CandidateOutput:
    """What a candidate_runner returns for one EvaluationCase. Every field
    is optional -- an EvaluationCase created for a RECOMMENDATION-only
    correction need not populate claims, and vice versa. is_estimable-style
    honesty: a candidate that cannot produce a field leaves it None/empty
    rather than this module guessing."""
    claim_texts: list[str] = field(default_factory=list)
    claims: list[NarrativeClaim] = field(default_factory=list)  # verified via claim_verifier when evidence_package is present
    evidence_package: Optional[EvidencePackage] = None
    recommendation: Optional[dict[str, Any]] = None  # {"tier": "...", "driver": "...", "recommendation_id": "..."}
    confidence: Optional[float] = None
    driver: Optional[str] = None


def _coerce_output(raw: Any) -> CandidateOutput:
    if isinstance(raw, CandidateOutput):
        return raw
    if isinstance(raw, dict):
        return CandidateOutput(
            claim_texts=list(raw.get("claim_texts", [])), claims=list(raw.get("claims", [])),
            evidence_package=raw.get("evidence_package"), recommendation=raw.get("recommendation"),
            confidence=raw.get("confidence"), driver=raw.get("driver"),
        )
    # Duck-typed object exposing the same attributes.
    return CandidateOutput(
        claim_texts=list(getattr(raw, "claim_texts", [])), claims=list(getattr(raw, "claims", [])),
        evidence_package=getattr(raw, "evidence_package", None), recommendation=getattr(raw, "recommendation", None),
        confidence=getattr(raw, "confidence", None), driver=getattr(raw, "driver", None),
    )


@dataclass
class CaseResult:
    case_id: str
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    claims_checked: int = 0
    claims_rejected: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, "passed": self.passed,
                "failure_reasons": list(self.failure_reasons), "checks": dict(self.checks)}


def _all_claim_texts(output: CandidateOutput) -> list[str]:
    texts = list(output.claim_texts)
    texts.extend(c.text for c in output.claims)
    return texts


def evaluate_case(case: EvaluationCase, candidate_runner: Callable[[EvaluationCase], Any]) -> CaseResult:
    """Runs one EvaluationCase against candidate_runner and checks every
    dimension the case declares expectations for. A dimension the case
    doesn't constrain (e.g. no expected_recommendation) is skipped, not
    scored as a pass -- only real checks count (spec section 16)."""
    output = _coerce_output(candidate_runner(case))
    reasons: list[str] = []
    checks: dict[str, bool] = {}

    all_texts = _all_claim_texts(output)

    # -- forbidden claims: no produced claim text may contain a forbidden phrase,
    #    and (spec section 13) causal language is specifically disallowed when a
    #    forbidden_claims list exists for this case, mirroring language_rules.py's
    #    own blacklist-not-whitelist posture.
    if case.forbidden_claims:
        forbidden_hit = False
        for forbidden in case.forbidden_claims:
            forbidden_lower = forbidden.lower()
            for text in all_texts:
                if forbidden_lower in text.lower() or contains_unsupported_causal_language(text):
                    forbidden_hit = True
                    reasons.append(f"forbidden claim pattern matched: {forbidden!r} in produced text {text!r}")
        checks["forbidden_claims"] = not forbidden_hit

    # -- expected claims: at least a substring match must appear somewhere in output.
    if case.expected_claims:
        missing = [exp for exp in case.expected_claims if not any(exp.lower() in t.lower() for t in all_texts)]
        checks["expected_claims"] = not missing
        if missing:
            reasons.append(f"expected claim(s) not found in candidate output: {missing}")

    # -- claim-level verification, reusing story.claim_verifier unmodified.
    if output.claims and output.evidence_package is not None:
        rejected = []
        for claim in output.claims:
            verify_claim(claim, output.evidence_package, tolerance=0.0005, absolute_floor=0.01)
            if claim.validation_status == ValidationStatus.REJECTED:
                rejected.append({"text": claim.text, "reason": claim.rejection_reason})
        checks["claim_verification"] = not rejected
        if rejected:
            reasons.append(f"claim_verifier rejected {len(rejected)} claim(s): {rejected}")

    # -- recommendation correctness.
    if case.expected_recommendation is not None:
        rec = output.recommendation or {}
        rec_ok = all(rec.get(k) == v for k, v in case.expected_recommendation.items())
        checks["recommendation"] = rec_ok
        if not rec_ok:
            reasons.append(f"recommendation {rec!r} did not match expected {case.expected_recommendation!r}")

    # -- driver correctness.
    if case.expected_driver is not None:
        driver_ok = output.driver == case.expected_driver
        checks["driver"] = driver_ok
        if not driver_ok:
            reasons.append(f"driver {output.driver!r} did not match expected {case.expected_driver!r}")

    # -- confidence correctness.
    if case.expected_confidence_range is not None:
        lo, hi = case.expected_confidence_range
        conf_ok = output.confidence is not None and lo <= output.confidence <= hi
        checks["confidence"] = conf_ok
        if not conf_ok:
            reasons.append(f"confidence {output.confidence!r} not within expected range [{lo}, {hi}]")

    claims_checked = len(output.claims) if (output.claims and output.evidence_package is not None) else 0
    claims_rejected = len(rejected) if (output.claims and output.evidence_package is not None) else 0

    passed = not reasons
    return CaseResult(case_id=case.case_id, passed=passed, failure_reasons=reasons, checks=checks,
                       claims_checked=claims_checked, claims_rejected=claims_rejected)


@dataclass
class EvaluationReport:
    dataset_version: str
    total_cases: int
    passed: int
    failed: int
    metrics: dict[str, float] = field(default_factory=dict)
    case_results: list[CaseResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_version": self.dataset_version, "total_cases": self.total_cases,
            "passed": self.passed, "failed": self.failed, "metrics": dict(self.metrics),
            "case_results": [r.to_dict() for r in self.case_results],
        }


def _rate(checks: list[CaseResult], key: str) -> Optional[float]:
    relevant = [r for r in checks if key in r.checks]
    if not relevant:
        return None
    return sum(1 for r in relevant if r.checks[key]) / len(relevant)


def run_offline_evaluation(
    dataset: list[EvaluationCase], candidate_runner: Callable[[EvaluationCase], Any],
    dataset_version: Optional[str] = None,
) -> EvaluationReport:
    """Evaluates every case in `dataset` against candidate_runner. Every
    metric below is computed only from cases that actually declared an
    expectation for that dimension -- never fabricated for cases that
    didn't (spec section 16). unsupported_claim_rate is the fraction of
    ALL produced claims (across every case using claim-level verification)
    that verify_claim rejected."""
    results = [evaluate_case(case, candidate_runner) for case in dataset]
    passed = sum(1 for r in results if r.passed)

    # Reuses the counts evaluate_case already computed while it ran
    # verify_claim -- never re-invokes candidate_runner a second time, which
    # would risk double-counting or seeing a different (freshly constructed)
    # set of claim objects than what was actually verified.
    total_claims_checked = sum(r.claims_checked for r in results)
    total_claims_rejected = sum(r.claims_rejected for r in results)

    metrics: dict[str, float] = {}
    for key, metric_name in (
        ("expected_claims", "numeric_accuracy"),
        ("claim_verification", "evidence_grounding"),
        ("forbidden_claims", "causal_correctness"),
        ("driver", "driver_accuracy"),
        ("recommendation", "recommendation_accuracy"),
        ("confidence", "confidence_accuracy"),
    ):
        rate = _rate(results, key)
        if rate is not None:
            metrics[metric_name] = rate

    if total_claims_checked > 0:
        metrics["unsupported_claim_rate"] = total_claims_rejected / total_claims_checked

    version = dataset_version or (dataset[0].dataset_version if dataset else "v0")
    return EvaluationReport(
        dataset_version=version, total_cases=len(dataset), passed=passed, failed=len(dataset) - passed,
        metrics=metrics, case_results=results,
    )


@dataclass
class ComparisonReport:
    baseline_version: str
    candidate_version: str
    baseline_metrics: dict[str, float]
    candidate_metrics: dict[str, float]
    deltas: dict[str, float]
    regressions: list[str]
    improvements: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_version": self.baseline_version, "candidate_version": self.candidate_version,
            "baseline_metrics": dict(self.baseline_metrics), "candidate_metrics": dict(self.candidate_metrics),
            "deltas": dict(self.deltas), "regressions": list(self.regressions), "improvements": list(self.improvements),
        }


# Metrics where a LOWER value is better -- everything else, higher is better.
_LOWER_IS_BETTER = {"unsupported_claim_rate"}


def compare_baseline_candidate(baseline: EvaluationReport, candidate: EvaluationReport) -> ComparisonReport:
    """Pure comparison -- never deploys, never chooses a winner. Spec
    section 19: "Compare metrics. Deploy only if improved" is a HUMAN
    decision this report informs, not one this function makes."""
    deltas: dict[str, float] = {}
    regressions: list[str] = []
    improvements: list[str] = []

    all_keys = set(baseline.metrics) | set(candidate.metrics)
    for key in sorted(all_keys):
        base_val = baseline.metrics.get(key)
        cand_val = candidate.metrics.get(key)
        if base_val is None or cand_val is None:
            continue
        delta = cand_val - base_val
        deltas[key] = delta
        better_direction = -1 if key in _LOWER_IS_BETTER else 1
        if delta * better_direction < 0:
            regressions.append(key)
        elif delta * better_direction > 0:
            improvements.append(key)

    return ComparisonReport(
        baseline_version=baseline.dataset_version, candidate_version=candidate.dataset_version,
        baseline_metrics=dict(baseline.metrics), candidate_metrics=dict(candidate.metrics),
        deltas=deltas, regressions=regressions, improvements=improvements,
    )
