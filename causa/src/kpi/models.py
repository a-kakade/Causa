"""
models.py — Step 3B request/result data structures.

These are plain, serializable containers. They carry no calculation logic and no
independently-invented business rules -- every field they hold is either supplied
by the caller (KPIRequest) or copied from the governed contract / computed by the
engine and attached here for traceability (KPIResult). See engine.py for where
values actually get computed.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

@dataclass
class KPIRequest:
    """A request for one KPI's value.

    kpi_id                    Required. Must match a kpi_id in config/kpis.yaml.
    start_date / end_date     Optional "YYYY-MM-DD". Defaults to the contract's
                               declared valid_time_window (default_start/end), or
                               full_data_start/end if override_analytical_window
                               is True and no explicit dates are given.
    dimensions                Grouping dimensions, e.g. ["month"], ["month",
                               "product_category"]. Each must be a dimension name
                               declared AND supported=true in the KPI's contract,
                               or one of the time-grain aliases "day"/"week"/
                               "month" (all resolve through the contract's
                               declared "month" dimension's source column, just
                               bucketed at a different frequency -- see
                               docs/KPI_COMPUTATION_ENGINE.md).
    filters                   e.g. {"order_status": "delivered"}. Keys must match
                               a filter declared in the contract's `filters` list
                               (or the reserved "in_analytical_window" key).
    variant                   Only meaningful for avg_review_score. One of the
                               contract's aggregation_variants ids. Defaults to
                               whichever variant has is_default=true.
    override_analytical_window  If True, do not apply the default
                               in_analytical_window filter (or, for
                               repeat_purchase_rate, do not apply its
                               deliberately-off default -- see the contract).
                               Excluded-period rows are never deleted from the
                               canonical layer, so this simply changes which rows
                               participate -- nothing is destroyed either way.
    requester_clearance       One of PUBLIC_ANALYTICAL / INTERNAL / RESTRICTED.
                               A dimension whose security_classification exceeds
                               this clearance is rejected as unauthorized, even if
                               the contract marks it supported=true.
    comparison_start / comparison_end   Optional. If both given, engine.compute()
                               additionally computes the same KPI over this second
                               period and returns a ComparisonResult (see
                               engine.compare_periods for the explicit form).
    """
    kpi_id: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    dimensions: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    variant: Optional[str] = None
    override_analytical_window: bool = False
    requester_clearance: str = "PUBLIC_ANALYTICAL"
    comparison_start: Optional[str] = None
    comparison_end: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class KPIResult:
    """The only thing engine.compute() returns for a single (possibly grouped)
    slice. Never a bare number -- every field below is populated on every result,
    even when the value itself is None (e.g. a zero-denominator ratio)."""
    kpi_id: str
    value: Optional[float]
    period: dict[str, str]                  # {"start": ..., "end": ...}
    grain: str                              # copied from the contract's base_grain
    dimensions: dict[str, Any]              # which dimension-value slice this is (empty = total)
    filters: dict[str, Any]                 # the EFFECTIVE filters applied (resolved, not just requested)
    sample_size: int                        # rows that actually contributed to `value`
    coverage: Optional[float]                # contributing / eligible-population, 0..1
    data_quality: str                       # HIGH | MEDIUM | LOW | UNKNOWN
    source: list[str]                       # canonical tables read
    lineage: list[dict[str, str]]           # copied verbatim from the contract
    warnings: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)  # KPI-specific extras (numerator, denominator, ...)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ComparisonResult:
    """Deterministic period-over-period change. NOT an anomaly judgement -- no
    threshold, no materiality decision, no statistical test. Just arithmetic over
    two KPIResults."""
    kpi_id: str
    current: KPIResult
    previous: KPIResult
    current_value: Optional[float]
    previous_value: Optional[float]
    absolute_change: Optional[float]
    percentage_change: Optional[float]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kpi_id": self.kpi_id,
            "current": self.current.to_dict(),
            "previous": self.previous.to_dict(),
            "current_value": self.current_value,
            "previous_value": self.previous_value,
            "absolute_change": self.absolute_change,
            "percentage_change": self.percentage_change,
            "warnings": self.warnings,
        }
