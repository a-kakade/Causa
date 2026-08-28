"""Step 8: PersonaEngine / StorytellingConfig loader tests.

Loads the REAL config/personas.yaml and config/storytelling.yaml -- governed
contracts under test, matching tests/test_decision_ontology.py's posture
toward config/decision_ontology.yaml. No LLM, no canonical data.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest  # noqa: E402

from story.config import StorytellingConfig, StorytellingConfigError  # noqa: E402
from story.models import ClaimType, EvidenceItem, EvidencePackage, Persona  # noqa: E402
from story.persona import PersonaConfigError, PersonaEngine  # noqa: E402


def _item(evidence_id, metric, evidence_type, value=1.0):
    return EvidenceItem(
        evidence_id=evidence_id, metric=metric, value=value, unit="percent", direction="increase",
        period="2017-11", source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00",
        analytical_method="x", confidence="HIGH", claim_type=ClaimType.FACT, evidence_type=evidence_type,
    )


def _demo_package():
    items = [
        _item("EV001", "revenue", "KPI_MOVEMENT"),
        _item("EV002", "orders", "KPI_MOVEMENT"),
        _item("EV003", "aov", "KPI_MOVEMENT"),
        _item("EV004", "volume", "DRIVER_CONTRIBUTION"),
        _item("EV005", "mix", "DRIVER_CONTRIBUTION"),
        _item("EV006", "on_time_delivery_rate", "ANOMALY_SIGNAL"),
        _item("EV007", "avg_review_score", "CUSTOMER_REVIEW"),
    ]
    return EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=items)


def test_persona_engine_loads_and_validates_real_config():
    engine = PersonaEngine.load()
    engine.validate()  # must not raise
    assert {"executive", "finance", "operations", "marketing"}.issubset(set(engine.list_personas()))


def test_all_four_required_personas_present():
    engine = PersonaEngine.load()
    for persona in Persona:
        assert engine.get(persona) is not None


def test_missing_required_persona_rejected(tmp_path):
    bad_yaml = tmp_path / "bad_personas.yaml"
    bad_yaml.write_text("version: '1.0'\npersonas:\n  executive:\n    focus_areas: [revenue]\n"
                        "    preferred_metrics: [revenue]\n    detail_level: LOW\n"
                        "    max_statements_per_section: 2\n    section_order: [Headline]\n")
    engine = PersonaEngine.load(bad_yaml)
    with pytest.raises(PersonaConfigError):
        engine.validate()


def test_executive_prioritizes_revenue_and_drivers():
    engine = PersonaEngine.load()
    package = _demo_package()
    ordered = engine.select_and_order(Persona.EXECUTIVE, package)
    ordered_ids = [i.evidence_id for i in ordered]
    # CUSTOMER_REVIEW is excluded for executive -- EV007 must not appear at all.
    assert "EV007" not in ordered_ids
    # preferred metrics (revenue/orders/aov) should rank before non-preferred ones.
    top_metrics = {ordered[0].metric, ordered[1].metric, ordered[2].metric}
    assert top_metrics <= {"revenue", "orders", "aov"}


def test_finance_prioritizes_revenue_bridge_metrics():
    engine = PersonaEngine.load()
    package = _demo_package()
    ordered = engine.select_and_order(Persona.FINANCE, package)
    ordered_ids = [i.evidence_id for i in ordered]
    assert "EV007" not in ordered_ids  # CUSTOMER_REVIEW excluded for finance too
    # DRIVER_CONTRIBUTION (volume/mix) should be preferred-type for finance.
    top_types = {ordered[0].evidence_type, ordered[1].evidence_type}
    assert "DRIVER_CONTRIBUTION" in top_types or ordered[0].metric in ("revenue", "aov", "price", "volume", "mix")


def test_operations_prioritizes_delivery_and_does_not_exclude_reviews():
    engine = PersonaEngine.load()
    package = _demo_package()
    ordered = engine.select_and_order(Persona.OPERATIONS, package)
    ordered_ids = [i.evidence_id for i in ordered]
    assert "EV007" in ordered_ids  # operations does NOT exclude CUSTOMER_REVIEW
    assert "EV006" in ordered_ids  # delivery anomaly signal present


def test_marketing_prioritizes_demand_and_customer_behavior():
    engine = PersonaEngine.load()
    package = _demo_package()
    ordered = engine.select_and_order(Persona.MARKETING, package)
    ordered_ids = [i.evidence_id for i in ordered]
    assert "EV007" in ordered_ids  # marketing does NOT exclude CUSTOMER_REVIEW
    top_metrics = {ordered[0].metric, ordered[1].metric}
    assert top_metrics <= {"orders", "aov", "revenue"}


def test_different_personas_produce_different_orderings_for_same_package():
    engine = PersonaEngine.load()
    package = _demo_package()
    exec_order = [i.evidence_id for i in engine.select_and_order(Persona.EXECUTIVE, package)]
    ops_order = [i.evidence_id for i in engine.select_and_order(Persona.OPERATIONS, package)]
    assert exec_order != ops_order


def test_selection_is_deterministic():
    engine = PersonaEngine.load()
    package = _demo_package()
    order_a = [i.evidence_id for i in engine.select_and_order(Persona.FINANCE, package)]
    order_b = [i.evidence_id for i in engine.select_and_order(Persona.FINANCE, package)]
    assert order_a == order_b


def test_storytelling_config_loads_and_validates_real_config():
    config = StorytellingConfig.load()
    assert config.max_generation_retries() >= 0
    assert 0.0 <= config.temperature() <= 2.0


def test_storytelling_config_rejects_bad_retry_count(tmp_path):
    bad_yaml = tmp_path / "bad_storytelling.yaml"
    bad_yaml.write_text(
        "version: '1.0'\n"
        "llm: {provider: groq, model: null, temperature: 0.2, max_tokens_planner: 800, max_tokens_generator: 1500}\n"
        "generation: {max_generation_retries: -1, prompt_version: v1}\n"
        "verification: {numeric_tolerance: 0.0005, numeric_absolute_floor: 0.01, minimum_magnitude: 20.0}\n"
        "fallback: {allow_deterministic_fallback: true}\n"
    )
    with pytest.raises(StorytellingConfigError):
        StorytellingConfig.load(bad_yaml)
