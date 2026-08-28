"""
constraint_engine.py — Step 7: evaluates a candidate ActionRecommendation
against real-world business constraints.

Pure, deterministic, no LLM -- same posture as causal/method_selector.py:
fixed-order dispatch over a dict[str, Callable], one _check_<name> function
per constraint type, evaluated only for the constraint names the ontology
actually declared relevant for this action_type (never a check the action
doesn't need). Missing business_context data is always a WARNING, never a
silent PASS -- "we don't know" is a real, reportable state, not the same as
"it's fine."

A BLOCKED action must not rank as a top executable recommendation
(ranking.py enforces this); a WARNING-only action may still be exposed as
CONDITIONAL.
"""

from __future__ import annotations

from typing import Any

from decision.models import ConstraintCheck, ConstraintSeverity, ConstraintStatus
from decision.ontology import DecisionScoringConfig

# Fixed evaluation order -- deterministic regardless of dict iteration order
# elsewhere in the pipeline.
_CONSTRAINT_ORDER = ("budget", "operational_capacity", "inventory", "geography", "decision_rights")


def _check_budget(business_context: dict[str, Any], thresholds: dict[str, Any]) -> ConstraintCheck:
    if "budget_available" not in business_context:
        return ConstraintCheck("budget", ConstraintStatus.WARNING, "budget availability unknown -- not supplied",
                                ConstraintSeverity.MEDIUM)
    if not business_context["budget_available"]:
        return ConstraintCheck("budget", ConstraintStatus.BLOCKED, "no budget available for this action",
                                ConstraintSeverity.HIGH)
    pct_remaining = business_context.get("budget_remaining_pct")
    if isinstance(pct_remaining, (int, float)):
        cfg = thresholds.get("budget", {})
        if pct_remaining <= cfg.get("blocked_below_pct", 0):
            return ConstraintCheck("budget", ConstraintStatus.BLOCKED,
                                    f"budget remaining ({pct_remaining}%) is at or below the blocked threshold",
                                    ConstraintSeverity.HIGH)
        if pct_remaining < cfg.get("warning_below_pct", 20):
            return ConstraintCheck("budget", ConstraintStatus.WARNING,
                                    f"budget remaining ({pct_remaining}%) is below the warning threshold",
                                    ConstraintSeverity.MEDIUM)
    return ConstraintCheck("budget", ConstraintStatus.PASS, "budget available", ConstraintSeverity.LOW)


def _check_operational_capacity(business_context: dict[str, Any], thresholds: dict[str, Any]) -> ConstraintCheck:
    if "operational_capacity_available" not in business_context:
        return ConstraintCheck("operational_capacity", ConstraintStatus.WARNING,
                                "operational capacity availability unknown -- not supplied", ConstraintSeverity.MEDIUM)
    if not business_context["operational_capacity_available"]:
        return ConstraintCheck("operational_capacity", ConstraintStatus.BLOCKED,
                                "no operational capacity available for this action", ConstraintSeverity.HIGH)
    utilization = business_context.get("operational_capacity_utilization_pct")
    if isinstance(utilization, (int, float)):
        cfg = thresholds.get("operational_capacity", {})
        if utilization >= cfg.get("blocked_utilization_pct", 100):
            return ConstraintCheck("operational_capacity", ConstraintStatus.BLOCKED,
                                    f"utilization ({utilization}%) is at or above the blocked threshold",
                                    ConstraintSeverity.HIGH)
        if utilization >= cfg.get("warning_utilization_pct", 85):
            return ConstraintCheck("operational_capacity", ConstraintStatus.WARNING,
                                    f"utilization ({utilization}%) is above the warning threshold",
                                    ConstraintSeverity.MEDIUM)
    return ConstraintCheck("operational_capacity", ConstraintStatus.PASS, "operational capacity available",
                            ConstraintSeverity.LOW)


def _check_inventory(business_context: dict[str, Any], thresholds: dict[str, Any]) -> ConstraintCheck:
    units = business_context.get("inventory_units_available")
    if units is None:
        return ConstraintCheck("inventory", ConstraintStatus.WARNING, "inventory availability unknown -- not supplied",
                                ConstraintSeverity.MEDIUM)
    cfg = thresholds.get("inventory", {})
    if units <= cfg.get("blocked_below_units", 0):
        return ConstraintCheck("inventory", ConstraintStatus.BLOCKED,
                                f"inventory ({units} units) is at or below the blocked threshold", ConstraintSeverity.HIGH)
    if units < cfg.get("warning_below_units", 100):
        return ConstraintCheck("inventory", ConstraintStatus.WARNING,
                                f"inventory ({units} units) is below the warning threshold", ConstraintSeverity.MEDIUM)
    return ConstraintCheck("inventory", ConstraintStatus.PASS, "sufficient inventory available", ConstraintSeverity.LOW)


def _check_geography(business_context: dict[str, Any], thresholds: dict[str, Any]) -> ConstraintCheck:
    coverage = business_context.get("geography_coverage")
    if coverage is None:
        cfg = thresholds.get("geography", {})
        if cfg.get("blocked_if_coverage_missing", True):
            return ConstraintCheck("geography", ConstraintStatus.WARNING,
                                    "geography coverage unknown -- not supplied", ConstraintSeverity.MEDIUM)
        return ConstraintCheck("geography", ConstraintStatus.PASS, "geography coverage not required",
                                ConstraintSeverity.LOW)
    if coverage is False:
        return ConstraintCheck("geography", ConstraintStatus.BLOCKED,
                                "action's target segment is outside available geography coverage",
                                ConstraintSeverity.HIGH)
    return ConstraintCheck("geography", ConstraintStatus.PASS, "geography coverage confirmed", ConstraintSeverity.LOW)


def _check_decision_rights(business_context: dict[str, Any], thresholds: dict[str, Any], owner: str) -> ConstraintCheck:
    allowlist = business_context.get("authorized_owner_roles")
    if allowlist is None:
        return ConstraintCheck("decision_rights", ConstraintStatus.WARNING,
                                "authorized owner roles unknown -- not supplied", ConstraintSeverity.MEDIUM)
    if owner not in allowlist:
        cfg = thresholds.get("decision_rights", {})
        if cfg.get("blocked_if_owner_role_not_in_allowlist", True):
            return ConstraintCheck("decision_rights", ConstraintStatus.BLOCKED,
                                    f"owner {owner!r} is not in the authorized decision-rights allowlist",
                                    ConstraintSeverity.CRITICAL)
        return ConstraintCheck("decision_rights", ConstraintStatus.WARNING,
                                f"owner {owner!r} is not explicitly authorized", ConstraintSeverity.MEDIUM)
    return ConstraintCheck("decision_rights", ConstraintStatus.PASS, f"owner {owner!r} is authorized",
                            ConstraintSeverity.LOW)


_CHECKERS = {
    "budget": lambda ctx, thresholds, owner: _check_budget(ctx, thresholds),
    "operational_capacity": lambda ctx, thresholds, owner: _check_operational_capacity(ctx, thresholds),
    "inventory": lambda ctx, thresholds, owner: _check_inventory(ctx, thresholds),
    "geography": lambda ctx, thresholds, owner: _check_geography(ctx, thresholds),
    "decision_rights": lambda ctx, thresholds, owner: _check_decision_rights(ctx, thresholds, owner),
}


def evaluate_constraints(relevant_constraints: list[str], business_context: dict[str, Any], owner: str,
                          scoring_config: DecisionScoringConfig) -> list[ConstraintCheck]:
    """Runs only the checks named in relevant_constraints (from the
    ontology's action_type entry), in the fixed _CONSTRAINT_ORDER --
    deterministic regardless of the order relevant_constraints was declared
    in."""
    thresholds = scoring_config.constraint_thresholds
    wanted = set(relevant_constraints)
    return [
        _CHECKERS[name](business_context, thresholds, owner)
        for name in _CONSTRAINT_ORDER
        if name in wanted
    ]
