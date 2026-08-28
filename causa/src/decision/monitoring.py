"""
monitoring.py — Step 7: builds a monitoring plan for an executable
ActionRecommendation.

Answers "how do we know whether the action worked?" No LLM, no fabricated
targets: target stays the literal sentinel "unknown" unless a real baseline+
effect combination is computable; warning_threshold stays None unless a real
expected_effect exists to derive a fraction of.
"""

from __future__ import annotations

from typing import Any, Optional

from decision.models import ExpectedImpact, MonitoringTarget
from decision.ontology import DecisionScoringConfig

# KPI-semantics fact (which direction is "improvement" for a given KPI),
# not a business policy -- small enough to hardcode as a constant, same
# posture as decision_ontology.yaml's driver->category mapping being config
# while this stays code. Movable to config if the KPI list grows.
_KPI_DIRECTION: dict[str, str] = {
    "on_time_delivery_rate": "increase",
    "avg_delivery_days": "decrease",
    "freight_ratio": "decrease",
    "aov": "increase",
    "revenue": "increase",
}

_WARNING_THRESHOLD_FRACTION = 0.5  # a monitored KPI moving less than half of its expected_effect after
                                    # `window` triggers a warning -- config-movable, documented here.


def build_monitoring_plan(monitoring_kpis: list[str], expected_impact: ExpectedImpact,
                           scoring_config: DecisionScoringConfig) -> list[MonitoringTarget]:
    window = scoring_config.default_monitoring_window()
    targets: list[MonitoringTarget] = []
    for kpi in monitoring_kpis:
        direction = _KPI_DIRECTION.get(kpi, "unknown")
        expected_effect: Optional[float] = expected_impact.estimated_effect if kpi == expected_impact.metric else None
        target = "unknown"
        warning_threshold: Optional[float] = None
        if expected_effect is not None:
            target = f"{direction} by approximately {expected_effect} within {window}"
            warning_threshold = expected_effect * _WARNING_THRESHOLD_FRACTION
        targets.append(MonitoringTarget(
            kpi=kpi, direction=direction, expected_effect=expected_effect, target=target, window=window,
            warning_threshold=warning_threshold,
            stop_condition=f"no measurable improvement in {kpi} after {window}",
        ))
    return targets
