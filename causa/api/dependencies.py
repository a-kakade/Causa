"""
dependencies.py — FastAPI dependency functions.

RBAC posture (SECURITY_ARCHITECTURE.md has the full writeup): the browser
sends a ROLE NAME only (?requester_role= or X-Causa-Role header) -- never a
clearance. This module is the only place that maps that role name to an
actual SecurityClassification, via the exact tools.policy tables the Step 5
engine already uses. No parallel policy is ever defined here.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query, Request

from api.bootstrap import EngineBundle, get_bundle
from api.store import InvestigationStore, get_store


def get_engine_bundle() -> EngineBundle:
    return get_bundle()


def get_investigation_store() -> InvestigationStore:
    return get_store()


def get_requester_role(
    request: Request,
    requester_role: str = Query(default="ANALYST"),
    x_causa_role: str | None = Header(default=None, alias="X-Causa-Role"),
) -> str:
    from agents.models import RequesterRole

    role_name = (x_causa_role or requester_role or "ANALYST").upper()
    try:
        role = RequesterRole(role_name)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown requester_role {role_name!r}. "
                                                      f"Must be one of {[r.value for r in RequesterRole]}.")
    request.state.requester_role = role
    return role.value


def get_requester_clearance(request: Request, requester_role: str = Depends(get_requester_role)) -> str:
    """FastAPI resolves get_requester_role first (a sub-dependency of this
    function), so every route that depends on get_requester_clearance
    transitively also gets request.state.requester_role set."""
    from agents.models import RequesterRole
    from tools import policy

    role = RequesterRole(requester_role)
    clearance = policy.clearance_for_role(role)
    request.state.requester_clearance = clearance
    return clearance
