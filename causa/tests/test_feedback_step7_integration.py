"""Step 9: integration with Step 7 recommendations (spec section 25) --
RECOMMENDATION feedback creates an evaluation case testing constraint-aware
behavior, never modifying decision.constraint_engine.py/ranking.py/ontology
config directly."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.constraint_engine import evaluate_constraints  # noqa: E402
from decision.models import ConstraintStatus, overall_constraint_status  # noqa: E402
from decision.ontology import DecisionScoringConfig  # noqa: E402
from feedback.capture import submit_feedback  # noqa: E402
from feedback.evaluation_case import create_evaluation_case  # noqa: E402
from feedback.evaluator import CandidateOutput, evaluate_case  # noqa: E402
from feedback.models import FeedbackRating, OutputType, ReviewStatus  # noqa: E402
from feedback.regression import promote_to_regression_test  # noqa: E402
from feedback.review import review_feedback  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402


def _store():
    return FeedbackStore(Path(tempfile.mkdtemp()))


def test_wrong_recommendation_feedback_creates_recommendation_evaluation_case():
    store = _store()
    fb = submit_feedback(
        FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="s1",
        comment="Carrier capacity is currently exhausted.",
        affected_recommendation_id="rec_delivery_delay_expedite_high_risk_shipments",
    )
    store.save_feedback(fb)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)

    case = create_evaluation_case(
        current, None, None, store,
        input_context={"business_context": {"operational_capacity_available": False}, "owner": "ops_team"},
        expected_recommendation={"tier": "BLOCKED"},
        expected_behavior={"must_not_rank_as_executable": True},
    )
    assert case.expected_recommendation == {"tier": "BLOCKED"}
    assert case.input_context["business_context"]["operational_capacity_available"] is False


def test_evaluation_case_input_context_drives_real_constraint_engine():
    """The case's input_context is structurally compatible with Step 7's own
    constraint_engine.evaluate_constraints -- a candidate_runner can feed it
    straight through without reshaping."""
    store = _store()
    fb = submit_feedback(FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="s1",
                          affected_recommendation_id="rec_x")
    store.save_feedback(fb)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)

    case = create_evaluation_case(
        current, None, None, store,
        input_context={"business_context": {"operational_capacity_available": False}, "owner": "ops_team"},
        expected_recommendation={"tier": "BLOCKED"},
    )

    scoring_config = DecisionScoringConfig.load()
    checks = evaluate_constraints(["operational_capacity"], case.input_context["business_context"],
                                   case.input_context["owner"], scoring_config)
    assert overall_constraint_status(checks) == ConstraintStatus.BLOCKED


def test_regression_test_catches_recommendation_ignoring_constraint():
    store = _store()
    fb = submit_feedback(FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="s1",
                          affected_recommendation_id="rec_x")
    store.save_feedback(fb)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    case = create_evaluation_case(current, None, None, store, expected_recommendation={"tier": "BLOCKED"})

    from feedback.evaluation_case import approve_evaluation_case
    approve_evaluation_case(case.case_id, reviewer="a", store=store)
    test = promote_to_regression_test(case.case_id, store)

    def wrongly_still_top(c):
        return CandidateOutput(recommendation={"tier": "TOP"})

    from feedback.regression import run_regression_tests
    report = run_regression_tests([test], store, wrongly_still_top)
    assert report.failed == 1

    def correctly_blocked(c):
        return CandidateOutput(recommendation={"tier": "BLOCKED"})

    report2 = run_regression_tests([test], store, correctly_blocked)
    assert report2.passed == 1
