"""
materiality.py — Step 3C: business impact (§5), persistence (§6), and the
materiality decision model (§8/§9/§13).

DESIGN RATIONALE (documented per this task's explicit instruction not to just
multiply dimensions together):

Three independent evidence dimensions are scored separately, each 0-3
(NORMAL/WATCH/MATERIAL/CRITICAL as ordinals):
  - magnitude   (classify_magnitude_tier)      -- is the raw size of the move
                 large relative to this KPI's configured absolute/relative
                 thresholds?
  - statistical (classify_statistical_tier)    -- is the move large relative to
                 this KPI's own historical variability (z / robust-z)?
  - business impact (classify_business_impact_tier) -- is the move large
                 relative to the configured minimum_business_impact?

These are then combined by taking the MEDIAN of the three tiers, not the max
and not a weighted product. The median is a simple, fully transparent rule with
a specific property this task's examples require: it takes at least TWO of the
three independent dimensions agreeing to reach a given severity. A KPI that
moves 100% in percentage terms but off a denominator of 3 (magnitude tier high)
while showing no statistical abnormality and no real business impact (both
tiers low) is correctly held down to WATCH, not MATERIAL -- this is exactly
task §3's "a small product: +100% may be statistically meaningless" case. A
genuine, broad-based movement like November 2017 (large in magnitude, large
statistically, large in business impact) clears all three and is not held down
by any single dimension's idiosyncrasy.

On top of the combined tier, two independent caps can only ever pull the
verdict DOWN, never up: low baseline confidence, and low current-period data
quality. Neither is folded into the median (that would let a data-quality
problem masquerade as evidence); both are applied afterward as an explicit,
logged downgrade -- task §7's "Never hide data quality."

Before any of this runs, a separate check (§9/§13) asks whether independent
BASELINE METHODS (previous-period vs the selected primary baseline vs seasonal,
where available) agree on a magnitude tier at all. If they disagree sharply,
the engine reports BASELINE_DISAGREEMENT and stops -- it does not pick a
winner among disagreeing baselines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from anomaly.models import (
    VERDICT_NORMAL, VERDICT_WATCH, VERDICT_MATERIAL, VERDICT_CRITICAL, VERDICT_BASELINE_DISAGREEMENT,
    PERSISTENCE_ONE_OFF, PERSISTENCE_PERSISTENT, PERSISTENCE_REVERSING, PERSISTENCE_TRENDING, PERSISTENCE_UNKNOWN,
    BusinessImpact, MaterialityAssessment, Persistence, PeriodObservation,
)

TIER_NORMAL, TIER_WATCH, TIER_MATERIAL, TIER_CRITICAL = 0, 1, 2, 3
TIER_TO_VERDICT = {TIER_NORMAL: VERDICT_NORMAL, TIER_WATCH: VERDICT_WATCH,
                    TIER_MATERIAL: VERDICT_MATERIAL, TIER_CRITICAL: VERDICT_CRITICAL}

# Multiples-of-configured-threshold that promote a dimension to the next tier.
# Configuration, not statistically tuned -- same posture as config/kpis.yaml's
# shared_materiality_note. Statistical signals use a lower multiplier ladder
# than magnitude/business-impact because a z-score's own units are already a
# "how many standard deviations" scale, so 1x/1.5x/2.5x the configured
# statistical_threshold (itself usually 2.0) means WATCH>=2, MATERIAL>=3,
# CRITICAL>=5 -- conventional z-score severity bands, not arbitrary.
MAGNITUDE_MULTIPLIERS = (1.0, 2.0, 4.0)      # (watch, material, critical)
STATISTICAL_MULTIPLIERS = (1.0, 1.5, 2.5)
BUSINESS_IMPACT_MULTIPLIERS = (1.0, 2.0, 4.0)

# If independent baseline methods' magnitude tiers span >= this many tiers
# (e.g. one says NORMAL=0, another says MATERIAL=2), the engine refuses to pick
# a winner -- task §9/§13.
DISAGREEMENT_TIER_GAP = 2


def _tier_from_multiple(multiple: Optional[float], multipliers: tuple[float, float, float]) -> int:
    if multiple is None:
        return TIER_NORMAL
    watch_x, material_x, critical_x = multipliers
    if multiple >= critical_x:
        return TIER_CRITICAL
    if multiple >= material_x:
        return TIER_MATERIAL
    if multiple >= watch_x:
        return TIER_WATCH
    return TIER_NORMAL


def classify_magnitude_tier(absolute_change: Optional[float], percentage_change: Optional[float],
                             absolute_threshold: Optional[float], relative_threshold: Optional[float]) -> int:
    """Either an absolute-significant move OR a relative-significant move can
    trigger this dimension (task §3's Revenue example: a large absolute move
    can be material even at a modest percentage). A single small-denominator
    percentage swing does not, by itself, produce a MATERIAL/CRITICAL verdict
    -- that requires corroboration from the statistical or business-impact
    dimension too, via the median combination in decide()."""
    multiples = []
    if absolute_threshold not in (None, 0) and absolute_change is not None:
        multiples.append(abs(absolute_change) / absolute_threshold)
    if relative_threshold not in (None, 0) and percentage_change is not None:
        multiples.append(abs(percentage_change) / relative_threshold)
    if not multiples:
        return TIER_NORMAL
    return _tier_from_multiple(max(multiples), MAGNITUDE_MULTIPLIERS)


def classify_statistical_tier(z: Optional[float], robust_z: Optional[float],
                               statistical_threshold: Optional[float]) -> int:
    if statistical_threshold in (None, 0):
        return TIER_NORMAL
    candidates = [abs(v) for v in (z, robust_z) if v is not None]
    if not candidates:
        return TIER_NORMAL
    return _tier_from_multiple(max(candidates) / statistical_threshold, STATISTICAL_MULTIPLIERS)


def classify_business_impact_tier(magnitude: Optional[float], minimum_business_impact: Optional[float]) -> int:
    if magnitude is None or minimum_business_impact in (None, 0):
        return TIER_NORMAL
    return _tier_from_multiple(abs(magnitude) / minimum_business_impact, BUSINESS_IMPACT_MULTIPLIERS)


def combine_tiers(tier_magnitude: int, tier_statistical: int, tier_business_impact: int) -> int:
    """Median of the three -- requires at least two dimensions to agree at (or
    above) a level before that level is granted. See module docstring."""
    return sorted([tier_magnitude, tier_statistical, tier_business_impact])[1]


# ---------------------------------------------------------------------------
# Business impact (§5)
# ---------------------------------------------------------------------------

def compute_business_impact(kpi_kind: str, kpi_name: str, observed_value: Optional[float],
                             baseline_value: Optional[float], observed_sample_size: int,
                             minimum_business_impact: Optional[float]) -> BusinessImpact:
    """kpi_kind: "additive" (SUM/COUNT/COUNT_DISTINCT KPIs -- Revenue, Orders,
    Freight Revenue, Quantity Sold, Review Volume) or "rate_or_average"
    (RATIO/DERIVED_RATIO/MEAN KPIs -- AOV, Average Delivery Days, Average Review
    Score, On-Time Delivery Rate, Repeat Purchase Rate). For the latter, the
    magnitude is never reported or treated as a monetary figure -- task §5's
    explicit instruction -- only as a per-unit shift across the observed
    population."""
    if observed_value is None or baseline_value is None:
        return BusinessImpact(
            kpi_kind=kpi_kind, magnitude=None, affected_population=observed_sample_size or None,
            denominator=observed_sample_size or None, meets_minimum_business_impact=None,
            business_interpretation=f"{kpi_name}'s business impact is not computable -- "
                                     "observed value or baseline value is missing.",
        )

    magnitude = observed_value - baseline_value
    meets = (abs(magnitude) >= minimum_business_impact) if minimum_business_impact not in (None, 0) else None

    if kpi_kind == "additive":
        interpretation = (
            f"{kpi_name} moved by {magnitude:+,.2f} versus its baseline "
            f"(observed value {observed_value:,.2f})."
        )
    else:
        interpretation = (
            f"{kpi_name} moved by {magnitude:+.4f} (its own unit, not a monetary total) "
            f"across {observed_sample_size:,} underlying observations this period."
        )

    return BusinessImpact(
        kpi_kind=kpi_kind, magnitude=magnitude,
        affected_population=observed_sample_size or None, denominator=observed_sample_size or None,
        business_interpretation=interpretation, meets_minimum_business_impact=meets,
    )


# ---------------------------------------------------------------------------
# Persistence (§6) -- informational, never gates the verdict
# ---------------------------------------------------------------------------

def classify_persistence(observed_value: Optional[float], baseline_value: Optional[float],
                          subsequent: list[PeriodObservation], absolute_threshold: Optional[float],
                          relative_threshold: Optional[float], persistence_periods_required: int) -> Persistence:
    """Does NOT gate materiality (task §6: "a one-day revenue shock can still
    be material") -- purely descriptive metadata attached to the result."""
    if observed_value is None or baseline_value is None:
        return Persistence(PERSISTENCE_UNKNOWN, 0, "Movement cannot be classified without both an observed value and a baseline.")

    current_delta = observed_value - baseline_value
    if not subsequent:
        return Persistence(
            PERSISTENCE_UNKNOWN, 1,
            "No subsequent-period data supplied -- cannot yet determine whether this movement "
            "persists, reverses, or trends. Re-evaluate once the next period is available.",
        )

    first = subsequent[0]
    if first.value is None:
        return Persistence(PERSISTENCE_UNKNOWN, 1, "The immediately following period's value is missing -- cannot classify persistence.")

    first_delta = first.value - baseline_value
    first_pct = (first_delta / baseline_value * 100) if baseline_value not in (0, None) else None
    first_moved = classify_magnitude_tier(first_delta, first_pct, absolute_threshold, relative_threshold) >= TIER_WATCH
    first_same_direction = (first_delta > 0) == (current_delta > 0) if current_delta != 0 else False

    if not first_moved:
        # Settled back within the normal range -- a genuine single-period
        # event, not a reversal (which implies overshooting materially in the
        # OPPOSITE direction) and not a persisting one.
        return Persistence(
            PERSISTENCE_ONE_OFF, 1,
            "The movement did not carry into the immediately following period -- it settled back "
            "within the normal range rather than persisting or reversing.",
        )
    if not first_same_direction:
        return Persistence(
            PERSISTENCE_REVERSING, 1,
            "The immediately following period moved materially in the OPPOSITE direction -- an "
            "overshoot/reversal, not a continuation of the original movement.",
        )

    magnitudes = [abs(current_delta), abs(first_delta)]
    consecutive = 1
    for obs in subsequent[1:]:
        if obs.value is None:
            break
        delta = obs.value - baseline_value
        pct = (delta / baseline_value * 100) if baseline_value not in (0, None) else None
        moved = classify_magnitude_tier(delta, pct, absolute_threshold, relative_threshold) >= TIER_WATCH
        same_direction = (delta > 0) == (current_delta > 0) if current_delta != 0 else False
        if not (moved and same_direction):
            break
        consecutive += 1
        magnitudes.append(abs(delta))

    periods_affected = 1 + consecutive

    if periods_affected < persistence_periods_required:
        cls = PERSISTENCE_PERSISTENT
        detail = (f"Movement carried into {consecutive} subsequent period(s), short of the "
                  f"configured {persistence_periods_required} required for a fully confirmed trend.")
    else:
        trending = magnitudes[-1] > magnitudes[0]
        cls = PERSISTENCE_TRENDING if trending else PERSISTENCE_PERSISTENT
        detail = (
            f"Movement carried into {consecutive} consecutive subsequent period(s) "
            f"({'still growing in magnitude' if trending else 'holding at a similar magnitude'})."
        )

    return Persistence(cls, periods_affected, detail)


# ---------------------------------------------------------------------------
# The decision (§8/§9/§13)
# ---------------------------------------------------------------------------

@dataclass
class BaselineSignalSet:
    """One baseline method's resulting movement, for the disagreement check."""
    method: str
    absolute_change: Optional[float]
    percentage_change: Optional[float]


def decide(*, primary: BaselineSignalSet, alternates: list[BaselineSignalSet],
           z: Optional[float], robust_z: Optional[float], percentile: Optional[float],
           business_impact_magnitude: Optional[float],
           absolute_threshold: Optional[float], relative_threshold: Optional[float],
           statistical_threshold: Optional[float], minimum_business_impact: Optional[float],
           baseline_confidence: str, current_period_low_quality: bool,
           current_period_quality_reasons: list[str]) -> MaterialityAssessment:
    """`primary` is the movement computed against the selected/primary baseline
    (baseline.py's chosen method). `alternates` are movements computed against
    every OTHER independently-meaningful baseline available (previous_period if
    it isn't already primary, seasonal if computable) -- used only for the
    agreement check, never as a second vote in the tier combination itself."""
    tier_magnitude = classify_magnitude_tier(primary.absolute_change, primary.percentage_change,
                                              absolute_threshold, relative_threshold)
    tier_statistical = classify_statistical_tier(z, robust_z, statistical_threshold)
    tier_business_impact = classify_business_impact_tier(business_impact_magnitude, minimum_business_impact)

    baseline_signals = {
        "primary_baseline_method": primary.method,
        "primary_baseline_change_pct": primary.percentage_change,
        "rolling_zscore": z,
        "robust_zscore": robust_z,
        "percentile": percentile,
    }
    for alt in alternates:
        baseline_signals[f"{alt.method}_change_pct"] = alt.percentage_change

    method_tiers = {primary.method: tier_magnitude}
    for alt in alternates:
        method_tiers[alt.method] = classify_magnitude_tier(alt.absolute_change, alt.percentage_change,
                                                             absolute_threshold, relative_threshold)

    # Seasonal is exempt from the disagreement check specifically: when it is
    # available and chosen as primary, that already happened because it is the
    # most statistically appropriate baseline for a KPI with a demonstrated
    # calendar pattern (task §10). A season-naive baseline (previous_period,
    # rolling_mean) is EXPECTED to diverge from it for a genuine seasonal
    # peak/trough -- that divergence is the definition of seasonality, not
    # evidence of uncertainty, so it must not trigger BASELINE_DISAGREEMENT.
    # The season-naive values are still surfaced in baseline_signals below for
    # transparency; they just don't gate the verdict here.
    if len(method_tiers) >= 2 and primary.method != "seasonal":
        spread = max(method_tiers.values()) - min(method_tiers.values())
        if spread >= DISAGREEMENT_TIER_GAP:
            method_verdicts = {k: TIER_TO_VERDICT[v] for k, v in method_tiers.items()}
            baseline_signals["method_verdicts"] = method_verdicts
            return MaterialityAssessment(
                verdict=VERDICT_BASELINE_DISAGREEMENT, score=None,
                tier_magnitude=tier_magnitude, tier_statistical=tier_statistical,
                tier_business_impact=tier_business_impact, baseline_signals=baseline_signals,
                reasons=[
                    f"Baseline methods disagree on materiality: {method_verdicts}. "
                    "Reporting BASELINE_DISAGREEMENT rather than choosing one baseline arbitrarily -- "
                    "a human (or a future step) must adjudicate which baseline is the right frame here."
                ],
            )

    final_tier = combine_tiers(tier_magnitude, tier_statistical, tier_business_impact)
    score = round((tier_magnitude + tier_statistical + tier_business_impact) / 9.0, 3)
    reasons: list[str] = []

    if baseline_confidence in ("LOW", "NONE") and final_tier > TIER_WATCH:
        reasons.append(
            f"Baseline confidence is {baseline_confidence} -- verdict capped at WATCH "
            f"(computed tier was {TIER_TO_VERDICT[final_tier]}). A thin or fallback-level baseline "
            "must never produce a high-confidence MATERIAL/CRITICAL verdict."
        )
        final_tier = TIER_WATCH
    if current_period_low_quality and final_tier > TIER_WATCH:
        reasons.append(
            f"Current-period data quality is low -- verdict capped at WATCH "
            f"(computed tier was {TIER_TO_VERDICT[final_tier]})."
        )
        reasons.extend(current_period_quality_reasons)
        final_tier = TIER_WATCH

    if not reasons:
        if final_tier == TIER_NORMAL:
            reasons.append("Magnitude, statistical, and business-impact signals are all within configured normal ranges.")
        else:
            reasons.append(
                f"Combined from magnitude tier={tier_magnitude}, statistical tier={tier_statistical}, "
                f"business-impact tier={tier_business_impact} (median of the three, requiring at least "
                "two independent dimensions to agree before elevating the verdict)."
            )

    return MaterialityAssessment(
        verdict=TIER_TO_VERDICT[final_tier], score=score,
        tier_magnitude=tier_magnitude, tier_statistical=tier_statistical,
        tier_business_impact=tier_business_impact, baseline_signals=baseline_signals, reasons=reasons,
    )
