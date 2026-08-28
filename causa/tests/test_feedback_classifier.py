"""Step 9: classifier.py tests -- deterministic multi-category
classification, works without an LLM, LLM path validates output and falls
back on LLMUnavailable/malformed output."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.classifier import classify_feedback  # noqa: E402
from feedback.models import FeedbackCategory, FeedbackRating, GeneratedBy, OutputType  # noqa: E402


def _fb(rating, comment=None):
    return submit_feedback(rating, OutputType.STORY_CLAIM, session_id="sess1", comment=comment)


def test_works_without_llm():
    fb = _fb(FeedbackRating.INCORRECT, "The delivery driver is incorrect. November had a holiday campaign.")
    categories, generated_by = classify_feedback(fb)
    assert generated_by == GeneratedBy.DETERMINISTIC_RULES
    assert FeedbackCategory.DRIVER in categories
    assert FeedbackCategory.NARRATIVE in categories


def test_kpi_definition_and_data_multi_category():
    fb = _fb(FeedbackRating.INCORRECT, "The KPI definition is wrong because refunded orders should be excluded.")
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.KPI_DEFINITION in categories
    assert FeedbackCategory.DATA in categories


def test_missing_driver_rating_implies_driver_category():
    fb = _fb(FeedbackRating.MISSING_DRIVER, "Pricing change was another important driver.")
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.DRIVER in categories


def test_wrong_recommendation_rating_implies_recommendation_category():
    fb = _fb(FeedbackRating.WRONG_RECOMMENDATION, "Carrier capacity is exhausted.")
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.RECOMMENDATION in categories


def test_wrong_confidence_rating_implies_confidence_category():
    fb = _fb(FeedbackRating.WRONG_CONFIDENCE, "Evidence is weak; confidence should be lower.")
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.CONFIDENCE in categories


def test_no_comment_no_rating_default_returns_empty():
    fb = _fb(FeedbackRating.CORRECT)
    categories, generated_by = classify_feedback(fb)
    assert categories == []
    assert generated_by == GeneratedBy.DETERMINISTIC_RULES


def test_evidence_keyword_classified():
    fb = _fb(FeedbackRating.INCORRECT, "The evidence interpretation here is wrong.")
    categories, _ = classify_feedback(fb)
    assert FeedbackCategory.EVIDENCE in categories


class _FakeLLMResponse:
    def __init__(self, text):
        self.content = [{"type": "text", "text": text}]


class _FakeLLMClient:
    def __init__(self, response_text):
        self._response_text = response_text

    def create(self, system, messages, tools, max_tokens):
        return _FakeLLMResponse(self._response_text)

    def build_user_message(self, text):
        return {"role": "user", "content": text}


def test_llm_valid_output_merged_and_validated():
    fake = _FakeLLMClient('["RECOMMENDATION", "NARRATIVE"]')
    fb = _fb(FeedbackRating.INCORRECT, "Some free text comment about the story.")
    categories, generated_by = classify_feedback(fb, llm_client=fake)
    assert generated_by == GeneratedBy.LLM_CLASSIFIED_VALIDATED
    assert FeedbackCategory.RECOMMENDATION in categories
    assert FeedbackCategory.NARRATIVE in categories


def test_llm_malformed_output_falls_back_to_deterministic():
    fake = _FakeLLMClient("not json at all")
    fb = _fb(FeedbackRating.MISSING_DRIVER, "Pricing change was another important driver.")
    categories, generated_by = classify_feedback(fb, llm_client=fake)
    assert generated_by == GeneratedBy.DETERMINISTIC_RULES
    assert FeedbackCategory.DRIVER in categories


def test_llm_invalid_category_falls_back_to_deterministic():
    fake = _FakeLLMClient('["NOT_A_REAL_CATEGORY"]')
    fb = _fb(FeedbackRating.MISSING_DRIVER, "Pricing change was another important driver.")
    categories, generated_by = classify_feedback(fb, llm_client=fake)
    assert generated_by == GeneratedBy.DETERMINISTIC_RULES
    assert FeedbackCategory.DRIVER in categories


def test_llm_unavailable_falls_back_to_deterministic():
    from agents.llm_client import LLMUnavailable

    class _RaisingClient:
        def create(self, *args, **kwargs):
            raise LLMUnavailable("no credentials")

        def build_user_message(self, text):
            return {"role": "user", "content": text}

    fb = _fb(FeedbackRating.MISSING_DRIVER, "Pricing change was another important driver.")
    categories, generated_by = classify_feedback(fb, llm_client=_RaisingClient())
    assert generated_by == GeneratedBy.DETERMINISTIC_RULES
    assert FeedbackCategory.DRIVER in categories
