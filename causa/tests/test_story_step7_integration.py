"""Step 8: Step 7 integration tests -- a claim citing a recommendation
reproduces ActionRecommendation.owner/expected_impact.calculated_impact/
score_breakdown.confidence_score verbatim; an invented number for a
recommendation is rejected."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.llm_client import FakeLLMClient, LLMResponse  # noqa: E402

from decision.models import (  # noqa: E402
    ActionRecommendation,
    DataSource,
    ExpectedImpact,
    GeneratedBy as DecisionGeneratedBy,
    RecommendationTier,
    ScoreBreakdown,
)
from story.claim_verifier import verify_story_claims  # noqa: E402
from story.config import StorytellingConfig  # noqa: E402
from story.evidence_package import build_evidence_package  # noqa: E402
from story.generator import generate_narrative  # noqa: E402
from story.models import ClaimType, NarrativePlan, NarrativePlanSection, Persona, ValidationStatus  # noqa: E402
from story.persona import PersonaEngine  # noqa: E402


def _action_recommendation():
    impact = ExpectedImpact(
        metric="on_time_delivery_rate", estimated_effect=0.06, effect_unit="pp", addressable_population=12500,
        confidence=0.78, calculated_impact=585.0, revenue_impact=None,
        effect_source=DataSource.HISTORICAL_ESTIMATE.value, population_source=DataSource.HISTORICAL_ESTIMATE.value,
        confidence_basis="test", is_estimable=True,
    )
    breakdown = ScoreBreakdown(
        confidence_factors={}, confidence_weights={}, confidence_score=0.78, controllability_score=0.9,
        controllability_basis="test", effort_score=0.2, effort_basis="test",
        priority_formula="impact * confidence * controllability / effort", priority_score=1679.5,
    )
    return ActionRecommendation(
        recommendation_id="rec_delivery_delay_expedite", driver="delivery_delay",
        driver_category="FULFILLMENT_LOGISTICS", controllable_lever="shipment_prioritization",
        possible_action="Expedite high-risk shipments.", expected_impact=impact, owner="Operations Manager",
        constraints=[], controllability=0.9, effort=0.2, priority_score=1679.5, monitoring_kpis=[],
        rationale="delivery_delay is associated with a movement in on_time_delivery_rate.",
        assumptions=["assumption"], score_breakdown=breakdown, tier=RecommendationTier.TOP,
        ranking_explanation=["ranked #1"], action_justified_by_evidence=False,
        generated_by=DecisionGeneratedBy.DETERMINISTIC_TEMPLATE, source_driver_signal_id="sig1",
    )


def _package_with_recommendation():
    rec = _action_recommendation()
    return build_evidence_package(kpi_id="on_time_delivery_rate", period="2017-11", recommendations=[rec]), rec


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(content=[{"type": "text", "text": text}], stop_reason="end_turn", input_tokens=10,
                        output_tokens=10, model="fake-model")


def test_deterministic_generator_cites_recommendation_verbatim():
    package, rec = _package_with_recommendation()
    plan = NarrativePlan(persona=Persona.EXECUTIVE,
                          sections=[NarrativePlanSection(title="Recommended actions", evidence_ids=[])])
    engine = PersonaEngine.load()
    config = StorytellingConfig.load()
    sections, _ = generate_narrative(Persona.EXECUTIVE, plan, package, engine, config, llm_client=None)
    statements = [s for section in sections for s in section.statements]
    assert any(rec.possible_action in s.text for s in statements)
    action_statement = next(s for s in statements if rec.possible_action in s.text)
    assert action_statement.confidence == rec.score_breakdown.confidence_score
    assert action_statement.evidence_ids == [rec.recommendation_id]


def test_llm_claim_citing_recommendation_with_correct_numbers_approved():
    package, rec = _package_with_recommendation()
    valid = json.dumps({
        "headline": "Expedite shipments.",
        "sections": [{"title": "Recommended actions", "statements": [
            {"text": f"Recommended action: {rec.possible_action} Expected impact is 585.0.",
             "evidence_ids": [rec.recommendation_id], "claim_type": "ANALYTICAL_FINDING", "confidence": 0.78},
        ]}],
    })
    fake = FakeLLMClient(script=lambda messages: _text_response(valid))
    plan = NarrativePlan(persona=Persona.EXECUTIVE,
                          sections=[NarrativePlanSection(title="Recommended actions", evidence_ids=[])])
    engine = PersonaEngine.load()
    config = StorytellingConfig.load()
    sections, _ = generate_narrative(Persona.EXECUTIVE, plan, package, engine, config, llm_client=fake)
    _, verification = verify_story_claims(sections, package)
    assert verification.status == ValidationStatus.APPROVED


def test_llm_claim_with_invented_impact_number_rejected():
    package, rec = _package_with_recommendation()
    invented = json.dumps({
        "headline": "Expedite shipments.",
        "sections": [{"title": "Recommended actions", "statements": [
            {"text": f"Recommended action: {rec.possible_action} Expected impact is 999999.",
             "evidence_ids": [rec.recommendation_id], "claim_type": "ANALYTICAL_FINDING", "confidence": 0.78},
        ]}],
    })
    fake = FakeLLMClient(script=lambda messages: _text_response(invented))
    plan = NarrativePlan(persona=Persona.EXECUTIVE,
                          sections=[NarrativePlanSection(title="Recommended actions", evidence_ids=[])])
    engine = PersonaEngine.load()
    config = StorytellingConfig.load()
    sections, _ = generate_narrative(Persona.EXECUTIVE, plan, package, engine, config, llm_client=fake)
    _, verification = verify_story_claims(sections, package)
    assert verification.status == ValidationStatus.REJECTED


def test_recommendation_not_in_package_is_rejected():
    package, _rec = _package_with_recommendation()
    from story.models import NarrativeClaim

    claim = NarrativeClaim(text="Recommended action: do something else entirely.",
                            claim_type=ClaimType.ANALYTICAL_FINDING, evidence_ids=["rec_not_real"])
    from story.claim_verifier import verify_claim
    result = verify_claim(claim, package, 0.0005, 0.01)
    assert result.validation_status == ValidationStatus.REJECTED
    assert "rec_not_real" in result.rejection_reason
