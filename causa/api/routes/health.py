from __future__ import annotations

from fastapi import APIRouter

from api import bootstrap

router = APIRouter(tags=["health"])


@router.get("/api/health")
def health():
    return {
        "status": "ok" if bootstrap.is_ready() else "starting",
        "engine_bundle_ready": bootstrap.is_ready(),
    }
