"""
bootstrap.py — builds the one shared, read-only engine bundle every request
handler reads from. Same construction sequence
scripts/step5_investigate_november_2017.py already uses (SemanticRegistry ->
KPIEngine -> ToolContext), reused here rather than re-derived, and built
exactly once at process startup (not per-request) since it costs real time
(parquet loads + the Step 4 evidence/review index build).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT / "src", REPO_ROOT / "scripts"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

CANONICAL_TABLES = [
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
]


@dataclass
class EngineBundle:
    registry: "object"
    kpi_engine: "object"
    ctx: "object"          # tools.context.ToolContext -- built once, shared read-only
    canonical: dict
    build_seconds: float


_bundle: Optional[EngineBundle] = None


def get_bundle() -> EngineBundle:
    """Builds the bundle lazily on first call, caches it for the process
    lifetime. Not thread-safe against concurrent first-calls -- acceptable
    for a single-process prototype server (uvicorn --workers 1)."""
    global _bundle
    if _bundle is not None:
        return _bundle

    import pandas as pd
    from kpi.engine import KPIEngine
    from kpi.semantic_registry import SemanticRegistry
    from tools.context import build_tool_context

    t0 = time.time()
    canonical = {t: pd.read_parquet(REPO_ROOT / "data" / "processed" / f"{t}.parquet") for t in CANONICAL_TABLES}
    registry = SemanticRegistry.load()
    registry.validate()
    kpi_engine = KPIEngine(registry=registry)
    ctx = build_tool_context(canonical, kpi_engine, registry)
    build_seconds = round(time.time() - t0, 2)

    _bundle = EngineBundle(
        registry=registry, kpi_engine=kpi_engine, ctx=ctx, canonical=canonical, build_seconds=build_seconds,
    )
    return _bundle


def is_ready() -> bool:
    return _bundle is not None
