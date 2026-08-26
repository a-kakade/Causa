"""
baseline.py — Step 3C: the baseline engine (task §1) and the historical
sufficiency / fallback ladder (task §2).

Two separate jobs live here, deliberately kept apart:

1. HOW MUCH HISTORY IS ENOUGH, AND AT WHAT LEVEL (`select_level`) -- walks the
   entity -> category -> regional -> global ladder and picks the first level
   whose history clears two independent bars: enough PERIODS to compute a
   baseline at all, and enough underlying OBSERVATIONS (rows) for those periods
   to be trustworthy, not noise. The second bar is read from the KPI's own
   governed contract (`config/kpis.yaml`'s `materiality.minimum_observations`),
   per this task's explicit instruction ("Use the semantic contract's
   minimum_observations"). This is deliberately a data-sufficiency gate, not a
   per-kpi_id lookup table -- see docs/MATERIALITY_ENGINE.md §2 for why.

2. GIVEN a level's history, WHICH BASELINE METHOD(S) ARE COMPUTABLE, AND WHICH
   ONE IS PRIMARY (`compute_baselines`) -- every method that has enough points is
   computed (so downstream code can compare them, e.g. the baseline-disagreement
   check in materiality.py), but only one is reported as "the" baseline value,
   chosen by a documented priority order: seasonal > rolling_mean > ewma >
   previous_period. Seasonal is preferred whenever it's computable specifically
   because task §10 requires predictable seasonal behavior to not be flagged as
   abnormal -- comparing like-for-like calendar periods is the most appropriate
   baseline whenever there's enough history to do it.

No pandas here -- this module operates on plain PeriodObservation lists so it
can be unit-tested with synthetic data without touching the canonical Parquet
layer (mirrors how query_planner.py stays pandas-free -- see
docs/KPI_COMPUTATION_ENGINE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from anomaly.models import BaselineLevel, PeriodObservation

# -- method-specific minimum period counts (NOT the contract's minimum_observations
# -- see module docstring: this is "can the arithmetic even run", the contract
# figure is "should we trust it"). These are engine defaults, not tuned against a
# backtest -- flagged as configuration in docs/MATERIALITY_ENGINE.md, same
# posture as config/kpis.yaml's shared_materiality_note. ---------------------
DEFAULT_MIN_PERIODS = {
    "previous_period": 1,
    "rolling_mean": 3,
    "rolling_median": 3,
    "rolling_std": 3,
    "ewma": 2,
    "seasonal": 2,   # PRIOR CYCLES required, not periods -- see _compute_seasonal
}

# Priority order for which computed method becomes "the" reported baseline.
METHOD_PRIORITY = ("seasonal", "rolling_mean", "ewma", "previous_period")


@dataclass
class BaselineConfig:
    rolling_window: int = 6                 # months of trailing history used for mean/median/std
    ewma_span: int = 3
    seasonal_cycles_required: int = 2       # how many prior same-calendar-month points needed
    min_periods: dict = field(default_factory=lambda: dict(DEFAULT_MIN_PERIODS))


@dataclass
class LevelSelection:
    level: BaselineLevel
    fallback_reason: Optional[str]           # None if the FIRST level tried was sufficient
    insufficient_even_at_chosen_level: bool  # True only if every level (including global) failed


def _values(history: list[PeriodObservation]) -> list[float]:
    return [o.value for o in history if o.value is not None]


def _is_level_sufficient(level: BaselineLevel, contract_minimum_observations: Optional[int],
                          config: BaselineConfig) -> bool:
    """A level is usable if it has enough NON-NULL periods to compute at least
    the weakest baseline method (previous_period always needs >=1; we require
    the stronger rolling_mean's minimum here so a level that "passes" can
    support more than the single-point comparison) AND enough total underlying
    observations (rows) to trust those periods, per the contract's own
    minimum_observations."""
    n_periods = len(_values(level.history))
    if n_periods < config.min_periods["rolling_mean"]:
        return False
    if contract_minimum_observations is not None and level.total_observations() < contract_minimum_observations:
        return False
    return True


def select_level(levels: list[BaselineLevel], contract_minimum_observations: Optional[int],
                  config: Optional[BaselineConfig] = None) -> LevelSelection:
    """Walks `levels` in the order supplied (caller is responsible for ordering
    them entity-first per FALLBACK_ORDER) and returns the first sufficient one.
    If none is sufficient, returns the LAST level supplied (typically "global")
    flagged `insufficient_even_at_chosen_level=True` -- the caller (engine.py)
    turns that into an INSUFFICIENT_DATA verdict rather than a fabricated
    baseline. Never silently invents a baseline from an insufficient level."""
    config = config or BaselineConfig()
    if not levels:
        raise ValueError("select_level requires at least one BaselineLevel")

    for i, level in enumerate(levels):
        if _is_level_sufficient(level, contract_minimum_observations, config):
            # carry the full reason chain, not just the immediately-prior level,
            # so a 3-hop fallback (entity -> category -> regional) is fully
            # explained rather than only naming the last skip.
            reason = None
            if i > 0:
                skipped = ", ".join(lv.level for lv in levels[:i])
                reason = f"{skipped}_history_insufficient"
            return LevelSelection(level=level, fallback_reason=reason, insufficient_even_at_chosen_level=False)

    return LevelSelection(level=levels[-1], fallback_reason="all_levels_insufficient",
                           insufficient_even_at_chosen_level=True)


# ---------------------------------------------------------------------------
# Individual baseline methods
# ---------------------------------------------------------------------------

def compute_previous_period(history: list[PeriodObservation]) -> Optional[float]:
    """Simplest baseline: the immediately preceding period's value. Always
    available with >=1 valid historical point -- the weakest baseline (a single
    observation), never the sole basis for a CRITICAL/MATERIAL verdict on its
    own (materiality.py enforces this via the disagreement check)."""
    for obs in reversed(history):
        if obs.value is not None:
            return float(obs.value)
    return None


def compute_rolling_mean(history: list[PeriodObservation], window: int) -> Optional[float]:
    vals = _values(history)[-window:]
    if len(vals) < DEFAULT_MIN_PERIODS["rolling_mean"]:
        return None
    return sum(vals) / len(vals)


def compute_rolling_median(history: list[PeriodObservation], window: int) -> Optional[float]:
    vals = sorted(_values(history)[-window:])
    if len(vals) < DEFAULT_MIN_PERIODS["rolling_median"]:
        return None
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def compute_rolling_std(history: list[PeriodObservation], window: int) -> Optional[float]:
    """Population-style sample std (ddof=1). Requires >=3 points -- a std from 2
    points is technically computable but not a meaningful spread estimate, so it
    is withheld (returns None) rather than reported with false confidence."""
    vals = _values(history)[-window:]
    if len(vals) < DEFAULT_MIN_PERIODS["rolling_std"]:
        return None
    mean = sum(vals) / len(vals)
    variance = sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)
    return variance ** 0.5


def compute_ewma(history: list[PeriodObservation], span: int) -> Optional[float]:
    """Exponentially weighted moving average, alpha = 2/(span+1) (pandas' own
    convention). Needs fewer points than rolling_mean (2) since it weights
    recent observations more heavily -- useful when an entity has thin but
    growing history."""
    vals = _values(history)
    if len(vals) < DEFAULT_MIN_PERIODS["ewma"]:
        return None
    alpha = 2.0 / (span + 1)
    ewma = vals[0]
    for v in vals[1:]:
        ewma = alpha * v + (1 - alpha) * ewma
    return ewma


def _period_month(period: str) -> Optional[str]:
    """"2017-11" -> "11". Returns None for anything not in YYYY-MM form (this
    engine only supports month-grain seasonality, matching every KPI contract's
    declared time dimension -- see docs/KPI_COMPUTATION_ENGINE.md §7)."""
    parts = period.split("-")
    if len(parts) != 2 or len(parts[1]) != 2:
        return None
    return parts[1]


def compute_seasonal(history: list[PeriodObservation], current_period: str, cycles_required: int) -> Optional[float]:
    """Mean of the same calendar month across prior years. Deliberately requires
    >= cycles_required (default 2) prior same-month observations -- a single
    prior year is one data point, not a pattern (task §10 requires seasonal
    normalization to be evidence-based, not assumed from one occurrence). Given
    Causa's ~2-year dataset (docs/ANALYTICAL_WINDOW.md), this will frequently be
    unavailable in practice -- reported as None (no fabricated seasonal claim),
    not zero."""
    target_month = _period_month(current_period)
    if target_month is None:
        return None
    matches = [o.value for o in history if o.value is not None and _period_month(o.period) == target_month]
    if len(matches) < cycles_required:
        return None
    return sum(matches) / len(matches)


@dataclass
class BaselineOutcome:
    primary_method: str
    primary_value: Optional[float]
    all_methods: dict[str, Optional[float]]
    rolling_std: Optional[float]            # exposed separately -- statistics.py needs it for z-scores
    rolling_median: Optional[float]
    minimum_history_required: int


def compute_baselines(history: list[PeriodObservation], current_period: str,
                       config: Optional[BaselineConfig] = None) -> BaselineOutcome:
    """Computes every feasible baseline method against `history`, then selects
    one as primary per METHOD_PRIORITY. Returns None-valued primary if not even
    previous_period is computable (an empty/all-null history)."""
    config = config or BaselineConfig()

    all_methods = {
        "previous_period": compute_previous_period(history),
        "rolling_mean": compute_rolling_mean(history, config.rolling_window),
        "ewma": compute_ewma(history, config.ewma_span),
        "seasonal": compute_seasonal(history, current_period, config.seasonal_cycles_required),
    }
    rolling_median = compute_rolling_median(history, config.rolling_window)
    rolling_std = compute_rolling_std(history, config.rolling_window)

    primary_method = "none"
    primary_value = None
    for method in METHOD_PRIORITY:
        if all_methods.get(method) is not None:
            primary_method = method
            primary_value = all_methods[method]
            break

    return BaselineOutcome(
        primary_method=primary_method,
        primary_value=primary_value,
        all_methods=all_methods,
        rolling_std=rolling_std,
        rolling_median=rolling_median,
        minimum_history_required=config.min_periods["rolling_mean"],
    )


def confidence_for_level(level_name: str, n_periods: int, is_fallback: bool, insufficient: bool) -> str:
    """HIGH/MEDIUM/LOW/NONE band for `BaselineInfo.baseline_confidence`.

    Confidence depends on whether this level was reached via a FALLBACK, not on
    the level's name alone -- a whole-of-business KPI (e.g. Revenue with no
    dimension slice) legitimately supplies a single "global" level as its ONLY
    and most-specific rung, and a healthy amount of platform-wide history there
    is genuinely HIGH confidence, not a degraded fallback. Confidence is only
    downgraded when a level was reached BECAUSE a more specific one (entity,
    then category, then regional) proved insufficient (task §12's sparse-entity
    requirement: a two-observation product falling back to its category must
    never be reported at HIGH confidence, even if the category itself has ample
    history)."""
    if insufficient:
        return "NONE"
    healthy = n_periods >= DEFAULT_MIN_PERIODS["rolling_mean"] * 2
    if not is_fallback:
        return "HIGH" if healthy else "MEDIUM"
    return "MEDIUM" if healthy else "LOW"
