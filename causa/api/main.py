"""
main.py — the FastAPI application entry point.

Run with:  cd causa && uvicorn api.main:app --reload --port 8000
"""

from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import bootstrap
from api.config import settings
from api.errors import register_exception_handlers


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build the engine bundle once at startup rather than lazily on first
    # request, so /api/health can truthfully report readiness and the first
    # real request isn't the one paying the ~parquet-load-plus-evidence-index
    # cost.
    bootstrap.get_bundle()
    yield


app = FastAPI(title="Causa API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

register_exception_handlers(app)

from api.routes import (  # noqa: E402
    audit, causal, decisions, drivers, evidence, feedback, health, investigations, kpis, overview, security, story,
    telemetry,
)

for router_module in (health, overview, kpis, drivers, investigations, evidence, causal, decisions, story,
                      feedback, audit, security, telemetry):
    app.include_router(router_module.router)
