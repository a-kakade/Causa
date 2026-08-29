"""
routes/telemetry.py — GET /api/telemetry, /api/investigations/{id}/telemetry.

Returns exactly what agents.telemetry.aggregate() produces -- missing values
are null with telemetry_available=False, never fabricated as 0.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_investigation_store
from api.store import InvestigationStore

router = APIRouter(tags=["telemetry"])


@router.get("/api/telemetry")
def get_global_telemetry(store: InvestigationStore = Depends(get_investigation_store)):
    from agents.telemetry import aggregate

    records = store.list()
    if not records:
        return {"telemetry_available": False, "investigations": 0}
    aggregates = [aggregate(r.state) for r in records]
    total_calls = sum(a["total_llm_calls"] for a in aggregates)
    total_det = sum(a["total_deterministic_calls"] for a in aggregates)
    total_tokens = sum(a["total_tokens"] for a in aggregates)
    total_cost = round(sum(a["total_estimated_cost"] for a in aggregates), 6)
    total_tool_calls = sum(a["total_tool_calls"] for a in aggregates)
    return {
        "telemetry_available": True, "investigations": len(records),
        "total_llm_calls": total_calls, "total_deterministic_calls": total_det,
        "total_tokens": total_tokens, "total_estimated_cost": total_cost, "total_tool_calls": total_tool_calls,
        "by_investigation": [
            {"investigation_id": r.investigation_id, "source": r.source, **aggregate(r.state)} for r in records
        ],
    }


@router.get("/api/investigations/{investigation_id}/telemetry")
def get_investigation_telemetry(investigation_id: str, store: InvestigationStore = Depends(get_investigation_store)):
    from agents.telemetry import aggregate

    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    if not record.state.telemetry:
        return {"investigation_id": investigation_id, "telemetry_available": False, "reason": "no telemetry records "
                "were captured for this run (e.g. a replayed investigation whose original report predates this "
                "field, or a run with zero LLM/deterministic-agent calls recorded)"}
    return {"investigation_id": investigation_id, "telemetry_available": True, **aggregate(record.state)}
