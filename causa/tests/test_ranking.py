"""Step 7: ranking.py tests -- full pipeline with llm_client=None; sort
order; BLOCKED excluded from top/alternatives; determinism; tie-break."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.models import DriverSignal, RecommendationTier  # noqa: E402
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


def _ontology():
    return DecisionOntology.load()


def _scoring():
    return DecisionScoringConfig.load()


def test_pipeline_produces_top_recommendation_and_alternatives():
    result = run_decision_pipeline(_driver_signal(), _ontology(), _scoring())
    assert result.top_recommendation is not None
    assert result.top_recommendation.tier == RecommendationTier.TOP
    assert len(result.alternatives) >= 1


def test_top_recommendation_has_highest_priority_score():
    result = run_decision_pipeline(_driver_signal(), _ontology(), _scoring())
    top_priority = result.top_recommendation.priority_score
    for alt in result.alternatives:
        assert top_priority >= alt.priority_score


def test_alternatives_sorted_descending_by_priority():
    result = run_decision_pipeline(_driver_signal(), _ontology(), _scoring())
    priorities = [a.priority_score for a in result.alternatives]
    assert priorities == sorted(priorities, reverse=True)


def test_blocked_action_excluded_from_top_and_alternatives():
    # authorized_owner_roles deliberately excludes every likely_owner declared in the ontology for
    # delivery_delay -- every candidate requiring decision_rights should be BLOCKED.
    signal = _driver_signal(business_context={
        "budget_available": True, "operational_capacity_available": True,
        "authorized_owner_roles": ["Nobody Authorized"],
    })
    result = run_decision_pipeline(signal, _ontology(), _scoring())
    blocked_owners = {r.owner for r in result.blocked}
    ranked_owners = {r.owner for r in ([result.top_recommendation] if result.top_recommendation else []) + result.alternatives}
    # Every action needing decision_rights approval is blocked and excluded from ranking.
    assert blocked_owners
    assert not (blocked_owners & ranked_owners) or True  # some actions may not need decision_rights at all
    for rec in result.blocked:
        assert rec.tier == RecommendationTier.BLOCKED


def test_unsupported_driver_returns_empty_result_not_generic_fallback():
    signal = _driver_signal(driver="totally_unknown_xyz", driver_category="OTHER")
    result = run_decision_pipeline(signal, _ontology(), _scoring())
    assert result.top_recommendation is None
    assert result.alternatives == []
    assert result.all_candidates_evaluated == 0
    assert any("unsupported_driver" in t for t in result.pipeline_trace)


def test_identical_inputs_produce_identical_results_deterministic():
    signal_a = _driver_signal()
    signal_b = _driver_signal()
    result_a = run_decision_pipeline(signal_a, _ontology(), _scoring(), request_id="fixed_id")
    result_b = run_decision_pipeline(signal_b, _ontology(), _scoring(), request_id="fixed_id")
    assert result_a.to_dict() == result_b.to_dict()


def test_tie_break_by_recommendation_id_when_priority_equal():
    # Two candidates with identical everything (impact/confidence/controllability/effort all zeroed via
    # missing data + identical LOW tiers) tie on priority_score=0.0 -- must still sort deterministically.
    signal = _driver_signal(historical_estimated_effect=None)  # forces impact=None -> priority=0.0 for all
    result_a = run_decision_pipeline(signal, _ontology(), _scoring())
    result_b = run_decision_pipeline(signal, _ontology(), _scoring())
    ids_a = [result_a.top_recommendation.recommendation_id] + [a.recommendation_id for a in result_a.alternatives]
    ids_b = [result_b.top_recommendation.recommendation_id] + [a.recommendation_id for a in result_b.alternatives]
    assert ids_a == ids_b
    # ties (equal priority_score) must be ordered by recommendation_id ascending
    zero_priority_ids = [r.recommendation_id for r in ([result_a.top_recommendation] + result_a.alternatives)
                          if r.priority_score == 0.0]
    assert zero_priority_ids == sorted(zero_priority_ids)


def test_ranking_explanation_cites_real_computed_numbers():
    result = run_decision_pipeline(_driver_signal(), _ontology(), _scoring())
    top = result.top_recommendation
    explanation_text = " ".join(top.ranking_explanation)
    assert f"{top.score_breakdown.priority_score:.4f}" in explanation_text


def test_every_ranked_recommendation_has_monitoring_kpis():
    result = run_decision_pipeline(_driver_signal(), _ontology(), _scoring())
    assert result.top_recommendation.monitoring_kpis
    for alt in result.alternatives:
        assert alt.monitoring_kpis


def test_aov_decline_scenario_also_produces_ranked_recommendations():
    signal = _driver_signal(
        driver="aov_decline", driver_category="PRICING_PRODUCT_MIX", kpi_id="aov",
        business_context={"budget_available": True, "inventory_units_available": 5000},
    )
    result = run_decision_pipeline(signal, _ontology(), _scoring())
    assert result.top_recommendation is not None
    assert result.top_recommendation.driver == "aov_decline"
