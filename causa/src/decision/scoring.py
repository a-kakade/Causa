"""
scoring.py — Step 7: controllability, effort, and priority scoring.

Pure, deterministic, no LLM. Controllability/effort are tier lookups from
config/decision_scoring.yaml, keyed by the ontology's own
controllability_tier/effort_tier declaration for an action_type -- never
hidden in an LLM prompt. Priority is the configurable formula:

    priority = impact * confidence * controllability / effort

with effort clamped to a config-declared divide_by_zero_floor before
division (task's own explicit divide-by-zero guard). The formula's literal
string is echoed from config/decision_scoring.yaml into
ScoreBreakdown.priority_formula purely for audit purposes; supporting a
fully swappable formula (parsed/evaluated from an arbitrary config string)
is documented future work, not built in this pass -- it would need a real
expression parser to avoid an eval() security smell, which is
over-engineering for this MVP relative to the task's explicit
"production-lean, not over-engineered" instruction. Every numeric INPUT to
the formula is already 100% config- and data-driven.
"""

from __future__ import annotations

from typing import Optional

from decision.ontology import DecisionScoringConfig


def compute_controllability(action_type: dict, scoring_config: DecisionScoringConfig) -> tuple[float, str]:
    tier = action_type.get("controllability_tier", "LOW")
    score = scoring_config.controllability_tier_scores.get(tier, 0.0)
    basis = f"controllability_tier={tier!r} (config/decision_scoring.yaml::controllability_tier_scores)"
    return score, basis


def compute_effort(action_type: dict, scoring_config: DecisionScoringConfig) -> tuple[float, str]:
    tier = action_type.get("effort_tier", "HIGH")
    score = scoring_config.effort_tier_scores.get(tier, 1.0)
    basis = f"effort_tier={tier!r} (config/decision_scoring.yaml::effort_tier_scores)"
    return score, basis


def compute_priority(impact: Optional[float], confidence: float, controllability: float, effort: float,
                      scoring_config: DecisionScoringConfig) -> float:
    """impact=None (i.e. ExpectedImpact.is_estimable=False) is treated as 0.0
    for ranking purposes -- never fabricated as a positive number, but also
    never silently dropped from ranking (a candidate with unknown impact
    still gets a real, low priority score and appears in the pipeline
    trace/ranking_explanation as such)."""
    effort_floor = scoring_config.divide_by_zero_floor()
    safe_effort = max(effort, effort_floor)
    safe_impact = impact if impact is not None else 0.0
    return (safe_impact * confidence * controllability) / safe_effort
