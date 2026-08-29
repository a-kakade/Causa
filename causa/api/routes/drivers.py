"""
routes/drivers.py — GET /api/kpis/{kpi_id}/drivers, /pvm, /segments.

Clearance is always derived server-side (get_requester_clearance) and passed
straight into drivers.engine.decompose's own requester_clearance parameter --
the engine itself raises UnauthorizedSegmentError/UnsupportedSegmentError,
translated to 403/400 by api/errors.py. No parallel authorization logic here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.bootstrap import EngineBundle
from api.dependencies import get_engine_bundle, get_requester_clearance
from api.routes.kpis import _month_bounds
from api.serializers import driver_decomposition_dict

router = APIRouter(prefix="/api/kpis", tags=["drivers"])

DEFAULT_CURRENT = "2017-11"
DEFAULT_PREVIOUS = "2017-10"


def _decompose(bundle: EngineBundle, kpi_id: str, period: str, previous_period: str,
               requester_clearance: str, segment_dimensions: Optional[list[str]] = None):
    from drivers.engine import decompose
    from drivers.models import DriverDecompositionRequest

    cur_start, cur_end = _month_bounds(period)
    prev_start, prev_end = _month_bounds(previous_period)
    request = DriverDecompositionRequest(
        kpi_id=kpi_id,
        period_current_start=cur_start, period_current_end=cur_end, period_current_label=period,
        period_previous_start=prev_start, period_previous_end=prev_end, period_previous_label=previous_period,
        override_analytical_window=True, requester_clearance=requester_clearance,
        segment_dimensions=segment_dimensions,
    )
    return decompose(bundle.kpi_engine, bundle.registry, request)


@router.get("/{kpi_id}/drivers")
def get_driver_decomposition(
    kpi_id: str, period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    segments: Optional[str] = Query(default=None, description="comma-separated segment dimensions"),
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    seg_list = [s.strip() for s in segments.split(",")] if segments else None
    result = _decompose(bundle, kpi_id, period, previous_period, requester_clearance, seg_list)
    return driver_decomposition_dict(result)


@router.get("/{kpi_id}/pvm")
def get_pvm(
    kpi_id: str, period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    result = _decompose(bundle, kpi_id, period, previous_period, requester_clearance, segment_dimensions=[])
    d = driver_decomposition_dict(result)
    return {"kpi_id": d["kpi_id"], "period_current": d["period_current"], "period_previous": d["period_previous"],
            "total_change": d["total_change"], "drivers": d["drivers"], "reconciliation": d["reconciliation"]}


@router.get("/{kpi_id}/segments")
def get_segments(
    kpi_id: str, period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    dimension: Optional[str] = Query(default=None),
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    seg_list = [dimension] if dimension else None
    result = _decompose(bundle, kpi_id, period, previous_period, requester_clearance, seg_list)
    d = driver_decomposition_dict(result)
    return {"kpi_id": d["kpi_id"], "period_current": d["period_current"], "period_previous": d["period_previous"],
            "segment_contributions": d["segment_contributions"]}


@router.get("/{kpi_id}/concurrent")
def get_concurrent_kpis(
    kpi_id: str, period: str = Query(default=DEFAULT_CURRENT), previous_period: str = Query(default=DEFAULT_PREVIOUS),
    bundle: EngineBundle = Depends(get_engine_bundle), requester_clearance: str = Depends(get_requester_clearance),
):
    result = _decompose(bundle, kpi_id, period, previous_period, requester_clearance, segment_dimensions=[])
    d = driver_decomposition_dict(result)
    return {"kpi_id": d["kpi_id"], "concurrent_kpis": d["concurrent_kpis"]}
