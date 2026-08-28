"""Step 7: end-to-end test using the exact demo scenario values -- delivery
delay, -8% observed change, 12,500 addressable shipments, +6pp historical
effect, confidence 0.78, budget/capacity available. Asserts the top
recommendation is a concrete, quantified action -- never a generic string
like "improve logistics"."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.models import DriverSignal  # noqa: E402
from decision.ontology import DecisionOntology, DecisionScoringConfig  # noqa: E402
from decision.ranking import run_decision_pipeline  # noqa: E402

_GENERIC_PHRASES = ("improve logistics", "improve delivery", "increase marketing", "do better", "fix the problem")


def _demo_driver_signal() -> DriverSignal:
    return DriverSignal(
        driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS", kpi_id="on_time_delivery_rate",
        period="2017-11", observed_change_pct=-0.08, addressable_population=12500,
        addressable_population_source="HISTORICAL_ESTIMATE", historical_estimated_effect=0.06,
        historical_effect_source="HISTORICAL_ESTIMATE", driver_confidence=0.78, source="MANUAL",
        business_context={"budget_available": True, "operational_capacity_available": True},
    )


def test_end_to_end_delivery_delay_produces_full_recommendation():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    result = run_decision_pipeline(_demo_driver_signal(), ontology, scoring)

    top = result.top_recommendation
    assert top is not None

    # driver / lever / action / owner / constraints / confidence / priority / monitoring -- all present.
    assert top.driver == "delivery_delay"
    assert top.controllable_lever
    assert top.possible_action
    assert top.owner
    assert isinstance(top.constraints, list)
    assert 0.0 <= top.score_breakdown.confidence_score <= 1.0
    assert top.priority_score >= 0.0
    assert top.monitoring_kpis


def test_top_recommendation_is_quantified_not_generic():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    result = run_decision_pipeline(_demo_driver_signal(), ontology, scoring)
    top = result.top_recommendation

    lowered = top.possible_action.lower()
    for phrase in _GENERIC_PHRASES:
        assert phrase not in lowered

    # The recommendation must be traceable to a concrete, real number -- not a vague adjective.
    assert top.expected_impact.calculated_impact == 0.06 * 12500 * 0.78


def test_expected_impact_matches_exact_demo_arithmetic():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    result = run_decision_pipeline(_demo_driver_signal(), ontology, scoring)
    top = result.top_recommendation
    assert top.expected_impact.is_estimable is True
    assert top.expected_impact.estimated_effect == 0.06
    assert top.expected_impact.addressable_population == 12500
    assert top.expected_impact.confidence == 0.78
    assert top.expected_impact.calculated_impact == 0.06 * 12500 * 0.78


def test_multiple_alternative_actions_evaluated_not_just_one():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    result = run_decision_pipeline(_demo_driver_signal(), ontology, scoring)
    assert result.all_candidates_evaluated > 1
    assert len(result.alternatives) >= 1


def test_every_recommendation_traceable_to_driver_lever_action_calculation_constraints():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    result = run_decision_pipeline(_demo_driver_signal(), ontology, scoring)
    all_recs = ([result.top_recommendation] if result.top_recommendation else []) + result.alternatives \
        + result.conditional + result.blocked
    for rec in all_recs:
        assert rec.driver
        assert rec.controllable_lever
        assert rec.possible_action
        assert rec.expected_impact.effect_source
        assert rec.expected_impact.population_source
        assert rec.expected_impact.confidence_basis
        assert isinstance(rec.constraints, list)
        assert rec.ranking_explanation


def test_action_justified_by_evidence_false_for_manual_driver_signal():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    result = run_decision_pipeline(_demo_driver_signal(), ontology, scoring)
    # MANUAL source, never a bridged CausalResult -- must never claim causal justification.
    assert result.top_recommendation.action_justified_by_evidence is False


def test_blocked_constraint_scenario_produces_at_least_one_blocked_or_conditional():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    signal = DriverSignal(
        driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS", kpi_id="on_time_delivery_rate",
        period="2017-11", observed_change_pct=-0.08, addressable_population=12500,
        addressable_population_source="HISTORICAL_ESTIMATE", historical_estimated_effect=0.06,
        historical_effect_source="HISTORICAL_ESTIMATE", driver_confidence=0.78, source="MANUAL",
        business_context={"budget_available": False, "operational_capacity_available": False},
    )
    result = run_decision_pipeline(signal, ontology, scoring)
    assert len(result.blocked) > 0
    for rec in result.blocked:
        assert any(c.status.value == "BLOCKED" for c in rec.constraints)
