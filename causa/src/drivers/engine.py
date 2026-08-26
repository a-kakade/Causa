"""
engine.py — Step 3D: driver decomposition orchestrator.

    DriverDecompositionRequest
        │
        ▼
    SemanticRegistry.get("revenue")        -- dimension validity + clearance (§14)
        │
        ▼
    CanonicalDataStore (reused from kpi.engine, read-only)         -- load + filter
        │                                                             item-grain rows
        ├─→ pvm.compute_pvm_bridge()                        -- §1/§2 (Volume/Price/Mix)
        ├─→ contribution.compute_segment_contributions()     -- §4/5/6, per requested dimension
        └─→ kpi.engine.KPIEngine.compare_periods()            -- §15/16 (Orders/AOV/Freight/...)
        │
        ▼
    reconciliation checks (§13) -- raises ReconciliationError on failure, never
    returns an apparently-valid but non-reconciling result
        │
        ▼
    DriverDecompositionResult (§17)

This module answers exactly one question: "which measurable factors
mathematically account for this KPI movement?" It never answers "why did it
happen" -- see docs/DRIVER_DECOMPOSITION.md §8 for the boundary this module
deliberately does not cross.

Stays decoupled from kpi.engine's private filtering helpers (same posture
src/anomaly/ took relative to kpi.engine in Step 3C) -- it reuses only
kpi.engine's PUBLIC surface (`CanonicalDataStore`, `KPIEngine`) and
reimplements the small amount of date/window/status filtering logic locally,
documented as mirroring the same discipline.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from drivers.contribution import MISSING_LABEL_BY_SEGMENT, compute_segment_contributions
from drivers.models import (
    ConcurrentKPIMovement, DataQualitySummary, DriverContribution, DriverDecompositionRequest,
    DriverDecompositionResult, EVIDENCE_DETERMINISTIC, METHOD_PVM, ReconciliationCheck, direction_of,
)
from drivers.pvm import CATEGORY_COL, UNCATEGORIZED_LABEL, compute_pvm_bridge
from drivers.ranking import rank_segment_contributions
from kpi.engine import CanonicalDataStore, KPIEngine
from kpi.semantic_registry import SemanticRegistry

SUPPORTED_SEGMENT_DIMENSIONS = ("product_category", "seller", "customer_state", "seller_state")
# maps a segment_type name to the column this module's item frames carry it under
_SEGMENT_COLUMN = {
    "product_category": CATEGORY_COL, "seller": "seller", "customer_state": "customer_state",
    "seller_state": "seller_state",
}
CONCURRENT_KPI_IDS = ("orders", "aov", "freight_revenue", "avg_delivery_days", "avg_review_score")
CLEARANCE_RANK = {"PUBLIC_ANALYTICAL": 0, "INTERNAL": 1, "RESTRICTED": 2}


class DriverRequestError(Exception):
    """Base class for every request-rejection reason this engine raises."""


class UnsupportedSegmentError(DriverRequestError):
    pass


class UnauthorizedSegmentError(DriverRequestError):
    pass


class ReconciliationError(Exception):
    """Raised when a decomposition's contributions do not sum back to the
    actual change within tolerance -- task §13: the engine MUST fail rather
    than return an apparently-valid, non-reconciling result."""


# ---------------------------------------------------------------------------
# Dimension safety (§14) -- reads the KPI semantic layer, never bypasses it
# ---------------------------------------------------------------------------

def _validate_segment(registry: SemanticRegistry, kpi_id: str, segment_type: str) -> dict[str, Any]:
    dim = registry.get_dimension(kpi_id, segment_type)
    if dim is None or not dim["supported"]:
        supported = [d["name"] for d in registry.get(kpi_id)["dimensions"] if d["supported"]]
        raise UnsupportedSegmentError(
            f"{segment_type!r} is not a supported dimension for {kpi_id!r} in its governed contract "
            f"(config/kpis.yaml). Supported: {supported}"
        )
    return dim


def _check_clearance(dim: dict[str, Any], segment_type: str, requester_clearance: str) -> None:
    required = CLEARANCE_RANK.get(dim["security_classification"], 0)
    have = CLEARANCE_RANK.get(requester_clearance, 0)
    if have < required:
        raise UnauthorizedSegmentError(
            f"segment {segment_type!r} requires clearance {dim['security_classification']!r}, "
            f"requester has {requester_clearance!r}"
        )


def _resolve_segment_dimensions(registry: SemanticRegistry, kpi_id: str, requested: Optional[list[str]],
                                 requester_clearance: str, warnings: list[str]) -> list[str]:
    """None -> every SUPPORTED_SEGMENT_DIMENSIONS this clearance can reach,
    silently omitting (with a logged warning) anything above clearance --
    a caller who didn't ask for "seller" by name shouldn't get a hard error
    just because they lack INTERNAL clearance. An EXPLICIT request for a
    segment above clearance is a hard error (UnauthorizedSegmentError) --
    task §5: "Do not expose seller identity to restricted personas without
    security clearance.\""""
    if requested is None:
        resolved = []
        for name in SUPPORTED_SEGMENT_DIMENSIONS:
            dim = _validate_segment(registry, kpi_id, name)
            required = CLEARANCE_RANK.get(dim["security_classification"], 0)
            have = CLEARANCE_RANK.get(requester_clearance, 0)
            if have < required:
                warnings.append(
                    f"segment '{name}' omitted -- requires clearance {dim['security_classification']!r}, "
                    f"requester has {requester_clearance!r}."
                )
                continue
            resolved.append(name)
        return resolved

    resolved = []
    for name in requested:
        dim = _validate_segment(registry, kpi_id, name)
        _check_clearance(dim, name, requester_clearance)
        resolved.append(name)
    return resolved


# ---------------------------------------------------------------------------
# Canonical data access -- mirrors kpi.engine's filtering discipline locally
# ---------------------------------------------------------------------------

def _load_period_items(data: CanonicalDataStore, start: str, end: str,
                        apply_window_filter: bool, order_status: Optional[str]) -> pd.DataFrame:
    """Item-grain rows for one period, with order context and
    category/seller/state labels already joined and NULL-normalized. Same
    date-range/window/status semantics as kpi.engine._compute_item_grain_sum
    (Revenue's own computation), reimplemented locally so src/drivers/ does
    not import kpi.engine's private helpers."""
    items = data.get("fact_order_items")[["order_id", "product_id", "seller_id", "price"]]
    orders = data.get("fact_orders")[["order_id", "purchase_timestamp", "order_status", "customer_state", "in_analytical_window"]]
    items = items.merge(orders, on="order_id", how="inner")

    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    items = items[(items["purchase_timestamp"] >= start_ts) & (items["purchase_timestamp"] < end_ts)]
    if apply_window_filter:
        items = items[items["in_analytical_window"]]
    if order_status is not None:
        items = items[items["order_status"] == order_status]

    dim_product = data.get("dim_product")[["product_id", "category_name_en"]]
    items = items.merge(dim_product, on="product_id", how="left")
    items[CATEGORY_COL] = items["category_name_en"].fillna(UNCATEGORIZED_LABEL)

    dim_seller = data.get("dim_seller")[["seller_id", "seller_state"]]
    items = items.merge(dim_seller, on="seller_id", how="left")
    items["seller_state"] = items["seller_state"].fillna(MISSING_LABEL_BY_SEGMENT["seller_state"])
    items["customer_state"] = items["customer_state"].fillna(MISSING_LABEL_BY_SEGMENT["customer_state"])
    items["seller"] = items["seller_id"].fillna(MISSING_LABEL_BY_SEGMENT["seller"])

    return items


def _coverage(data: CanonicalDataStore, items: pd.DataFrame, start: str, end: str,
              apply_window_filter: bool, order_status: Optional[str]) -> Optional[float]:
    orders = data.get("fact_orders")
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end) + pd.Timedelta(days=1)
    orders = orders[(orders["purchase_timestamp"] >= start_ts) & (orders["purchase_timestamp"] < end_ts)]
    if apply_window_filter:
        orders = orders[orders["in_analytical_window"]]
    if order_status is not None:
        orders = orders[orders["order_status"] == order_status]
    eligible = len(orders)
    if eligible == 0:
        return None
    contributing = items["order_id"].nunique()
    return contributing / eligible


def _history_periods_by_key(data: CanonicalDataStore, group_col: str, upto_end: str) -> dict[str, int]:
    """Distinct calendar months, across ALL available canonical history up to
    and including `upto_end`, in which each segment value had >=1 order-item
    row -- a real, deterministic "how established is this entity" signal
    (task §10), not a guess or a statistical estimate."""
    items = _load_period_items(data, "2016-01-01", upto_end, apply_window_filter=False, order_status=None)
    items["_month"] = items["purchase_timestamp"].dt.to_period("M").astype(str)
    counts = items.groupby(group_col)["_month"].nunique()
    return counts.to_dict()


# ---------------------------------------------------------------------------
# Reconciliation (§13)
# ---------------------------------------------------------------------------

def _reconcile(sum_of_contributions: float, actual_change: float, tolerance: float) -> ReconciliationCheck:
    error = sum_of_contributions - actual_change
    reconciled = abs(error) <= tolerance
    return ReconciliationCheck(
        sum_of_contributions=sum_of_contributions, actual_change=actual_change,
        error=error, tolerance=tolerance, reconciled=reconciled,
    )


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

def decompose(kpi_engine: KPIEngine, registry: SemanticRegistry,
              request: DriverDecompositionRequest) -> DriverDecompositionResult:
    if request.kpi_id != "revenue":
        raise DriverRequestError(
            f"PVM decomposition is implemented for 'revenue' only in this step (task §1's explicit scope), "
            f"got kpi_id={request.kpi_id!r}."
        )
    contract = registry.get(request.kpi_id)
    data = kpi_engine.data
    apply_window_filter = not request.override_analytical_window

    warnings: list[str] = []
    segment_dimensions = _resolve_segment_dimensions(
        registry, request.kpi_id, request.segment_dimensions, request.requester_clearance, warnings,
    )

    items_previous = _load_period_items(data, request.period_previous_start, request.period_previous_end,
                                         apply_window_filter, request.order_status)
    items_current = _load_period_items(data, request.period_current_start, request.period_current_end,
                                        apply_window_filter, request.order_status)

    # -- PVM (§1/§2) ----------------------------------------------------------
    bridge = compute_pvm_bridge(items_previous, items_current)
    delta_revenue = bridge.revenue_current - bridge.revenue_previous
    pct_change = None if bridge.revenue_previous == 0 else (delta_revenue / bridge.revenue_previous * 100)

    lineage = registry.get_lineage_chain(request.kpi_id)

    def _driver(name: str, value: float) -> DriverContribution:
        pct_of_change = None if delta_revenue == 0 else (value / abs(delta_revenue) * 100)
        return DriverContribution(
            driver=name, contribution_value=round(value, 2), contribution_pct_of_change=pct_of_change,
            direction=direction_of(value), method=METHOD_PVM,
            period_current=request.period_current_label, period_previous=request.period_previous_label,
            evidence_type=EVIDENCE_DETERMINISTIC, confidence=bridge.confidence, lineage=lineage,
        )

    drivers = [
        _driver("volume", bridge.volume_effect),
        _driver("price", bridge.price_effect),
        _driver("mix", bridge.mix_effect),
    ]

    pvm_sum = bridge.volume_effect + bridge.price_effect + bridge.mix_effect
    pvm_reconciliation = _reconcile(pvm_sum, delta_revenue, request.tolerance)
    if not pvm_reconciliation.reconciled:
        raise ReconciliationError(
            f"PVM decomposition does not reconcile: sum(volume+price+mix)={pvm_sum:.4f} vs "
            f"actual_change={delta_revenue:.4f} (error={pvm_reconciliation.error:.4f}, "
            f"tolerance={request.tolerance}). Refusing to return a non-reconciling decomposition (task §13)."
        )

    # -- Segment contributions (§4/5/6) ----------------------------------------
    segment_contributions: dict[str, list] = {}
    segment_reconciliation: dict[str, dict[str, Any]] = {}
    for segment_type in segment_dimensions:
        col = _SEGMENT_COLUMN[segment_type]
        history_by_key = _history_periods_by_key(data, col, request.period_previous_end)
        contributions = compute_segment_contributions(
            items_previous, items_current, col, segment_type, delta_revenue, history_by_key,
        )
        contributions = rank_segment_contributions(contributions)
        segment_contributions[segment_type] = contributions[:request.top_n] if request.top_n else contributions

        seg_sum = sum(c.absolute_change for c in contributions)  # reconcile over the FULL set, not just top_n
        seg_check = _reconcile(seg_sum, delta_revenue, request.tolerance)
        segment_reconciliation[segment_type] = seg_check.to_dict()
        if not seg_check.reconciled:
            raise ReconciliationError(
                f"Segment '{segment_type}' contributions do not reconcile: sum={seg_sum:.4f} vs "
                f"actual_change={delta_revenue:.4f} (error={seg_check.error:.4f}, tolerance={request.tolerance})."
            )

    # -- Concurrent KPI movements (§15/16) -- deterministic arithmetic only,
    # never combined into a conclusion here or anywhere in this module -------
    concurrent_kpis: dict[str, ConcurrentKPIMovement] = {}
    for kid in CONCURRENT_KPI_IDS:
        cmp = kpi_engine.compare_periods(
            kid, request.period_current_start, request.period_current_end,
            request.period_previous_start, request.period_previous_end,
            override_analytical_window=request.override_analytical_window,
        )
        concurrent_kpis[kid] = ConcurrentKPIMovement(
            kpi_id=kid, previous_value=cmp.previous_value, current_value=cmp.current_value,
            absolute_change=cmp.absolute_change, percentage_change=cmp.percentage_change,
            warnings=list(cmp.warnings),
        )

    # -- Data quality -----------------------------------------------------------
    coverage_previous = _coverage(data, items_previous, request.period_previous_start,
                                   request.period_previous_end, apply_window_filter, request.order_status)
    coverage_current = _coverage(data, items_current, request.period_current_start,
                                  request.period_current_end, apply_window_filter, request.order_status)
    threshold = contract["data_quality_requirements"]["coverage_threshold_pct"]

    def _tier(cov: Optional[float]) -> str:
        if cov is None:
            return "UNKNOWN"
        pct = cov * 100
        if pct >= threshold:
            return "HIGH"
        if pct >= max(threshold - 15.0, 0):
            return "MEDIUM"
        return "LOW"

    tiers = [_tier(coverage_previous), _tier(coverage_current)]
    overall_dq = "LOW" if "LOW" in tiers else ("MEDIUM" if "MEDIUM" in tiers else ("UNKNOWN" if "UNKNOWN" in tiers else "HIGH"))

    data_quality = DataQualitySummary(
        sample_size_previous=len(items_previous), sample_size_current=len(items_current),
        coverage_previous=coverage_previous, coverage_current=coverage_current,
        data_quality=overall_dq, segment_reconciliation=segment_reconciliation, warnings=warnings,
    )

    return DriverDecompositionResult(
        kpi_id=request.kpi_id, period_current=request.period_current_label,
        period_previous=request.period_previous_label,
        total_change={"absolute": round(delta_revenue, 2), "percentage": pct_change},
        drivers=drivers, segment_contributions=segment_contributions, concurrent_kpis=concurrent_kpis,
        reconciliation=pvm_reconciliation, data_quality=data_quality, lineage=lineage,
    )


# ---------------------------------------------------------------------------
# Contribution tree (§12) -- a lighter, machine-readable export view over an
# already-built DriverDecompositionResult, matching the task's example shape
# ---------------------------------------------------------------------------

def build_contribution_tree(result: DriverDecompositionResult) -> dict[str, Any]:
    return {
        "kpi": result.kpi_id,
        "movement": dict(result.total_change),
        "drivers": [{"name": d.driver, "contribution": d.contribution_value} for d in result.drivers],
        "segments": {
            segment_type: [
                {"segment_value": c.segment_value, "contribution": c.absolute_change, "rank": c.rank}
                for c in contributions
            ]
            for segment_type, contributions in result.segment_contributions.items()
        },
        "reconciliation": {
            "sum_of_contributions": result.reconciliation.sum_of_contributions,
            "actual_change": result.reconciliation.actual_change,
            "error": result.reconciliation.error,
        },
        "causal_claim": False,
    }
