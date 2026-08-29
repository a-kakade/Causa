"""
routes/kpis.py — GET /api/kpis, /api/kpis/{kpi_id}, /api/kpis/{kpi_id}/timeseries.

Every number here traces to kpi.engine.KPIEngine.compute()/compare_periods()
-- no hardcoded business values.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.bootstrap import EngineBundle
from api.dependencies import get_engine_bundle
from api.serializers import comparison_result_dict, kpi_result_dict

router = APIRouter(prefix="/api/kpis", tags=["kpis"])

DEFAULT_CURRENT = "2017-11"
DEFAULT_PREVIOUS = "2017-10"
TRACKED_KPI_IDS = ("revenue", "orders", "aov", "freight_revenue", "avg_delivery_days",
                    "on_time_delivery_rate", "avg_review_score", "review_volume", "repeat_purchase_rate")


def _month_bounds(month: str) -> tuple[str, str]:
    from calendar import monthrange
    year, mon = (int(x) for x in month.split("-"))
    return f"{month}-01", f"{month}-{monthrange(year, mon)[1]:02d}"


@router.get("")
def list_kpi_movements(
    period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    bundle: EngineBundle = Depends(get_engine_bundle),
):
    cur_start, cur_end = _month_bounds(period)
    prev_start, prev_end = _month_bounds(previous_period)
    out = []
    for kpi_id in TRACKED_KPI_IDS:
        if kpi_id not in bundle.registry.list_kpi_ids():
            continue
        cmp = bundle.kpi_engine.compare_periods(kpi_id, cur_start, cur_end, prev_start, prev_end)
        out.append(comparison_result_dict(cmp))
    return {"period": period, "previous_period": previous_period, "movements": out}


@router.get("/{kpi_id}")
def get_kpi_movement(
    kpi_id: str, period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    bundle: EngineBundle = Depends(get_engine_bundle),
):
    if kpi_id not in bundle.registry.list_kpi_ids():
        raise HTTPException(status_code=404, detail=f"Unknown kpi_id {kpi_id!r}")
    cur_start, cur_end = _month_bounds(period)
    prev_start, prev_end = _month_bounds(previous_period)
    cmp = bundle.kpi_engine.compare_periods(kpi_id, cur_start, cur_end, prev_start, prev_end)
    return comparison_result_dict(cmp)


@router.get("/{kpi_id}/timeseries")
def get_kpi_timeseries(
    kpi_id: str, months: str = Query(default="2017-01,2017-02,2017-03,2017-04,2017-05,2017-06,"
                                              "2017-07,2017-08,2017-09,2017-10,2017-11,2017-12"),
    bundle: EngineBundle = Depends(get_engine_bundle),
):
    if kpi_id not in bundle.registry.list_kpi_ids():
        raise HTTPException(status_code=404, detail=f"Unknown kpi_id {kpi_id!r}")
    from kpi.models import KPIRequest

    points = []
    for month in [m.strip() for m in months.split(",") if m.strip()]:
        start, end = _month_bounds(month)
        result = bundle.kpi_engine.compute(KPIRequest(kpi_id=kpi_id, start_date=start, end_date=end))
        if isinstance(result, list):
            continue
        points.append({"period": month, **kpi_result_dict(result)})
    return {"kpi_id": kpi_id, "points": points}
