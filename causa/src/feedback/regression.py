"""
regression.py — Step 9: promoting approved EvaluationCases into runnable
regression tests (spec section 17).

promote_to_regression_test() only accepts an EvaluationCase whose status is
ReviewStatus.APPROVED_FOR_EVALUATION (set by evaluation_case.
approve_evaluation_case(), itself only reachable after the source Feedback
was separately approved) -- "Do not automatically add every piece of
feedback blindly."

run_regression_tests() is a thin harness: it takes a caller-supplied
candidate_runner callable (so this module never imports story/decision
directly, keeping Step 9 loosely coupled to Steps 7/8 per the task's own
requirement) and re-uses evaluator.py's per-case check logic so "does this
regression test pass" and "what does an offline evaluation run measure" are
one code path, not two competing implementations.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from datetime import timezone
from typing import Any, Callable

from feedback.evaluator import evaluate_case
from feedback.models import EvaluationCase, RegressionTest, ReviewStatus
from feedback.store import FeedbackStore


class RegressionError(Exception):
    """Raised when promote_to_regression_test() is called against an
    EvaluationCase that has not been APPROVED_FOR_EVALUATION."""


def _now() -> str:
    return datetime.datetime.now(timezone.utc).isoformat()


def _assertion_summary(case: EvaluationCase) -> str:
    parts = []
    if case.forbidden_claims:
        parts.append(f"forbids: {case.forbidden_claims}")
    if case.expected_claims:
        parts.append(f"expects: {case.expected_claims}")
    if case.expected_recommendation:
        parts.append(f"expected_recommendation: {case.expected_recommendation}")
    if case.expected_confidence_range:
        parts.append(f"expected_confidence_range: {case.expected_confidence_range}")
    return "; ".join(parts) if parts else f"evaluation case {case.case_id} regression check"


def promote_to_regression_test(case_id: str, store: FeedbackStore, test_id: str | None = None) -> RegressionTest:
    case = next((c for c in store.list_evaluation_cases() if c.case_id == case_id), None)
    if case is None:
        raise RegressionError(f"no evaluation case found with id {case_id!r}")
    if case.status != ReviewStatus.APPROVED_FOR_EVALUATION:
        raise RegressionError(
            f"evaluation case {case_id!r} has status={case.status.value}; only "
            f"APPROVED_FOR_EVALUATION cases may be promoted to a regression test"
        )
    test = RegressionTest(
        test_id=test_id or f"REGTEST_{case_id}", source_evaluation_case_id=case_id,
        assertion_summary=_assertion_summary(case), created_at=_now(),
    )
    return store.save_regression_test(test)


@dataclass
class RegressionResult:
    test_id: str
    case_id: str
    passed: bool
    failure_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"test_id": self.test_id, "case_id": self.case_id, "passed": self.passed,
                "failure_reasons": list(self.failure_reasons)}


@dataclass
class RegressionReport:
    total: int
    passed: int
    failed: int
    results: list[RegressionResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"total": self.total, "passed": self.passed, "failed": self.failed,
                "results": [r.to_dict() for r in self.results]}


def run_regression_tests(
    tests: list[RegressionTest], store: FeedbackStore, candidate_runner: Callable[[EvaluationCase], Any],
) -> RegressionReport:
    """Runs each RegressionTest's underlying EvaluationCase through
    candidate_runner (a caller-supplied callable that produces whatever the
    candidate Step 7/8 pipeline would output for that case's input_context)
    and reports pass/fail via evaluator.evaluate_case -- the exact same
    per-case check function offline evaluation uses, so a regression
    failure and an evaluation-metric failure can never silently disagree."""
    cases_by_id = {c.case_id: c for c in store.list_evaluation_cases()}
    results: list[RegressionResult] = []
    for test in tests:
        case = cases_by_id.get(test.source_evaluation_case_id)
        if case is None:
            results.append(RegressionResult(test.test_id, test.source_evaluation_case_id, False,
                                              [f"source evaluation case {test.source_evaluation_case_id!r} not found"]))
            continue
        case_result = evaluate_case(case, candidate_runner)
        results.append(RegressionResult(test.test_id, case.case_id, case_result.passed, case_result.failure_reasons))

    passed = sum(1 for r in results if r.passed)
    return RegressionReport(total=len(results), passed=passed, failed=len(results) - passed, results=results)
