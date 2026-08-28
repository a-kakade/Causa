"""
impact_estimator.py — Step 7: computes ExpectedImpact from a DriverSignal.

Pure arithmetic, no LLM, no fabrication (task's own non-negotiable rule for
this module): every number here traces directly to a DriverSignal field a
caller (or src/decision/bridge.py) actually supplied. Any missing required
input results in an explicit is_estimable=False + "UNKNOWN"-labeled source,
never a zero, never an interpolated guess.

    expected_impact = estimated_effect * addressable_population * confidence

revenue_impact is only computed when a monetary per-unit value is present in
DriverSignal.business_context (e.g. "avg_order_value") -- never guessed.
"""

from __future__ import annotations

from typing import Any, Optional

from decision.models import DataSource, ExpectedImpact

# Which KPI each supported driver's impact is naturally expressed against,
# and its unit -- a small, fixed lookup of KPI SEMANTICS (not a business
# policy), same posture as monitoring.py's _KPI_DIRECTION table.
_DRIVER_METRIC_UNIT: dict[str, tuple[str, str]] = {
    "delivery_delay": ("on_time_delivery_rate", "pp"),
    "aov_decline": ("aov", "currency"),
}


def _metric_and_unit(driver: str, kpi_id: str) -> tuple[str, str]:
    if driver in _DRIVER_METRIC_UNIT:
        return _DRIVER_METRIC_UNIT[driver]
    return kpi_id, "unknown"


def estimate_impact(driver_signal: Any) -> ExpectedImpact:
    metric, unit = _metric_and_unit(driver_signal.driver, driver_signal.kpi_id)

    effect = driver_signal.historical_estimated_effect
    population = driver_signal.addressable_population
    confidence = driver_signal.driver_confidence

    missing = [name for name, value in (("historical_estimated_effect", effect),
                                         ("addressable_population", population),
                                         ("driver_confidence", confidence)) if value is None]
    if missing:
        return ExpectedImpact(
            metric=metric, estimated_effect=effect, effect_unit=unit, addressable_population=population,
            confidence=confidence, calculated_impact=None, revenue_impact=None,
            effect_source=driver_signal.historical_effect_source if effect is not None else DataSource.UNKNOWN.value,
            population_source=driver_signal.addressable_population_source if population is not None else DataSource.UNKNOWN.value,
            confidence_basis=f"not computable -- missing: {', '.join(missing)}",
            is_estimable=False,
        )

    calculated_impact = effect * population * confidence

    revenue_impact: Optional[float] = None
    avg_order_value = driver_signal.business_context.get("avg_order_value")
    if isinstance(avg_order_value, (int, float)) and unit != "currency":
        revenue_impact = calculated_impact * avg_order_value
    elif unit == "currency":
        revenue_impact = calculated_impact  # already denominated in currency (e.g. AOV impact)

    confidence_basis = (
        f"driver_confidence={confidence} sourced from DriverSignal (source={driver_signal.source})"
    )

    return ExpectedImpact(
        metric=metric, estimated_effect=effect, effect_unit=unit, addressable_population=population,
        confidence=confidence, calculated_impact=calculated_impact, revenue_impact=revenue_impact,
        effect_source=driver_signal.historical_effect_source,
        population_source=driver_signal.addressable_population_source,
        confidence_basis=confidence_basis, is_estimable=True,
    )
