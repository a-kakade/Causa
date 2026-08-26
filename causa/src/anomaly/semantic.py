"""
semantic.py — Step 3C: reads config/kpis.yaml's `materiality` and `aggregation`
fields into the shapes this engine's other modules need.

This is the ONLY place in src/anomaly/ that reads a KPI contract field name
directly -- exactly the discipline docs/KPI_COMPUTATION_ENGINE.md describes for
kpi.engine.py: every constant that determines correctness is read from the
contract at runtime, not copy-pasted. `config/kpis.yaml`'s `materiality` block
was declared in Step 3A with `implemented: false` specifically because no
anomaly engine existed yet (see docs/KPI_SEMANTIC_LAYER.md §5) -- this module
is that engine's one entry point into those thresholds. It does not change
their values or their meaning; it turns the YAML into a typed
`MaterialityConfig`, and combines the `data_quality_requirements.
coverage_threshold_pct` field (already used by kpi.engine.py's HIGH/MEDIUM/LOW
tiering) into the same object so the anomaly engine's data-quality gate stays
consistent with the KPI engine's own tiering, rather than inventing a second,
divergent coverage rule.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

ADDITIVE_AGGREGATIONS = {"SUM", "COUNT", "COUNT_DISTINCT"}
RATE_OR_AVERAGE_AGGREGATIONS = {"RATIO", "DERIVED_RATIO", "MEAN"}


@dataclass
class MaterialityConfig:
    absolute_threshold: Optional[float]
    relative_threshold: Optional[float]
    statistical_threshold: Optional[float]
    minimum_observations: Optional[int]
    minimum_business_impact: Optional[float]
    persistence_periods: int
    coverage_threshold_pct: Optional[float]


def materiality_config_for(contract: dict[str, Any]) -> MaterialityConfig:
    m = contract["materiality"]
    dq = contract.get("data_quality_requirements", {})
    return MaterialityConfig(
        absolute_threshold=m.get("absolute_threshold"),
        relative_threshold=m.get("relative_threshold"),
        statistical_threshold=m.get("statistical_threshold"),
        minimum_observations=m.get("minimum_observations"),
        minimum_business_impact=m.get("minimum_business_impact"),
        persistence_periods=m.get("persistence_periods") or 2,
        coverage_threshold_pct=dq.get("coverage_threshold_pct"),
    )


def kpi_kind_for(contract: dict[str, Any]) -> str:
    """"additive" for SUM/COUNT/COUNT_DISTINCT KPIs (a monetary or unit total --
    Revenue, Orders, Freight Revenue, Quantity Sold, Review Volume), else
    "rate_or_average" (AOV, Average Delivery Days, Average Review Score,
    On-Time Delivery Rate, Repeat Purchase Rate) -- task §5's distinction
    between an additive impact and a ratio/rate that must never be presented as
    a monetary figure."""
    aggregation = contract["aggregation"]
    if aggregation in ADDITIVE_AGGREGATIONS:
        return "additive"
    if aggregation in RATE_OR_AVERAGE_AGGREGATIONS:
        return "rate_or_average"
    raise ValueError(f"Unrecognized aggregation type {aggregation!r} -- cannot classify business-impact kind.")
