"""Step 8: engine.py retry/regeneration tests -- first fails verification,
regenerates with feedback, second succeeds; max retries enforced;
persistent failure produces a safe failure state (fallback or exception per
config)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest  # noqa: E402

from agents.llm_client import FakeLLMClient, LLMResponse  # noqa: E402

from story.config import StorytellingConfig  # noqa: E402
from story.engine import generate_kpi_story  # noqa: E402
from story.models import ClaimType, EvidenceItem, EvidencePackage, GeneratedBy, Persona, StoryGenerationFailed, \
    ValidationStatus  # noqa: E402
from story.persona import PersonaEngine  # noqa: E402


def _item(evidence_id, metric, value=52.1, unit="percent"):
    return EvidenceItem(
        evidence_id=evidence_id, metric=metric, value=value, unit=unit, direction="increase", period="2017-11",
        source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00", analytical_method="x",
        confidence="HIGH", claim_type=ClaimType.FACT,
    )


def _package():
    items = [_item("EV001", "revenue", 52.1, "percent")]
    return EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=items)


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn", input_tokens=10,
                        output_tokens=10, model="fake-model")


def _planner_deterministic_json():
    """A minimal, always-valid planner response so tests can focus their
    scripted logic on the GENERATOR's behavior across retries, without the
    planner's own (also LLM-eligible) call consuming script entries."""
    return json.dumps({"sections": [{"title": "What happened", "evidence_ids": ["EV001"]}]})


def _valid_json():
    return json.dumps({
        "headline": "Revenue grew.",
        "sections": [{"title": "What happened", "statements": [
            {"text": "Revenue increased 52.1%.", "evidence_ids": ["EV001"], "claim_type": "FACT", "confidence": None},
        ]}],
    })


def _wrong_number_json():
    return json.dumps({
        "headline": "Revenue grew.",
        "sections": [{"title": "What happened", "statements": [
            {"text": "Revenue increased 57%.", "evidence_ids": ["EV001"], "claim_type": "FACT", "confidence": None},
        ]}],
    })


def _engine_and_config(allow_fallback=True, max_retries=2):
    engine = PersonaEngine.load()
    raw = StorytellingConfig.load()
    raw._raw["generation"]["max_generation_retries"] = max_retries
    raw._raw["fallback"]["allow_deterministic_fallback"] = allow_fallback
    return engine, raw


class _RoutingFakeLLMClient:
    """Routes .create() calls by system-prompt identity: the planner and
    generator use DIFFERENT system prompts (story.prompts.PLANNER_SYSTEM_PROMPT
    vs GENERATOR_SYSTEM_PROMPT), so a single scripted fake can give each its
    own independent response sequence without one stage's calls consuming
    the other's script entries. Mirrors tests/_llm_test_helpers.py's
    ScriptedRoutingClient pattern from Step 5."""

    def __init__(self, planner_script, generator_script):
        self._planner_script = planner_script
        self._generator_script = generator_script
        self.calls: list[dict] = []

    def build_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def build_tool_result_messages(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": i, "content": c} for i, c in results]

    def create(self, *, system: str, messages: list, tools: list, max_tokens: int = 4096):
        from story.prompts import PLANNER_SYSTEM_PROMPT

        self.calls.append({"system": system, "messages": list(messages)})
        if system == PLANNER_SYSTEM_PROMPT:
            return self._planner_script(messages)
        return self._generator_script.pop(0)


def test_first_attempt_fails_second_succeeds():
    generator_responses = [_text_response(_wrong_number_json()), _text_response(_valid_json())]
    routed = _RoutingFakeLLMClient(
        planner_script=lambda messages: _text_response(_planner_deterministic_json()),
        generator_script=list(generator_responses),
    )
    persona_engine, config = _engine_and_config()
    story = generate_kpi_story(Persona.EXECUTIVE, _package(), persona_engine=persona_engine, config=config,
                                llm_client=routed)
    assert story.verification.status == ValidationStatus.APPROVED
    assert story.generation_attempts == 2


def test_first_attempt_succeeds_immediately():
    fake = FakeLLMClient(script=lambda messages: _text_response(_valid_json()))
    persona_engine, config = _engine_and_config()
    story = generate_kpi_story(Persona.EXECUTIVE, _package(), persona_engine=persona_engine, config=config,
                                llm_client=fake)
    assert story.generation_attempts == 1
    assert story.verification.status == ValidationStatus.APPROVED


def test_max_retries_enforced_then_falls_back_when_allowed():
    fake = FakeLLMClient(script=lambda messages: _text_response(_wrong_number_json()))
    persona_engine, config = _engine_and_config(allow_fallback=True, max_retries=1)
    story = generate_kpi_story(Persona.EXECUTIVE, _package(), persona_engine=persona_engine, config=config,
                                llm_client=fake)
    # 1 initial attempt + 1 retry = 2 total attempts, both fail verification, then falls back.
    assert story.generated_by == GeneratedBy.DETERMINISTIC_TEMPLATE
    assert story.verification.status == ValidationStatus.APPROVED  # deterministic fallback is self-consistent


def test_persistent_failure_raises_when_fallback_disallowed():
    fake = FakeLLMClient(script=lambda messages: _text_response(_wrong_number_json()))
    persona_engine, config = _engine_and_config(allow_fallback=False, max_retries=1)
    with pytest.raises(StoryGenerationFailed):
        generate_kpi_story(Persona.EXECUTIVE, _package(), persona_engine=persona_engine, config=config,
                            llm_client=fake)


def test_feedback_message_cites_failed_claim_and_trusted_value():
    from story.prompts import GENERATOR_SYSTEM_PROMPT

    generator_responses = [_text_response(_wrong_number_json()), _text_response(_valid_json())]
    routed = _RoutingFakeLLMClient(
        planner_script=lambda messages: _text_response(_planner_deterministic_json()),
        generator_script=list(generator_responses),
    )
    persona_engine, config = _engine_and_config()
    generate_kpi_story(Persona.EXECUTIVE, _package(), persona_engine=persona_engine, config=config, llm_client=routed)
    generator_calls = [c for c in routed.calls if c["system"] == GENERATOR_SYSTEM_PROMPT]
    assert len(generator_calls) == 2
    second_call_content = generator_calls[1]["messages"][0]["content"]
    assert "52.1" in second_call_content
    assert "FAILED CLAIM" in second_call_content


def test_no_llm_client_produces_deterministic_story_directly():
    persona_engine, config = _engine_and_config()
    story = generate_kpi_story(Persona.EXECUTIVE, _package(), persona_engine=persona_engine, config=config,
                                llm_client=None)
    assert story.generated_by == GeneratedBy.DETERMINISTIC_TEMPLATE
    assert story.verification.status == ValidationStatus.APPROVED
    assert story.generation_attempts == 1
