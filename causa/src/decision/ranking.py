"""
ranking.py — Step 7: the single entry point for the Decision & Action
Intelligence Engine.

    DriverSignal
        |
        v
    candidate_generator.generate_candidates()   -- deterministic templates; optional LLM phrasing only
        |
        v
    [per candidate] impact_estimator.estimate_impact()
        |
        v
    [per candidate] constraint_engine.evaluate_constraints()
        |
        v
    [per candidate] confidence_engine.compute_confidence()
        |
        v
    [per candidate] scoring.compute_controllability() / compute_effort() / compute_priority()
        |
        v
    tier assignment (BLOCKED / CONDITIONAL / ranked) + sort + ranking_explanation
        |
        v
    [per executable candidate] monitoring.build_monitoring_plan()
        |
        v
    DecisionResult

No LLM import anywhere in this module (task's own non-negotiable: numbers,
confidence, priority, constraints, and ownership are never an LLM's
opinion). Verified by tests/test_decision_provenance.py's AST scan. The
entire pipeline runs deterministically end-to-end with llm_client=None --
every test and the demo script exercise this exact mode.
"""

from __future__ import annotations

from typing import Any, Optional

from decision import candidate_generator, constraint_engine, monitoring, scoring
from decision.confidence_engine import compute_confidence
from decision.models import (
    ActionRecommendation,
    ConstraintStatus,
    DecisionResult,
    RecommendationTier,
    ScoreBreakdown,
    overall_constraint_status,
)
from decision.ontology import DecisionOntology, DecisionScoringConfig
from decision.impact_estimator import estimate_impact


def _tier_for_constraint_status(status: ConstraintStatus) -> RecommendationTier:
    if status == ConstraintStatus.BLOCKED:
        return RecommendationTier.BLOCKED
    if status == ConstraintStatus.WARNING:
        return RecommendationTier.CONDITIONAL
    return RecommendationTier.ALTERNATIVE  # ranking pass below promotes exactly one to TOP


def _build_ranking_explanation(rec: ActionRecommendation, rank: Optional[int], total: int) -> list[str]:
    explanation: list[str] = []
    bd = rec.score_breakdown
    if rank is not None:
        explanation.append(
            f"Ranked #{rank} of {total}: priority={bd.priority_score:.4f} = impact"
            f"({rec.expected_impact.calculated_impact if rec.expected_impact.calculated_impact is not None else 'unknown(treated as 0)'}) "
            f"x confidence({bd.confidence_score:.2f}) x controllability({bd.controllability_score:.2f}) "
            f"/ effort({bd.effort_score:.2f})"
        )
    if not rec.expected_impact.is_estimable:
        explanation.append("Impact could not be estimated -- one or more required inputs was missing; "
                            "priority was computed with impact treated as 0, never fabricated.")
    for check in rec.constraints:
        if check.status != ConstraintStatus.PASS:
            explanation.append(f"Constraint {check.constraint!r} is {check.status.value}: {check.details}")
    if not explanation:
        explanation.append("All constraints pass; impact, confidence, and controllability are estimable.")
    return explanation


def run_decision_pipeline(driver_signal: Any, ontology: DecisionOntology, scoring_config: DecisionScoringConfig,
                           llm_client: Optional[Any] = None, request_id: Optional[str] = None) -> DecisionResult:
    trace: list[str] = []
    req_id = request_id or f"decision_{driver_signal.driver}_{driver_signal.kpi_id}_{driver_signal.period}"

    candidates = candidate_generator.generate_candidates(driver_signal, ontology, llm_client)
    if not candidates:
        trace.append(f"unsupported_driver: {driver_signal.driver} (policy={ontology.unsupported_driver_policy()})")
        return DecisionResult(
            request_id=req_id, driver_signal=driver_signal, top_recommendation=None, alternatives=[],
            conditional=[], blocked=[], all_candidates_evaluated=0, pipeline_trace=trace,
        )
    trace.append(f"generated {len(candidates)} candidate(s) for driver={driver_signal.driver}")

    entry = ontology.get_driver(driver_signal.driver)
    action_types_by_lever_and_id = {
        (a["_lever"], a["action_id"]): a for a in ontology.action_types_for(driver_signal.driver)
    }

    scored: list[ActionRecommendation] = []
    for rec in candidates:
        # Recover this candidate's ontology action_type entry (for tier/constraint/monitoring lookups) --
        # recommendation_id was built as f"rec_{driver}_{action_id}" by candidate_generator.py.
        action_id = rec.recommendation_id[len(f"rec_{driver_signal.driver}_"):]
        action_type = action_types_by_lever_and_id.get((rec.controllable_lever, action_id))
        if action_type is None:
            # Should be unreachable given candidate_generator.py's own construction, but never crash
            # the whole pipeline over one malformed candidate -- skip it, record why.
            trace.append(f"skipped candidate {rec.recommendation_id}: could not resolve ontology action_type")
            continue

        expected_impact = estimate_impact(driver_signal)
        constraints = constraint_engine.evaluate_constraints(
            action_type.get("relevant_constraints", []), driver_signal.business_context, rec.owner, scoring_config,
        )
        confidence_score, factors, weights = compute_confidence(driver_signal, expected_impact, action_type, scoring_config)
        controllability_score, controllability_basis = scoring.compute_controllability(action_type, scoring_config)
        effort_score, effort_basis = scoring.compute_effort(action_type, scoring_config)
        priority_score = scoring.compute_priority(
            expected_impact.calculated_impact, confidence_score, controllability_score, effort_score, scoring_config,
        )

        rec.expected_impact = expected_impact
        rec.constraints = constraints
        rec.controllability = controllability_score
        rec.effort = effort_score
        rec.priority_score = priority_score
        rec.score_breakdown = ScoreBreakdown(
            confidence_factors=factors, confidence_weights=weights, confidence_score=confidence_score,
            controllability_score=controllability_score, controllability_basis=controllability_basis,
            effort_score=effort_score, effort_basis=effort_basis,
            priority_formula=scoring_config.prioritization_formula(), priority_score=priority_score,
        )
        overall_status = overall_constraint_status(constraints)
        rec.tier = _tier_for_constraint_status(overall_status)
        rec.monitoring_kpis = monitoring.build_monitoring_plan(
            action_type.get("monitoring_kpis", []), expected_impact, scoring_config,
        )
        scored.append(rec)

    blocked = [r for r in scored if r.tier == RecommendationTier.BLOCKED]
    conditional = [r for r in scored if r.tier == RecommendationTier.CONDITIONAL]
    rankable = [r for r in scored if r.tier == RecommendationTier.ALTERNATIVE]

    # Deterministic sort: priority_score descending, tie-break by recommendation_id ascending.
    rankable.sort(key=lambda r: (-r.priority_score, r.recommendation_id))
    blocked.sort(key=lambda r: r.recommendation_id)
    conditional.sort(key=lambda r: (-r.priority_score, r.recommendation_id))

    top_recommendation: Optional[ActionRecommendation] = None
    alternatives: list[ActionRecommendation] = []
    if rankable:
        top_recommendation = rankable[0]
        top_recommendation.tier = RecommendationTier.TOP
        alternatives = rankable[1:]

    total = len(rankable)
    for i, rec in enumerate(rankable, start=1):
        rec.ranking_explanation = _build_ranking_explanation(rec, i, total)
    for rec in conditional:
        rec.ranking_explanation = _build_ranking_explanation(rec, None, total)
    for rec in blocked:
        rec.ranking_explanation = _build_ranking_explanation(rec, None, total)

    trace.append(f"ranked {len(rankable)} executable, {len(conditional)} conditional, {len(blocked)} blocked")

    return DecisionResult(
        request_id=req_id, driver_signal=driver_signal, top_recommendation=top_recommendation,
        alternatives=alternatives, conditional=conditional, blocked=blocked,
        all_candidates_evaluated=len(scored), pipeline_trace=trace,
    )
