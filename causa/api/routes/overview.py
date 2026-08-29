"""
routes/overview.py — GET /api/overview.

The one genuinely new aggregation endpoint: no single Step 1-9 function
returns "every tracked KPI's movement + the headline anomaly verdict +
driver decomposition" in one call, so this route composes three real engine
calls (KPIEngine.compare_periods, anomaly.engine.detect, drivers.engine.decompose)
and returns their outputs untouched -- it does not compute a new number.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from api.bootstrap import EngineBundle
from api.dependencies import get_engine_bundle, get_requester_clearance
from api.kpi_support import build_anomaly_result
from api.routes.kpis import TRACKED_KPI_IDS, _range_bounds
from api.serializers import (
    anomaly_result_dict, comparison_result_dict, driver_decomposition_dict,
)

router = APIRouter(prefix="/api/overview", tags=["overview"])

DEFAULT_CURRENT = "2017-11"
DEFAULT_PREVIOUS = "2017-10"
HEADLINE_KPI = "revenue"


@router.get("")
def get_overview(
    period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    start_period: str | None = Query(default=None), end_period: str | None = Query(default=None),
    previous_start_period: str | None = Query(default=None), previous_end_period: str | None = Query(default=None),
    bundle: EngineBundle = Depends(get_engine_bundle),
    requester_clearance: str = Depends(get_requester_clearance),
):
    cur_start, cur_end = _range_bounds(start_period or period, end_period or period)
    prev_start, prev_end = _range_bounds(previous_start_period or previous_period, previous_end_period or previous_period)

    movements = []
    for kpi_id in TRACKED_KPI_IDS:
        if kpi_id not in bundle.registry.list_kpi_ids():
            continue
        cmp = bundle.kpi_engine.compare_periods(kpi_id, cur_start, cur_end, prev_start, prev_end)
        movements.append(comparison_result_dict(cmp))

    anomaly_result, _observed = build_anomaly_result(
        bundle.kpi_engine, bundle.registry, HEADLINE_KPI, period, cur_start, cur_end,
    )

    driver_result = None
    driver_error = None
    try:
        from drivers.engine import decompose
        from drivers.models import DriverDecompositionRequest

        driver_result = driver_decomposition_dict(decompose(bundle.kpi_engine, bundle.registry, DriverDecompositionRequest(
            kpi_id=HEADLINE_KPI,
            period_current_start=cur_start, period_current_end=cur_end, period_current_label=period,
            period_previous_start=prev_start, period_previous_end=prev_end, period_previous_label=previous_period,
            override_analytical_window=True, requester_clearance=requester_clearance,
        )))
    except Exception as exc:  # noqa: BLE001 -- overview must never 500 over one optional panel
        driver_error = str(exc)

    return {
        "period": period, "previous_period": previous_period,
        "kpi_movements": movements,
        "headline_kpi": HEADLINE_KPI,
        "headline_anomaly": anomaly_result_dict(anomaly_result),
        "driver_decomposition": driver_result,
        "driver_decomposition_error": driver_error,
        "requester_clearance": requester_clearance,
        "freshness": {
            "canonical_data": "data/processed/*.parquet (Step 2 canonical build)",
            "note": "Every number above is computed live from real Olist canonical data on this request; "
                    "nothing here is cached beyond the process-lifetime engine bundle.",
        },
    }
