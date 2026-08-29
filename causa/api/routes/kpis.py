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


def _range_bounds(start_month: str, end_month: str) -> tuple[str, str]:
    """Expands a start/end month pair (inclusive, 'YYYY-MM') into a full
    date range: first day of start_month through last day of end_month.
    A single month (start_month == end_month) reduces to the old
    _month_bounds behavior."""
    from calendar import monthrange
    end_year, end_mon = (int(x) for x in end_month.split("-"))
    return f"{start_month}-01", f"{end_month}-{monthrange(end_year, end_mon)[1]:02d}"


def _month_bounds(month: str) -> tuple[str, str]:
    return _range_bounds(month, month)


@router.get("")
def list_kpi_movements(
    period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    start_period: str | None = Query(default=None), end_period: str | None = Query(default=None),
    previous_start_period: str | None = Query(default=None), previous_end_period: str | None = Query(default=None),
    bundle: EngineBundle = Depends(get_engine_bundle),
):
    cur_start, cur_end = _range_bounds(start_period or period, end_period or period)
    prev_start, prev_end = _range_bounds(previous_start_period or previous_period, previous_end_period or previous_period)
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
    start_period: str | None = Query(default=None), end_period: str | None = Query(default=None),
    previous_start_period: str | None = Query(default=None), previous_end_period: str | None = Query(default=None),
    bundle: EngineBundle = Depends(get_engine_bundle),
):
    if kpi_id not in bundle.registry.list_kpi_ids():
        raise HTTPException(status_code=404, detail=f"Unknown kpi_id {kpi_id!r}")
    cur_start, cur_end = _range_bounds(start_period or period, end_period or period)
    prev_start, prev_end = _range_bounds(previous_start_period or previous_period, previous_end_period or previous_period)
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
        # kpi_result_dict(result) carries its own "period" key (a
        # {start, end} date-range object) -- put the simple 'YYYY-MM' month
        # label AFTER the spread so it wins, instead of being silently
        # shadowed by the result's own period object (which previously left
        # every point's "period" as {start, end} instead of the month
        # string every caller keys its chart data by).
        points.append({**kpi_result_dict(result), "period": month})
    return {"kpi_id": kpi_id, "points": points}
