"""
candidate_generator.py — Step 7: generates MULTIPLE candidate
ActionRecommendation drafts for a DriverSignal.

Deterministic core: one draft recommendation per (lever, action_type) pair
declared in the ontology for the signal's driver, template-filled from
DriverSignal fields only. This is the primary path and the only one
exercised by tests/the demo script.

This is one of exactly two modules in src/decision/ allowed to import
agents.llm_client (the other is explanation.py) -- an optional LLM may
rephrase a candidate's possible_action sentence, but:
  - it only ever sees facts that already exist before any score is computed
    (driver, lever, segment, action_id, owner -- never impact/confidence/
    priority, which don't exist yet at this stage);
  - its output is passed through agents.models.assert_no_unsupported_causal_language
    (structurally, via ActionRecommendation.__post_init__) and a numeric-claims
    check (agents.models.extract_numeric_claims) that rejects any digit not
    already present in the facts handed to it;
  - any failure, or llm_client=None, falls back to the raw deterministic
    template string -- the pipeline is always fully functional and
    deterministic with zero LLM calls (tests and the demo run this way).

Drafts returned here have expected_impact/constraints/scores all left as
placeholders -- impact_estimator.py, constraint_engine.py, confidence_engine.py,
and scoring.py fill those in later pipeline stages (ranking.py orchestrates).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from agents.models import validate_numeric_claims

from decision.models import (
    ActionRecommendation,
    ConstraintSeverity,
    ConstraintStatus,
    DataSource,
    ExpectedImpact,
    GeneratedBy,
    MonitoringTarget,
    RecommendationTier,
    ScoreBreakdown,
)
from decision.ontology import DecisionOntology

_EMPTY_IMPACT_METRIC = "unassigned"


def _placeholder_impact(metric: str) -> ExpectedImpact:
    return ExpectedImpact(
        metric=metric, estimated_effect=None, effect_unit="unknown", addressable_population=None,
        confidence=None, calculated_impact=None, revenue_impact=None,
        effect_source=DataSource.UNKNOWN.value, population_source=DataSource.UNKNOWN.value,
        confidence_basis="not yet estimated", is_estimable=False,
    )


def _placeholder_score_breakdown() -> ScoreBreakdown:
    return ScoreBreakdown(
        confidence_factors={}, confidence_weights={}, confidence_score=0.0,
        controllability_score=0.0, controllability_basis="not yet scored",
        effort_score=0.0, effort_basis="not yet scored",
        priority_formula="not yet computed", priority_score=0.0,
    )


def _segment_label(driver_signal: Any) -> str:
    """A short, human-readable segment phrase built ONLY from DriverSignal
    fields already present -- never invented. Falls back to the kpi_id/period
    if business_context carries no more specific segment key."""
    segment = driver_signal.business_context.get("segment")
    if segment:
        return str(segment)
    return f"{driver_signal.kpi_id} ({driver_signal.period})"


def _fill_template(template: str, driver_signal: Any) -> str:
    return template.format(driver=driver_signal.driver, segment=_segment_label(driver_signal))


def _allowed_numbers_for_rephrase(driver_signal: Any, action_type: dict) -> set[float]:
    """Numbers an LLM rephrase is allowed to mention at THIS stage -- only
    facts that already exist before any score is computed. Never includes
    impact/confidence/priority, since those are computed later."""
    allowed: set[float] = set()
    for value in (driver_signal.observed_change_pct, driver_signal.observed_change_absolute,
                  driver_signal.addressable_population, driver_signal.historical_estimated_effect):
        if isinstance(value, (int, float)):
            allowed.add(round(float(value), 6))
    return allowed


def _llm_rephrase(template_text: str, driver_signal: Any, action_type: dict, llm_client: Any) -> tuple[str, GeneratedBy]:
    """Attempts an LLM rephrase of an already-deterministic template string.
    Falls back to the raw template on ANY failure -- malformed output,
    fabricated numbers, causal-language violation, or no llm_client at all.
    Never raises; the caller always gets a usable string back."""
    if llm_client is None:
        return template_text, GeneratedBy.DETERMINISTIC_TEMPLATE

    from agents.llm_client import LLMUnavailable  # local import: keeps this module's LLM
                                                    # dependency confined to this one function

    prompt = (
        "Rephrase the following business action recommendation into one clear, natural sentence. "
        "Do not add any number, percentage, or currency amount that is not already present in the text. "
        "Do not claim the action definitely caused or will cause anything -- describe it as a proposed "
        f"action only.\n\nAction: {template_text}"
    )
    try:
        response = llm_client.create(
            system="You rephrase business action recommendations. You never invent numbers or causal claims.",
            messages=[llm_client.build_user_message(prompt)], tools=[], max_tokens=200,
        )
    except LLMUnavailable:
        return template_text, GeneratedBy.DETERMINISTIC_TEMPLATE
    except Exception:
        return template_text, GeneratedBy.DETERMINISTIC_TEMPLATE

    text_blocks = [b.get("text", "") for b in response.content if b.get("type") == "text"]
    candidate = " ".join(t.strip() for t in text_blocks if t.strip())
    if not candidate or len(candidate) > 500:
        return template_text, GeneratedBy.DETERMINISTIC_TEMPLATE

    allowed = _allowed_numbers_for_rephrase(driver_signal, action_type)
    ok, _violations = validate_numeric_claims(candidate, allowed)
    if not ok:
        return template_text, GeneratedBy.DETERMINISTIC_TEMPLATE  # fabricated/out-of-band number -- reject

    return candidate, GeneratedBy.LLM_PHRASED_SCHEMA_VALIDATED


def generate_candidates(driver_signal: Any, ontology: DecisionOntology, llm_client: Optional[Any] = None
                         ) -> list[ActionRecommendation]:
    """Returns [] for an unsupported driver (this ontology's own
    unsupported_driver_policy == "abstain") -- never a generic fallback
    action. Otherwise returns one draft ActionRecommendation per (lever,
    action_type) declared for the driver, in the ontology's own fixed order
    (deterministic)."""
    entry = ontology.get_driver(driver_signal.driver)
    if entry is None:
        return []

    candidates: list[ActionRecommendation] = []
    for action_type in ontology.action_types_for(driver_signal.driver):
        template_text = _fill_template(action_type["template"], driver_signal)
        possible_action, generated_by = _llm_rephrase(template_text, driver_signal, action_type, llm_client)

        recommendation_id = f"rec_{driver_signal.driver}_{action_type['action_id']}"
        rationale = (
            f"{driver_signal.driver} is associated with a movement in {driver_signal.kpi_id}; "
            f"{action_type['_lever']} is a controllable lever the business can act on directly."
        )
        candidates.append(ActionRecommendation(
            recommendation_id=recommendation_id,
            driver=driver_signal.driver,
            driver_category=entry["driver_category"],
            controllable_lever=action_type["_lever"],
            possible_action=possible_action,
            expected_impact=_placeholder_impact(metric=_EMPTY_IMPACT_METRIC),
            owner=action_type["likely_owners"][0],
            constraints=[],
            controllability=0.0,
            effort=0.0,
            priority_score=0.0,
            monitoring_kpis=[],
            rationale=rationale,
            assumptions=[f"{action_type['_lever']} genuinely affects {driver_signal.kpi_id} as ontology-declared."],
            score_breakdown=_placeholder_score_breakdown(),
            tier=RecommendationTier.ALTERNATIVE,  # placeholder -- ranking.py assigns the real tier
            ranking_explanation=[],
            action_justified_by_evidence=bool(
                driver_signal.source == "STEP6_CAUSAL_RESULT" and driver_signal.causal_claim_allowed
            ),
            generated_by=generated_by,
            source_driver_signal_id=f"{driver_signal.driver}_{driver_signal.kpi_id}_{driver_signal.period}",
        ))
    return candidates
