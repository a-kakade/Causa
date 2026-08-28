"""Step 8: generator.py tests -- FakeLLMClient scripted for the 5 required
scenarios: valid response, wrong-number response, unsupported-claim
response, wrong-causality response, malformed JSON response."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest  # noqa: E402

from agents.llm_client import FakeLLMClient, LLMResponse, LLMUnavailable  # noqa: E402

from story.claim_verifier import verify_story_claims  # noqa: E402
from story.config import StorytellingConfig  # noqa: E402
from story.generator import MalformedGeneratorOutput, generate_narrative  # noqa: E402
from story.models import ClaimType, EvidenceItem, EvidencePackage, GeneratedBy, NarrativePlan, NarrativePlanSection, \
    Persona, ValidationStatus  # noqa: E402
from story.persona import PersonaEngine  # noqa: E402


def _item(evidence_id, metric, value=52.1, unit="percent", claim_type=ClaimType.FACT):
    return EvidenceItem(
        evidence_id=evidence_id, metric=metric, value=value, unit=unit, direction="increase", period="2017-11",
        source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00", analytical_method="x",
        confidence="HIGH", claim_type=claim_type,
    )


def _package():
    items = [
        _item("EV001", "revenue", 52.1, "percent", ClaimType.FACT),
        _item("EV006", "on_time_delivery_rate", 27.9, "percent", ClaimType.ASSOCIATION),
    ]
    return EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=items)


def _plan():
    return NarrativePlan(persona=Persona.EXECUTIVE,
                          sections=[NarrativePlanSection(title="What happened", evidence_ids=["EV001", "EV006"])])


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn", input_tokens=10,
                        output_tokens=10, model="fake-model")


def _engine_and_config():
    return PersonaEngine.load(), StorytellingConfig.load()


def test_deterministic_fallback_with_no_llm_client():
    engine, config = _engine_and_config()
    sections, generated_by = generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config,
                                                  llm_client=None)
    assert generated_by == GeneratedBy.DETERMINISTIC_TEMPLATE
    assert sections
    _, verification = verify_story_claims(sections, _package())
    assert verification.status == ValidationStatus.APPROVED  # deterministic path always self-consistent


# -- 1. valid response ---------------------------------------------------------

def test_valid_llm_response_accepted():
    valid = json.dumps({
        "headline": "Revenue grew.",
        "sections": [{"title": "What happened", "statements": [
            {"text": "Revenue increased 52.1%.", "evidence_ids": ["EV001"], "claim_type": "FACT", "confidence": None},
        ]}],
    })
    fake = FakeLLMClient(script=lambda messages: _text_response(valid))
    engine, config = _engine_and_config()
    sections, generated_by = generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config,
                                                  llm_client=fake)
    assert generated_by == GeneratedBy.LLM_GENERATED_VERIFIED
    _, verification = verify_story_claims(sections, _package())
    assert verification.status == ValidationStatus.APPROVED


# -- 2. wrong-number response ---------------------------------------------------

def test_wrong_number_response_parses_but_fails_verification():
    wrong_number = json.dumps({
        "headline": "Revenue grew.",
        "sections": [{"title": "What happened", "statements": [
            {"text": "Revenue increased 57%.", "evidence_ids": ["EV001"], "claim_type": "FACT", "confidence": None},
        ]}],
    })
    fake = FakeLLMClient(script=lambda messages: _text_response(wrong_number))
    engine, config = _engine_and_config()
    sections, generated_by = generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config,
                                                  llm_client=fake)
    assert generated_by == GeneratedBy.LLM_GENERATED_VERIFIED  # structurally valid, parses fine
    _, verification = verify_story_claims(sections, _package())
    assert verification.status == ValidationStatus.REJECTED  # but numerically wrong -- verifier catches it
    assert verification.claims_rejected == 1


# -- 3. unsupported-claim response -----------------------------------------------

def test_unsupported_claim_response_parses_but_fails_verification():
    unsupported = json.dumps({
        "headline": "Profit grew.",
        "sections": [{"title": "What happened", "statements": [
            {"text": "Profit increased 18%.", "evidence_ids": ["EV001"], "claim_type": "FACT", "confidence": None},
        ]}],
    })
    fake = FakeLLMClient(script=lambda messages: _text_response(unsupported))
    engine, config = _engine_and_config()
    sections, generated_by = generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config,
                                                  llm_client=fake)
    _, verification = verify_story_claims(sections, _package())
    assert verification.status == ValidationStatus.REJECTED


# -- 4. wrong-causality response --------------------------------------------------

def test_wrong_causality_response_rejected_at_construction_or_verification():
    # NarrativeClaim.__post_init__ rejects unsupported causal language at construction time --
    # generator._parse_generator_response converts that ValueError into MalformedGeneratorOutput,
    # which is the correct outcome here (retried with feedback, not silently accepted).
    wrong_causality = json.dumps({
        "headline": "Delivery caused review decline.",
        "sections": [{"title": "Risks", "statements": [
            {"text": "Delivery deterioration caused lower review scores.", "evidence_ids": ["EV006"],
             "claim_type": "ASSOCIATION", "confidence": None},
        ]}],
    })
    fake = FakeLLMClient(script=lambda messages: _text_response(wrong_causality))
    engine, config = _engine_and_config()
    with pytest.raises(MalformedGeneratorOutput):
        generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config, llm_client=fake)


def test_wrong_causality_response_that_bypasses_construction_guard_caught_by_verifier():
    # A claim phrased with hedged-but-still-technically-causal language that DOES construct
    # successfully (e.g. doesn't match UNSUPPORTED_CAUSAL_PATTERN literally) but still violates
    # its claim_type's language rule should be caught by claim_verifier at the verification stage.
    hedged_but_wrong = json.dumps({
        "headline": "Delivery review link.",
        "sections": [{"title": "Risks", "statements": [
            {"text": "Delivery deterioration coincided with lower review scores.", "evidence_ids": ["EV006"],
             "claim_type": "FACT", "confidence": None},  # mislabeled as FACT for ASSOCIATION-tier evidence
        ]}],
    })
    fake = FakeLLMClient(script=lambda messages: _text_response(hedged_but_wrong))
    engine, config = _engine_and_config()
    sections, _ = generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config, llm_client=fake)
    _, verification = verify_story_claims(sections, _package())
    assert verification.status == ValidationStatus.REJECTED


# -- 5. malformed JSON response --------------------------------------------------

def test_malformed_json_response_raises():
    fake = FakeLLMClient(script=lambda messages: _text_response("this is not { valid json"))
    engine, config = _engine_and_config()
    with pytest.raises(MalformedGeneratorOutput):
        generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config, llm_client=fake)


def test_missing_required_keys_raises():
    fake = FakeLLMClient(script=lambda messages: _text_response(json.dumps({"wrong_key": []})))
    engine, config = _engine_and_config()
    with pytest.raises(MalformedGeneratorOutput):
        generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config, llm_client=fake)


def test_llm_unavailable_falls_back_to_deterministic():
    def _raise(messages):
        raise LLMUnavailable("no credentials")

    fake = FakeLLMClient(script=_raise)
    engine, config = _engine_and_config()
    sections, generated_by = generate_narrative(Persona.EXECUTIVE, _plan(), _package(), engine, config,
                                                  llm_client=fake)
    assert generated_by == GeneratedBy.DETERMINISTIC_TEMPLATE
