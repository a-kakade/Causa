"""Step 7: candidate_generator.py tests.

Pure, synthetic -- builds DriverSignal by hand (no canonical data), matching
the style of tests/test_method_selector.py. Uses agents.llm_client.FakeLLMClient
for the optional-LLM-rephrase path (mock the LLM, never the business logic).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.llm_client import FakeLLMClient, LLMResponse  # noqa: E402

from decision.candidate_generator import generate_candidates  # noqa: E402
from decision.models import DriverSignal, GeneratedBy  # noqa: E402
from decision.ontology import DecisionOntology  # noqa: E402


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


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn",
                        input_tokens=10, output_tokens=10, model="fake-model")


def test_multiple_candidates_generated_for_delivery_delay():
    ontology = DecisionOntology.load()
    candidates = generate_candidates(_driver_signal(), ontology)
    assert len(candidates) > 1
    assert all(c.driver == "delivery_delay" for c in candidates)
    assert all(c.driver_category == "FULFILLMENT_LOGISTICS" for c in candidates)


def test_multiple_candidates_generated_for_aov_decline():
    ontology = DecisionOntology.load()
    signal = _driver_signal(driver="aov_decline", driver_category="PRICING_PRODUCT_MIX", kpi_id="aov")
    candidates = generate_candidates(signal, ontology)
    assert len(candidates) > 1
    assert all(c.driver == "aov_decline" for c in candidates)


def test_unsupported_driver_returns_empty_list_not_generic_fallback():
    ontology = DecisionOntology.load()
    signal = _driver_signal(driver="totally_unknown_driver_xyz", driver_category="OTHER")
    candidates = generate_candidates(signal, ontology)
    assert candidates == []


def test_candidates_generated_by_deterministic_template_with_no_llm_client():
    ontology = DecisionOntology.load()
    candidates = generate_candidates(_driver_signal(), ontology, llm_client=None)
    assert all(c.generated_by == GeneratedBy.DETERMINISTIC_TEMPLATE for c in candidates)
    assert all(c.possible_action for c in candidates)  # non-empty, real sentences


def test_valid_llm_rephrase_is_accepted():
    fake = FakeLLMClient(script=lambda messages: _text_response(
        "Expedite the highest-risk shipments affecting on-time delivery performance."
    ))
    ontology = DecisionOntology.load()
    candidates = generate_candidates(_driver_signal(), ontology, llm_client=fake)
    rephrased = [c for c in candidates if c.generated_by == GeneratedBy.LLM_PHRASED_SCHEMA_VALIDATED]
    assert len(rephrased) > 0


def test_llm_rephrase_with_fabricated_number_falls_back_to_template():
    fake = FakeLLMClient(script=lambda messages: _text_response(
        "This action will increase revenue by 47.3% within 2 weeks, guaranteed."
    ))
    ontology = DecisionOntology.load()
    candidates = generate_candidates(_driver_signal(), ontology, llm_client=fake)
    assert all(c.generated_by == GeneratedBy.DETERMINISTIC_TEMPLATE for c in candidates)


def test_llm_unavailable_falls_back_to_template():
    from agents.llm_client import LLMUnavailable

    def _raise(messages):
        raise LLMUnavailable("no credentials")

    fake = FakeLLMClient(script=_raise)
    ontology = DecisionOntology.load()
    candidates = generate_candidates(_driver_signal(), ontology, llm_client=fake)
    assert all(c.generated_by == GeneratedBy.DETERMINISTIC_TEMPLATE for c in candidates)
    assert all(c.possible_action for c in candidates)


def test_action_justified_by_evidence_false_when_not_from_causal_result():
    ontology = DecisionOntology.load()
    candidates = generate_candidates(_driver_signal(source="MANUAL"), ontology)
    assert all(c.action_justified_by_evidence is False for c in candidates)


def test_action_justified_by_evidence_true_when_causal_claim_allowed():
    ontology = DecisionOntology.load()
    signal = _driver_signal(source="STEP6_CAUSAL_RESULT", causal_claim_allowed=True)
    candidates = generate_candidates(signal, ontology)
    assert all(c.action_justified_by_evidence is True for c in candidates)


def test_candidate_recommendation_ids_are_unique():
    ontology = DecisionOntology.load()
    candidates = generate_candidates(_driver_signal(), ontology)
    ids = [c.recommendation_id for c in candidates]
    assert len(ids) == len(set(ids))
