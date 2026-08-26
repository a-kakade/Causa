"""
query_planner.py — validates a KPIRequest against the governed contract and
produces a QueryPlan. This module makes NO pandas calls and reads NO canonical
data -- it only consults kpi.semantic_registry.SemanticRegistry (the contracts)
and the request. Its entire job is to reject invalid requests loudly, with a
specific reason, before the engine touches any data.

Rejection categories (per Step 3B spec §1):
  - unknown KPI            -> UnknownKPIError
  - unsupported dimension  -> UnsupportedDimensionError
  - invalid filter         -> InvalidFilterError
  - missing required parameters -> MissingParameterError
  - unauthorized dimension -> UnauthorizedDimensionError
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

import pandas as pd

from kpi.models import KPIRequest
from kpi.semantic_registry import SemanticRegistry

TIME_GRAINS = {"day", "week", "month"}
CLEARANCE_RANK = {"PUBLIC_ANALYTICAL": 0, "INTERNAL": 1, "RESTRICTED": 2}

VALID_ORDER_STATUSES = {
    "delivered", "shipped", "canceled", "unavailable",
    "invoiced", "processing", "created", "approved",
}
VALID_DELIVERY_FLAGS = {"VALID", "MISSING_CUSTOMER_DATE", "MISSING_CARRIER_DATE", "INVALID_SEQUENCE"}


class KPIRequestError(Exception):
    """Base class for every request-rejection reason this planner raises."""


class UnknownKPIError(KPIRequestError):
    pass


class UnsupportedDimensionError(KPIRequestError):
    pass


class UnauthorizedDimensionError(KPIRequestError):
    pass


class InvalidFilterError(KPIRequestError):
    pass


class MissingParameterError(KPIRequestError):
    pass


@dataclass
class ResolvedDimension:
    name: str
    is_time_grain: bool
    time_grain: Optional[str]           # "day" | "week" | "month" | None
    source_table: Optional[str]
    source_column: Optional[str]


@dataclass
class QueryPlan:
    kpi_id: str
    contract: dict[str, Any]
    start: pd.Timestamp
    end: pd.Timestamp
    window_start: str
    window_end: str
    apply_window_filter: bool
    dimensions: list[ResolvedDimension]
    filters: dict[str, Any]                 # validated, effective filters (name -> value)
    delivery_flag_filter: Optional[str]     # resolved mandatory filter value, if any
    variant: Optional[str]
    source_tables: list[str]
    requester_clearance: str


def _require(condition: bool, exc_cls: type[KPIRequestError], message: str) -> None:
    if not condition:
        raise exc_cls(message)


def plan(registry: SemanticRegistry, request: KPIRequest) -> QueryPlan:
    _require(bool(request.kpi_id), MissingParameterError, "kpi_id is required")

    try:
        contract = registry.get(request.kpi_id)
    except KeyError:
        raise UnknownKPIError(
            f"Unknown kpi_id {request.kpi_id!r}. Known KPIs: {registry.list_kpi_ids()}"
        )

    window = contract["valid_time_window"]

    # -- in_analytical_window default (per-KPI -- repeat_purchase_rate's default
    # is OFF, per its contract; every other KPI's default is ON) -- resolved
    # BEFORE the date range default, because the date range default depends on it
    # (see below): a KPI whose window filter defaults off should also default to
    # the FULL data range, not silently restrict to the recommended window while
    # claiming the filter is off. ------------------------------------------------
    window_filter_entry = next(
        (f for f in contract["filters"] if f["source_column"] == "fact_orders.in_analytical_window"), None
    )
    contract_default_apply_window = bool(window_filter_entry and window_filter_entry["applied_by_default"])
    apply_window_filter = contract_default_apply_window and not request.override_analytical_window

    # -- date range -----------------------------------------------------------
    if request.start_date and not request.end_date:
        raise MissingParameterError("end_date is required when start_date is given")
    if request.end_date and not request.start_date:
        raise MissingParameterError("start_date is required when end_date is given")

    if request.start_date and request.end_date:
        try:
            start = pd.Timestamp(request.start_date)
            end = pd.Timestamp(request.end_date)
        except (ValueError, TypeError) as e:
            raise MissingParameterError(f"start_date/end_date could not be parsed: {e}")
        _require(start <= end, MissingParameterError, f"start_date {start} must be <= end_date {end}")
    else:
        # No explicit range given -- default to the recommended window ONLY if
        # this request is actually going to apply the window filter; otherwise
        # (window filter off, whether by contract default or explicit override)
        # default to the full data range, so "window filter off" and "date range"
        # never silently contradict each other.
        if apply_window_filter:
            start, end = pd.Timestamp(window["default_start"]), pd.Timestamp(window["default_end"]) + pd.offsets.MonthEnd(0)
        else:
            start, end = pd.Timestamp(window["full_data_start"]), pd.Timestamp(window["full_data_end"]) + pd.offsets.MonthEnd(0)

    # -- variant (avg_review_score only) --------------------------------------
    variant = request.variant
    variants = contract.get("aggregation_variants")
    if variants:
        valid_variant_ids = {v["variant_id"] for v in variants}
        if variant is None:
            variant = next(v["variant_id"] for v in variants if v["is_default"])
        elif variant not in valid_variant_ids:
            raise InvalidFilterError(
                f"[{request.kpi_id}] unknown variant {variant!r}. Valid: {sorted(valid_variant_ids)}"
            )
    elif variant is not None:
        raise InvalidFilterError(f"[{request.kpi_id}] does not support variants (requested {variant!r})")

    # -- dimensions -------------------------------------------------------------
    resolved_dims: list[ResolvedDimension] = []
    contract_dims_by_name = {d["name"]: d for d in contract["dimensions"]}
    for dim_name in request.dimensions:
        if dim_name in TIME_GRAINS:
            # every time-grain alias resolves through the contract's declared
            # "month" dimension entry -- same underlying column, different
            # pandas resample frequency. The contract, not this planner, still
            # decides whether time-bucketing this KPI is safe at all.
            month_dim = contract_dims_by_name.get("month")
            _require(
                month_dim is not None, UnsupportedDimensionError,
                f"[{request.kpi_id}] has no time dimension declared in its contract -- cannot bucket by {dim_name!r}"
            )
            _require(
                month_dim["supported"], UnsupportedDimensionError,
                f"[{request.kpi_id}] time dimension is declared but marked unsupported: "
                f"{month_dim.get('unsupported_reason', 'no reason given')}"
            )
            _check_clearance(request, month_dim)
            resolved_dims.append(ResolvedDimension(
                name=dim_name, is_time_grain=True, time_grain=dim_name,
                source_table=month_dim["source_table"], source_column=month_dim["source_column"],
            ))
            continue

        dim = contract_dims_by_name.get(dim_name)
        if dim is None:
            raise UnsupportedDimensionError(
                f"[{request.kpi_id}] does not declare a dimension named {dim_name!r}. "
                f"Declared dimensions: {sorted(contract_dims_by_name)}"
            )
        if not dim["supported"]:
            raise UnsupportedDimensionError(
                f"[{request.kpi_id}] dimension {dim_name!r} is explicitly unsupported: "
                f"{dim.get('unsupported_reason', 'no reason given')}"
            )
        _check_clearance(request, dim)
        resolved_dims.append(ResolvedDimension(
            name=dim_name, is_time_grain=False, time_grain=None,
            source_table=dim["source_table"], source_column=dim["source_column"],
        ))

    # -- filters ------------------------------------------------------------
    contract_filter_names = {f["name"] for f in contract["filters"]}
    effective_filters: dict[str, Any] = {}
    delivery_flag_filter = None

    # mandatory contract-level default filters (e.g. avg_delivery_days'
    # delivery_data_quality_flag == VALID) are applied even if the caller didn't
    # ask for them -- they are not optional.
    for f in contract["filters"]:
        if f["source_column"] == "fact_orders.delivery_data_quality_flag" and f["applied_by_default"]:
            delivery_flag_filter = f["default_value"]

    for key, value in request.filters.items():
        if key not in contract_filter_names and key != "in_analytical_window":
            raise InvalidFilterError(
                f"[{request.kpi_id}] does not declare a filter named {key!r}. "
                f"Declared filters: {sorted(contract_filter_names)}"
            )
        if key == "order_status":
            values = value if isinstance(value, (list, tuple, set)) else [value]
            bad = set(values) - VALID_ORDER_STATUSES
            _require(not bad, InvalidFilterError, f"invalid order_status value(s): {bad}. Valid: {VALID_ORDER_STATUSES}")
        if key == "delivery_data_quality_flag":
            _require(value in VALID_DELIVERY_FLAGS, InvalidFilterError,
                      f"invalid delivery_data_quality_flag value {value!r}. Valid: {VALID_DELIVERY_FLAGS}")
            delivery_flag_filter = value  # explicit request overrides the contract default
        effective_filters[key] = value

    return QueryPlan(
        kpi_id=request.kpi_id,
        contract=contract,
        start=start, end=end,
        window_start=window["default_start"], window_end=window["default_end"],
        apply_window_filter=apply_window_filter,
        dimensions=resolved_dims,
        filters=effective_filters,
        delivery_flag_filter=delivery_flag_filter,
        variant=variant,
        source_tables=contract["source_tables"],
        requester_clearance=request.requester_clearance,
    )


def _check_clearance(request: KPIRequest, dim: dict[str, Any]) -> None:
    required = CLEARANCE_RANK.get(dim["security_classification"], 0)
    have = CLEARANCE_RANK.get(request.requester_clearance, 0)
    if have < required:
        raise UnauthorizedDimensionError(
            f"dimension {dim['name']!r} requires clearance {dim['security_classification']!r}, "
            f"requester has {request.requester_clearance!r}"
        )
