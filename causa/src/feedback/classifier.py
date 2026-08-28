"""
classifier.py — Step 9: deterministic Feedback Classification layer.

classify_feedback() maps a Feedback (rating + optional free-text comment)
onto one or more FeedbackCategory values (spec section 5: "A single piece of
feedback may contain multiple categories"). Deterministic rules are the
default and only required path -- keyword rules over the comment text plus a
rating -> category default mapping. An LLM classifier is optional (mirrors
story/generator.py's llm_client=None -> deterministic-fallback posture
exactly): if supplied, its output is validated against the FeedbackCategory
enum before being trusted at all, and any LLMUnavailable/malformed-output
case silently falls back to the deterministic result. classify_feedback()
NEVER modifies analytical truth -- it only returns a list[FeedbackCategory],
which capture.py / evaluation_case.py may then attach to a Feedback record.
"""

from __future__ import annotations

from typing import Any, Optional

from feedback.models import Feedback, FeedbackCategory, FeedbackRating, GeneratedBy

# Rating -> default category set. A rating alone is often enough to imply a
# category even with no comment at all (spec section 5's examples always
# pair a category with either a structured selection or free text; the
# rating itself is the most structured signal available).
_RATING_DEFAULTS: dict[FeedbackRating, tuple[FeedbackCategory, ...]] = {
    FeedbackRating.MISSING_DRIVER: (FeedbackCategory.DRIVER,),
    FeedbackRating.WRONG_RECOMMENDATION: (FeedbackCategory.RECOMMENDATION,),
    FeedbackRating.WRONG_CONFIDENCE: (FeedbackCategory.CONFIDENCE,),
}

# Keyword -> category rules applied to lowercased comment text. Deliberately
# simple substring matching (same "deterministic, no LLM required" posture
# as story/persona.py's select_and_order()) -- a comment can trigger more
# than one rule, which is exactly how multi-category feedback (spec section
# 5's two worked examples) arises without any LLM involvement.
_KEYWORD_RULES: tuple[tuple[str, FeedbackCategory], ...] = (
    ("kpi definition", FeedbackCategory.KPI_DEFINITION),
    ("excluded", FeedbackCategory.DATA),
    ("refunded", FeedbackCategory.DATA),
    ("data quality", FeedbackCategory.DATA),
    ("driver", FeedbackCategory.DRIVER),
    ("caused", FeedbackCategory.NARRATIVE),
    ("evidence", FeedbackCategory.EVIDENCE),
    ("confidence", FeedbackCategory.CONFIDENCE),
    ("recommend", FeedbackCategory.RECOMMENDATION),
    ("capacity", FeedbackCategory.RECOMMENDATION),
    ("campaign", FeedbackCategory.NARRATIVE),
    ("holiday", FeedbackCategory.NARRATIVE),
    ("wording", FeedbackCategory.NARRATIVE),
    ("narrative", FeedbackCategory.NARRATIVE),
)


def _deterministic_classify(feedback: Feedback, comment: Optional[str]) -> list[FeedbackCategory]:
    found: list[FeedbackCategory] = []

    for category in _RATING_DEFAULTS.get(feedback.rating, ()):
        if category not in found:
            found.append(category)

    text = (comment or feedback.comment or "").lower()
    for keyword, category in _KEYWORD_RULES:
        if keyword in text and category not in found:
            found.append(category)

    return found


def classify_feedback(
    feedback: Feedback, comment: Optional[str] = None, llm_client: Optional[Any] = None
) -> tuple[list[FeedbackCategory], GeneratedBy]:
    """Returns (categories, generated_by). Deterministic path always runs
    first and is always the fallback. llm_client is only ever consulted to
    try to REFINE the result on free-text comments -- never to replace
    deterministic rating-based defaults, and its output is validated before
    use (must be a JSON list of strings, every one a real FeedbackCategory
    value) exactly like story/generator.py's _parse_generator_response()."""
    deterministic_result = _deterministic_classify(feedback, comment)

    if llm_client is None:
        return deterministic_result, GeneratedBy.DETERMINISTIC_RULES

    from agents.llm_client import LLMUnavailable

    text = comment or feedback.comment
    if not text:
        # Nothing for an LLM to add over a plain rating -- skip the call
        # entirely rather than invoking it on empty input.
        return deterministic_result, GeneratedBy.DETERMINISTIC_RULES

    system = (
        "Classify the following analyst feedback comment into zero or more of these categories: "
        + ", ".join(c.value for c in FeedbackCategory)
        + ". Respond with ONLY a JSON array of category strings, nothing else."
    )
    try:
        response = llm_client.create(
            system=system, messages=[llm_client.build_user_message(text)], tools=[], max_tokens=200,
        )
    except LLMUnavailable:
        return deterministic_result, GeneratedBy.DETERMINISTIC_RULES

    import json

    text_blocks = [b.get("text", "") for b in response.content if b.get("type") == "text"]
    raw_text = "".join(text_blocks).strip()
    try:
        parsed = json.loads(raw_text)
        if not isinstance(parsed, list):
            raise ValueError("LLM classifier response was not a JSON list")
        llm_categories = [FeedbackCategory(item) for item in parsed]
    except (ValueError, TypeError, KeyError):
        # Malformed or invalid-category output -- never trusted. Falls back
        # to the deterministic result rather than raising, matching
        # story/planner.py's "invalid LLM output degrades gracefully" posture.
        return deterministic_result, GeneratedBy.DETERMINISTIC_RULES

    merged = list(deterministic_result)
    for category in llm_categories:
        if category not in merged:
            merged.append(category)
    return merged, GeneratedBy.LLM_CLASSIFIED_VALIDATED
