"""Step 7: explanation.py tests -- deterministic narrative always works;
fabricated-number/causal-language LLM response rejected and falls back."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.llm_client import FakeLLMClient, LLMResponse, LLMUnavailable  # noqa: E402

from decision.explanation import narrate  # noqa: E402
from decision.models import DriverSignal  # noqa: E402
from decision.ontology import DecisionOntology, DecisionScoringConfig  # noqa: E402
from decision.ranking import run_decision_pipeline  # noqa: E402


def _driver_signal(**overrides):
    defaults = dict(
        driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS", kpi_id="on_time_delivery_rate",
        period="2017-11", observed_change_pct=-0.08, addressable_population=12500,
        addressable_population_source="HISTORICAL_ESTIMATE", historical_estimated_effect=0.06,
        historical_effect_source="HISTORICAL_ESTIMATE", driver_confidence=0.78, source="MANUAL",
        business_context={"budget_available": True, "operational_capacity_available": True},
    )
    defaults.update(overrides)
    return DriverSignal(**defaults)


def _result():
    return run_decision_pipeline(_driver_signal(), DecisionOntology.load(), DecisionScoringConfig.load())


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn",
                        input_tokens=10, output_tokens=10, model="fake-model")


def test_deterministic_narrative_always_available_with_no_llm_client():
    result = _result()
    text = narrate(result, llm_client=None)
    assert result.top_recommendation.possible_action in text
    assert result.top_recommendation.owner in text


def test_narrative_for_no_recommendation_case_is_honest():
    from decision.models import DriverSignal as _DS
    signal = _driver_signal(driver="totally_unknown_xyz", driver_category="OTHER")
    result = run_decision_pipeline(signal, DecisionOntology.load(), DecisionScoringConfig.load())
    text = narrate(result, llm_client=None)
    assert "No actionable recommendation" in text


def test_valid_llm_narrative_accepted():
    result = _result()
    fake = FakeLLMClient(script=lambda messages: _text_response(
        f"The top recommendation is to {result.top_recommendation.possible_action.lower()}, "
        f"owned by {result.top_recommendation.owner}."
    ))
    text = narrate(result, llm_client=fake)
    assert result.top_recommendation.owner in text


def test_llm_narrative_with_fabricated_number_falls_back_to_deterministic():
    result = _result()
    fake = FakeLLMClient(script=lambda messages: _text_response(
        "This action is guaranteed to increase revenue by 999.9% within days."
    ))
    text = narrate(result, llm_client=fake)
    assert result.top_recommendation.possible_action in text  # fell back to deterministic template


def test_llm_narrative_with_causal_language_falls_back_to_deterministic():
    result = _result()
    fake = FakeLLMClient(script=lambda messages: _text_response(
        "This driver caused the KPI decline and the action will fix it."
    ))
    text = narrate(result, llm_client=fake)
    assert result.top_recommendation.possible_action in text  # fell back to deterministic template


def test_llm_unavailable_falls_back_to_deterministic():
    result = _result()

    def _raise(messages):
        raise LLMUnavailable("no credentials")

    fake = FakeLLMClient(script=_raise)
    text = narrate(result, llm_client=fake)
    assert result.top_recommendation.possible_action in text
