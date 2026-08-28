"""Step 8: planner.py tests -- only valid evidence IDs selected, unsupported
IDs rejected (fallback), persona changes ordering, deterministic fallback
with llm_client=None."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.llm_client import FakeLLMClient, LLMResponse, LLMUnavailable  # noqa: E402

from story.config import StorytellingConfig  # noqa: E402
from story.models import ClaimType, EvidenceItem, EvidencePackage, Persona  # noqa: E402
from story.persona import PersonaEngine  # noqa: E402
from story.planner import plan_narrative  # noqa: E402


def _item(evidence_id, metric, value=1.0, unit="percent", evidence_type="KPI_MOVEMENT"):
    return EvidenceItem(
        evidence_id=evidence_id, metric=metric, value=value, unit=unit, direction="increase", period="2017-11",
        source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00", analytical_method="x",
        confidence="HIGH", claim_type=ClaimType.FACT, evidence_type=evidence_type,
    )


def _package():
    items = [_item("EV001", "revenue"), _item("EV002", "orders"), _item("EV003", "aov"),
             _item("EV004", "volume", evidence_type="DRIVER_CONTRIBUTION"),
             _item("EV006", "on_time_delivery_rate", evidence_type="ANOMALY_SIGNAL")]
    return EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=items)


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn", input_tokens=10,
                        output_tokens=10, model="fake-model")


def _engine_and_config():
    return PersonaEngine.load(), StorytellingConfig.load()


def test_deterministic_plan_with_no_llm_client():
    engine, config = _engine_and_config()
    plan = plan_narrative(Persona.EXECUTIVE, _package(), engine, config, llm_client=None)
    assert plan.sections
    all_planned_ids = {eid for s in plan.sections for eid in s.evidence_ids}
    assert all_planned_ids <= _package().all_ids()


def test_valid_llm_plan_accepted():
    valid_json = json.dumps({"sections": [{"title": "What happened", "evidence_ids": ["EV001", "EV002"]}]})
    fake = FakeLLMClient(script=lambda messages: _text_response(valid_json))
    engine, config = _engine_and_config()
    plan = plan_narrative(Persona.EXECUTIVE, _package(), engine, config, llm_client=fake)
    assert len(plan.sections) == 1
    assert plan.sections[0].evidence_ids == ["EV001", "EV002"]


def test_llm_plan_with_unknown_evidence_id_falls_back():
    bad_json = json.dumps({"sections": [{"title": "What happened", "evidence_ids": ["EV001", "EV999"]}]})
    fake = FakeLLMClient(script=lambda messages: _text_response(bad_json))
    engine, config = _engine_and_config()
    plan = plan_narrative(Persona.EXECUTIVE, _package(), engine, config, llm_client=fake)
    all_planned_ids = {eid for s in plan.sections for eid in s.evidence_ids}
    assert "EV999" not in all_planned_ids  # fell back to deterministic plan


def test_malformed_json_falls_back():
    fake = FakeLLMClient(script=lambda messages: _text_response("not valid json {{{"))
    engine, config = _engine_and_config()
    plan = plan_narrative(Persona.EXECUTIVE, _package(), engine, config, llm_client=fake)
    assert plan.sections  # deterministic fallback still produces a valid plan


def test_llm_unavailable_falls_back():
    def _raise(messages):
        raise LLMUnavailable("no credentials")

    fake = FakeLLMClient(script=_raise)
    engine, config = _engine_and_config()
    plan = plan_narrative(Persona.EXECUTIVE, _package(), engine, config, llm_client=fake)
    assert plan.sections


def test_missing_sections_key_falls_back():
    fake = FakeLLMClient(script=lambda messages: _text_response(json.dumps({"wrong_key": []})))
    engine, config = _engine_and_config()
    plan = plan_narrative(Persona.EXECUTIVE, _package(), engine, config, llm_client=fake)
    assert plan.sections


def test_persona_changes_deterministic_plan_ordering():
    engine, config = _engine_and_config()
    exec_plan = plan_narrative(Persona.EXECUTIVE, _package(), engine, config, llm_client=None)
    ops_plan = plan_narrative(Persona.OPERATIONS, _package(), engine, config, llm_client=None)
    exec_ids = [eid for s in exec_plan.sections for eid in s.evidence_ids]
    ops_ids = [eid for s in ops_plan.sections for eid in s.evidence_ids]
    assert exec_ids != ops_ids


def test_empty_package_produces_valid_plan_with_empty_sections():
    engine, config = _engine_and_config()
    empty_package = EvidencePackage(package_id="empty", kpi_id="revenue", period="2017-11", items=[])
    plan = plan_narrative(Persona.EXECUTIVE, empty_package, engine, config, llm_client=None)
    assert plan.sections is not None
