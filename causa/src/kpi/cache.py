"""
cache.py — deterministic computation cache for the KPI engine.

This is NOT an LLM cache, NOT a semantic cache, and NOT time-based (no TTL). It
exists purely so that computing the same KPI request twice does not re-read and
re-aggregate the canonical Parquet tables twice. The cache key is a pure function
of the request's meaning -- same kpi_id + date range + dimensions + filters +
variant + window-override + clearance always produces the same key, and a
different key is produced whenever any of those change.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from kpi.models import KPIRequest


def make_cache_key(request: KPIRequest) -> str:
    """hash(kpi_id + date_range + dimensions + filters + variant [+ window
    override + clearance]), per this task's spec. Filters/dimensions are
    canonicalized (sorted) so key order in the request dict never changes the
    hash -- the key is a function of MEANING, not of how the caller wrote it."""
    payload = {
        "kpi_id": request.kpi_id,
        "start_date": request.start_date,
        "end_date": request.end_date,
        "dimensions": sorted(request.dimensions),
        "filters": {k: request.filters[k] for k in sorted(request.filters)},
        "variant": request.variant,
        "override_analytical_window": request.override_analytical_window,
        "requester_clearance": request.requester_clearance,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ComputationCache:
    """A simple in-memory, process-local cache. No persistence, no TTL, no
    invalidation policy beyond `clear()` -- if the underlying canonical Parquet
    files change, the caller is responsible for constructing a fresh cache (or
    calling clear()), since this module has no way to detect that on its own."""

    def __init__(self):
        self._store: dict[str, Any] = {}
        self.hits = 0
        self.misses = 0

    def get_or_compute(self, request: KPIRequest, compute_fn: Callable[[], Any]) -> Any:
        key = make_cache_key(request)
        if key in self._store:
            self.hits += 1
            return self._store[key]
        self.misses += 1
        value = compute_fn()
        self._store[key] = value
        return value

    def get(self, request: KPIRequest) -> Any | None:
        return self._store.get(make_cache_key(request))

    def contains(self, request: KPIRequest) -> bool:
        return make_cache_key(request) in self._store

    def clear(self) -> None:
        self._store.clear()
        self.hits = 0
        self.misses = 0

    def stats(self) -> dict[str, int]:
        return {"entries": len(self._store), "hits": self.hits, "misses": self.misses}
