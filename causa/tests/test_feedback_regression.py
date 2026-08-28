"""Step 9: regression.py tests -- approved evaluation cases become runnable
regression tests, regression failure is detectable, unapproved cases
cannot be promoted."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.evaluation_case import approve_evaluation_case, create_evaluation_case  # noqa: E402
from feedback.evaluator import CandidateOutput  # noqa: E402
from feedback.models import FeedbackRating, OutputType, ReviewStatus  # noqa: E402
from feedback.regression import RegressionError, promote_to_regression_test, run_regression_tests  # noqa: E402
from feedback.review import review_feedback  # noqa: E402
from feedback.store import FeedbackStore  # noqa: E402


def _store():
    return FeedbackStore(Path(tempfile.mkdtemp()))


def _approved_case(store, forbidden_claims=None):
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1", comment="wrong driver")
    store.save_feedback(fb)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    case = create_evaluation_case(current, None, None, store, forbidden_claims=forbidden_claims or [])
    return approve_evaluation_case(case.case_id, reviewer="a", store=store)


def test_pending_case_cannot_be_promoted():
    store = _store()
    fb = submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1")
    store.save_feedback(fb)
    review_feedback(fb.feedback_id, ReviewStatus.REVIEWED, reviewer="a", store=store)
    review_feedback(fb.feedback_id, ReviewStatus.APPROVED_FOR_EVALUATION, reviewer="a", store=store)
    current = store.get_feedback(fb.feedback_id)
    case = create_evaluation_case(current, None, None, store)  # not approved as a case

    try:
        promote_to_regression_test(case.case_id, store)
        assert False, "expected RegressionError"
    except RegressionError:
        pass


def test_approved_case_promotes_to_regression_test():
    store = _store()
    case = _approved_case(store, forbidden_claims=["delivery caused review decline"])
    test = promote_to_regression_test(case.case_id, store)
    assert test.source_evaluation_case_id == case.case_id
    stored_tests = store.list_regression_tests()
    assert any(t.test_id == test.test_id for t in stored_tests)


def test_regression_pass_when_candidate_avoids_forbidden_claim():
    store = _store()
    case = _approved_case(store, forbidden_claims=["delivery caused review decline"])
    test = promote_to_regression_test(case.case_id, store)

    def good_runner(c):
        return CandidateOutput(claim_texts=["Delivery deterioration coincided with lower reviews."])

    report = run_regression_tests([test], store, good_runner)
    assert report.passed == 1
    assert report.failed == 0


def test_regression_fail_when_candidate_repeats_forbidden_claim():
    store = _store()
    case = _approved_case(store, forbidden_claims=["delivery caused review decline"])
    test = promote_to_regression_test(case.case_id, store)

    def bad_runner(c):
        return CandidateOutput(claim_texts=["Delivery caused review decline this month."])

    report = run_regression_tests([test], store, bad_runner)
    assert report.passed == 0
    assert report.failed == 1
    assert report.results[0].failure_reasons
