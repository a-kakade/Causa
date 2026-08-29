"""
kpi_support.py — small shared helpers for building real AnomalyRequest
baseline histories from live KPIEngine calls. Mirrors
src/evidence/engine.py::_build_anomaly_evidence's pattern exactly (12 months
of real monthly KPIEngine.compute() calls feeding a global BaselineLevel) --
not a new computation, just the same construction reused for API callers
that need an AnomalyResult without going through the Step 4 evidence
package.
"""

from __future__ import annotations

from calendar import monthrange
from typing import Any

BASELINE_HISTORY_MONTHS = (
    "2017-01", "2017-02", "2017-03", "2017-04", "2017-05", "2017-06",
    "2017-07", "2017-08", "2017-09", "2017-10",
)


def month_bounds(month: str) -> tuple[str, str]:
    year, mon = (int(x) for x in month.split("-"))
    return f"{month}-01", f"{month}-{monthrange(year, mon)[1]:02d}"


def build_anomaly_result(kpi_engine: Any, registry: Any, kpi_id: str, period_label: str,
                          period_start: str, period_end: str, history_months: tuple = BASELINE_HISTORY_MONTHS):
    from anomaly import engine as anomaly_engine
    from anomaly.models import AnomalyRequest, BaselineLevel, PeriodObservation
    from kpi.models import KPIRequest

    history = []
    for month in history_months:
        start, end = month_bounds(month)
        r = kpi_engine.compute(KPIRequest(kpi_id=kpi_id, start_date=start, end_date=end))
        if isinstance(r, list):
            continue
        history.append(PeriodObservation(period=month, value=r.value, sample_size=r.sample_size, coverage=r.coverage))

    observed = kpi_engine.compute(KPIRequest(kpi_id=kpi_id, start_date=period_start, end_date=period_end))
    if isinstance(observed, list):
        raise ValueError(f"{kpi_id} resolved to a dimension-grouped result -- anomaly detection needs a single value.")

    request = AnomalyRequest(
        kpi_id=kpi_id, period=period_label, observed_value=observed.value,
        observed_sample_size=observed.sample_size, observed_coverage=observed.coverage,
        levels=[BaselineLevel(level="global", label=f"all_{kpi_id}", history=history)],
    )
    return anomaly_engine.detect(registry, request), observed
