"""
models.py — Step 3C: request/result data structures for the materiality and
anomaly detection engine.

Plain, serializable containers. No calculation logic lives here -- see
baseline.py / statistics.py / materiality.py / engine.py for that. Every result
object is designed to be fully transparent: every number that fed the verdict is
present on the object, not just the verdict itself, so a human can audit the
decision without re-running the engine.

STRICT RULE: nothing in this module (or anywhere in src/anomaly/) ever asserts
*why* a movement happened. See AnomalyResult's docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Materiality verdicts
# ---------------------------------------------------------------------------

# Six possible verdicts. NORMAL/WATCH/MATERIAL/CRITICAL/INSUFFICIENT_DATA are
# the five named in this task's §8 decision model (the OBJECTIVE section's
# "NORMAL VARIATION / MINOR MOVEMENT / MATERIAL MOVEMENT / CRITICAL MOVEMENT /
# INSUFFICIENT EVIDENCE" is the same five-way split under different labels --
# WATCH == MINOR MOVEMENT, INSUFFICIENT_DATA == INSUFFICIENT EVIDENCE -- unified
# here on the §8 names since that section gives the canonical enum). A sixth,
# BASELINE_DISAGREEMENT, is added per §9/§13's explicit instruction: when
# independent baseline methods (previous-period vs rolling/seasonal) disagree
# about whether a movement is material, the engine must say so rather than pick
# a winner -- this is a genuinely distinct state from "not enough history"
# (INSUFFICIENT_DATA) or "not unusual" (NORMAL).
VERDICT_NORMAL = "NORMAL"
VERDICT_WATCH = "WATCH"
VERDICT_MATERIAL = "MATERIAL"
VERDICT_CRITICAL = "CRITICAL"
VERDICT_INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
VERDICT_BASELINE_DISAGREEMENT = "BASELINE_DISAGREEMENT"

ALL_VERDICTS = (
    VERDICT_NORMAL, VERDICT_WATCH, VERDICT_MATERIAL, VERDICT_CRITICAL,
    VERDICT_INSUFFICIENT_DATA, VERDICT_BASELINE_DISAGREEMENT,
)

PERSISTENCE_ONE_OFF = "ONE_OFF"
PERSISTENCE_PERSISTENT = "PERSISTENT"
PERSISTENCE_REVERSING = "REVERSING"
PERSISTENCE_TRENDING = "TRENDING"
PERSISTENCE_UNKNOWN = "UNKNOWN"

BASELINE_LEVEL_ENTITY = "entity"
BASELINE_LEVEL_CATEGORY = "category"
BASELINE_LEVEL_REGIONAL = "regional"
BASELINE_LEVEL_GLOBAL = "global"
FALLBACK_ORDER = (BASELINE_LEVEL_ENTITY, BASELINE_LEVEL_CATEGORY, BASELINE_LEVEL_REGIONAL, BASELINE_LEVEL_GLOBAL)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class PeriodObservation:
    """One historical (or subsequent) data point for a KPI at some level of the
    fallback hierarchy. `period` is a label such as "2017-10" (month grain is
    assumed throughout this engine, matching every KPI contract's declared
    "month" dimension -- see docs/KPI_COMPUTATION_ENGINE.md §7). `sample_size` is
    the number of underlying rows that produced `value` (e.g. orders, order
    items, reviews) -- this is what "two-observation entity" means in practice
    (§12): not two calendar periods, but two underlying rows total."""
    period: str
    value: Optional[float]
    sample_size: int = 0
    coverage: Optional[float] = None


@dataclass
class BaselineLevel:
    """One rung of the entity -> category -> regional -> global fallback ladder
    (§2). `history` is chronologically ordered and must NOT include the period
    being evaluated. `level` must be one of BASELINE_LEVEL_*."""
    level: str
    label: str
    history: list[PeriodObservation] = field(default_factory=list)

    def total_observations(self) -> int:
        return sum(o.sample_size for o in self.history)


@dataclass
class AnomalyRequest:
    """Everything the engine needs to assess one KPI movement.

    kpi_id                The governed contract id (config/kpis.yaml).
    period                Label of the period being evaluated, e.g. "2017-11".
    observed_value         The KPI's value in `period`. None is a legitimate
                           input (NULL KPI / zero-denominator ratio) -- see §14.
    observed_sample_size   Rows backing `observed_value` (orders, reviews, ...).
    observed_coverage      0..1, copied from the KPI engine's KPIResult.coverage.
    levels                 Baseline fallback ladder, most-specific first
                           (typically [entity, category, regional, global], but
                           a whole-of-business KPI with no dimension slice may
                           legitimately supply a single "global" level only).
    subsequent              Observations AFTER `period`, chronologically ordered,
                           used for persistence classification (§6). Optional --
                           persistence is reported UNKNOWN, never guessed, if
                           empty.
    """
    kpi_id: str
    period: str
    observed_value: Optional[float]
    observed_sample_size: int = 0
    observed_coverage: Optional[float] = None
    levels: list[BaselineLevel] = field(default_factory=list)
    subsequent: list[PeriodObservation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Result -- AnomalyResult, per this task's §14 contract
# ---------------------------------------------------------------------------

@dataclass
class BaselineInfo:
    baseline_method: str                       # "previous_period"|"rolling_mean"|"ewma"|"seasonal"|"none"
    baseline_value: Optional[float]
    history_periods: int                       # periods available AT THE LEVEL USED
    minimum_history_required: int
    baseline_level: str                        # entity|category|regional|global|none
    baseline_confidence: str                   # HIGH|MEDIUM|LOW|NONE
    fallback_reason: Optional[str]              # None if entity-level was sufficient
    all_methods: dict[str, Optional[float]] = field(default_factory=dict)  # every feasible method's value, for transparency


@dataclass
class MovementInfo:
    absolute: Optional[float]
    percentage: Optional[float]
    previous_period_value: Optional[float]
    previous_period_change_pct: Optional[float]


@dataclass
class StatisticalSignals:
    z_score: Optional[float]
    robust_z_score: Optional[float]
    percentile: Optional[float]
    signals_agree: Optional[bool]               # None if not enough signals to compare
    assumptions: list[str] = field(default_factory=list)


@dataclass
class BusinessImpact:
    kpi_kind: str                                # "additive" | "rate_or_average"
    magnitude: Optional[float]                    # observed - expected, in the KPI's own unit
    affected_population: Optional[int]
    denominator: Optional[int]
    business_interpretation: str
    meets_minimum_business_impact: Optional[bool]


@dataclass
class Persistence:
    persistence_class: str                       # ONE_OFF|PERSISTENT|REVERSING|TRENDING|UNKNOWN
    periods_affected: int
    detail: str


@dataclass
class DataQuality:
    current_period_sample_size: int
    current_period_coverage: Optional[float]
    baseline_history_periods: int
    baseline_level_used: str
    downgraded: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class MaterialityAssessment:
    verdict: str
    score: Optional[float]                        # 0..1, continuous transparency signal -- NOT the verdict driver alone
    tier_magnitude: Optional[int]
    tier_statistical: Optional[int]
    tier_business_impact: Optional[int]
    baseline_signals: dict[str, Any] = field(default_factory=dict)   # §9: previous_period_change, rolling_zscore, robust_zscore, percentile, seasonal_change
    reasons: list[str] = field(default_factory=list)


@dataclass
class AnomalyResult:
    """The only thing engine.detect() returns.

    This object answers exactly one question: "is this movement sufficiently
    unusual and economically meaningful to warrant an investigation?" It does
    NOT and must never answer "why did it happen?" -- no field here may contain
    a causal claim (enforced by tests/test_anomaly_engine.py::
    test_no_result_contains_a_causal_claim, which scans every string field of
    every test fixture's result for causal language)."""
    kpi_id: str
    period: str
    observed_value: Optional[float]
    baseline: BaselineInfo
    movement: MovementInfo
    statistical_signals: StatisticalSignals
    business_impact: BusinessImpact
    persistence: Persistence
    data_quality: DataQuality
    materiality: MaterialityAssessment
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
