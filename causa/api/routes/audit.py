"""
routes/audit.py — GET /api/audit and /api/investigations/{id}/audit.

Serializes ONLY the documented AuditTraceEntry fields (see api/serializers.py
audit_entry_dict's strict allowlist) -- never raw LLM prompt/response text,
never anything from state.telemetry beyond the already-allowlisted
telemetry_record_dict fields.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_investigation_store
from api.serializers import audit_entry_dict
from api.store import InvestigationStore

router = APIRouter(tags=["audit"])


@router.get("/api/audit")
def list_audit_entries(
    investigation_id: Optional[str] = Query(default=None), actor_role: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None), tool: Optional[str] = Query(default=None),
    store: InvestigationStore = Depends(get_investigation_store),
):
    records = store.list(role_filter=None)
    if investigation_id:
        records = [r for r in records if r.investigation_id == investigation_id]

    rows = []
    for record in records:
        for entry in record.state.audit_trace:
            d = audit_entry_dict(entry)
            d["investigation_id"] = record.investigation_id
            rows.append(d)

    if actor_role:
        rows = [r for r in rows if r.get("agent_role") == actor_role]
    if status:
        rows = [r for r in rows if r.get("security_decision") == status]
    if tool:
        rows = [r for r in rows if r.get("tool_call") == tool]

    rows.sort(key=lambda r: r.get("timestamp") or "", reverse=True)
    return {"count": len(rows), "entries": rows}


@router.get("/api/investigations/{investigation_id}/audit")
def get_investigation_audit(investigation_id: str, store: InvestigationStore = Depends(get_investigation_store)):
    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    return {
        "investigation_id": investigation_id,
        "audit_trace": [audit_entry_dict(a) for a in record.state.audit_trace],
        "security_events": list(record.state.security_events),
    }
