"""
models.py — Step 3D: request/result data structures for the driver
decomposition engine.

Plain, serializable containers, no calculation logic. Every result object
carries `causal_claim: False` (hardcoded default, not a caller-settable
field) and uses "contribution"/"associated movement"/"mathematical
decomposition" language, never "caused"/"responsible for"/"led to" — this is
enforced structurally here (the field exists and defaults to False on every
dataclass that represents a driver-shaped result) and re-checked by
tests/test_driver_engine.py's causal-language scan, same discipline
src/anomaly/models.py used in Step 3C.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

DIRECTION_POSITIVE = "positive"
DIRECTION_NEGATIVE = "negative"
DIRECTION_FLAT = "flat"

EVIDENCE_DETERMINISTIC = "deterministic"

METHOD_PVM = "PVM"
METHOD_SEGMENT = "deterministic_contribution_analysis"


def direction_of(value: Optional[float]) -> str:
    if value is None or value == 0:
        return DIRECTION_FLAT
    return DIRECTION_POSITIVE if value > 0 else DIRECTION_NEGATIVE


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------

@dataclass
class DriverDecompositionRequest:
    """kpi_id is currently constrained to "revenue" -- PVM (Price x Volume x
    Mix) is only meaningful for a SUM-of-price KPI (task §1's explicit scope).
    Segment/concurrent-KPI analysis is generic, but this engine does not (yet)
    generalize PVM to other KPIs -- see docs/DRIVER_DECOMPOSITION.md.

    period_current_label / period_previous_label are human-readable period
    labels (e.g. "2017-11") attached to every result for traceability; the
    *_start/*_end fields are the actual "YYYY-MM-DD" date range used to filter
    canonical data, so a period need not be a calendar month.

    segment_dimensions: None defaults to every dimension this engine's
    requester_clearance can reach (§4/5/6); an explicit list is validated
    against the KPI's own contract (§14) and raises if any entry is
    unsupported or unauthorized for requester_clearance.
    """
    kpi_id: str
    period_current_start: str
    period_current_end: str
    period_current_label: str
    period_previous_start: str
    period_previous_end: str
    period_previous_label: str
    segment_dimensions: Optional[list[str]] = None
    requester_clearance: str = "PUBLIC_ANALYTICAL"
    override_analytical_window: bool = False
    order_status: Optional[str] = None
    top_n: int = 10
    tolerance: float = 0.01

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Result pieces
# ---------------------------------------------------------------------------

@dataclass
class DriverContribution:
    """One PVM effect (volume/price/mix) -- task §3's exact contract shape."""
    driver: str
    contribution_value: float
    contribution_pct_of_change: Optional[float]
    direction: str
    method: str
    period_current: str
    period_previous: str
    evidence_type: str
    confidence: str
    lineage: list[dict[str, str]] = field(default_factory=list)
    causal_claim: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SegmentContribution:
    """One value of one segment dimension (e.g. product_category=
    "beleza_saude", or seller="unknown_seller" for a null seller_id) -- task
    §4/5/6. `segment_value` is always a concrete string; NULL/missing values
    are normalized to an explicit sentinel label before this object is built
    (never silently dropped, task §4)."""
    segment_type: str
    segment_value: str
    previous_value: float
    current_value: float
    absolute_change: float
    percentage_change: Optional[float]        # None when previous_value == 0 -- never inf (§9)
    share_of_total_movement: Optional[float]    # None when total_change == 0
    rank: Optional[int]                        # assigned by ranking.py, None until ranked
    sample_size: int                            # current-period row count backing this value
    history_periods: Optional[int]              # distinct months with activity, up to period_previous (§10)
    confidence: str                             # HIGH|MEDIUM|LOW, from history/sample volume -- NOT a materiality judgement
    method: str = METHOD_SEGMENT
    evidence_type: str = EVIDENCE_DETERMINISTIC
    causal_claim: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConcurrentKPIMovement:
    """A same-period-pair movement in a DIFFERENT KPI (Orders, AOV, Freight,
    Delivery, Review Score), reported alongside a Revenue decomposition for
    context ONLY -- task §15: "do not combine them into a causal conclusion."
    Deterministic arithmetic via kpi.engine.KPIEngine.compare_periods(),
    nothing more."""
    kpi_id: str
    previous_value: Optional[float]
    current_value: Optional[float]
    absolute_change: Optional[float]
    percentage_change: Optional[float]
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationCheck:
    sum_of_contributions: float
    actual_change: float
    error: float
    tolerance: float
    reconciled: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataQualitySummary:
    sample_size_previous: int
    sample_size_current: int
    coverage_previous: Optional[float]
    coverage_current: Optional[float]
    data_quality: str
    segment_reconciliation: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Result — task §17's DriverDecompositionResult
# ---------------------------------------------------------------------------

@dataclass
class DriverDecompositionResult:
    """This object answers exactly one question: "which measurable factors
    mathematically account for this KPI movement?" It never answers "why did
    it happen" -- causal_claim is hardcoded False and every nested object
    carries the same field. See docs/DRIVER_DECOMPOSITION.md §8."""
    kpi_id: str
    period_current: str
    period_previous: str
    total_change: dict[str, Optional[float]]                  # {"absolute": ..., "percentage": ...}
    drivers: list[DriverContribution]                          # PVM: volume, price, mix
    segment_contributions: dict[str, list[SegmentContribution]]
    concurrent_kpis: dict[str, ConcurrentKPIMovement]
    reconciliation: ReconciliationCheck                         # PVM reconciliation (§12/§13)
    data_quality: DataQualitySummary
    lineage: list[dict[str, str]]
    causal_claim: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "kpi_id": self.kpi_id,
            "period_current": self.period_current,
            "period_previous": self.period_previous,
            "total_change": self.total_change,
            "drivers": [d.to_dict() for d in self.drivers],
            "segment_contributions": {k: [s.to_dict() for s in v] for k, v in self.segment_contributions.items()},
            "concurrent_kpis": {k: v.to_dict() for k, v in self.concurrent_kpis.items()},
            "reconciliation": self.reconciliation.to_dict(),
            "data_quality": self.data_quality.to_dict(),
            "lineage": self.lineage,
            "causal_claim": self.causal_claim,
        }
