"""
engine.py — Step 3C: the materiality and anomaly detection engine.

    AnomalyRequest -> SemanticRegistry (materiality config, aggregation kind)
        -> baseline.select_level (historical sufficiency, §2)
        -> baseline.compute_baselines (§1)
        -> statistics.{z_score,robust_z_score,percentile_rank} (§4)
        -> materiality.compute_business_impact (§5)
        -> materiality.classify_persistence (§6)
        -> materiality.decide (§8/§9/§13)
        -> AnomalyResult (§14)

This module answers exactly one question: "is this KPI movement sufficiently
unusual and economically meaningful to warrant an investigation?" It NEVER
answers "why did it happen?" -- no code path here inspects, names, or infers a
cause (no Black-Friday-style lookup, no external calendar, no correlation
presented as causation). See docs/MATERIALITY_ENGINE.md §8 for the boundary
this module deliberately does not cross, and STEP3C_VALIDATION.md for the
November 2017 worked example that demonstrates it.

This module does NOT read data/processed/*.parquet and does NOT depend on
kpi.engine.KPIEngine. It operates on plain PeriodObservation histories supplied
by the caller (an AnomalyRequest) -- exactly like kpi.query_planner stays
pandas-free and only consults the contract plus the request. Whoever builds the
history (scripts/step3c_validate_engine.py, in this repo, using KPIEngine) is
free to source it from live computed KPI values, a cached report, or synthetic
test fixtures; this engine does not care which.
"""

from __future__ import annotations

from typing import Optional

from anomaly.baseline import BaselineConfig, compute_baselines, confidence_for_level, select_level
from anomaly.materiality import BaselineSignalSet, classify_persistence, compute_business_impact, decide
from anomaly.models import (
    PERSISTENCE_UNKNOWN, VERDICT_INSUFFICIENT_DATA,
    AnomalyRequest, AnomalyResult, BaselineInfo, BusinessImpact, DataQuality, MaterialityAssessment,
    MovementInfo, Persistence, StatisticalSignals,
)
from anomaly.semantic import kpi_kind_for, materiality_config_for
from anomaly.statistics import assumptions_note, mad, percentile_rank, robust_z_score, z_score


def detect(registry, request: AnomalyRequest, baseline_config: Optional[BaselineConfig] = None) -> AnomalyResult:
    """The one public entry point. `registry` is a kpi.semantic_registry.
    SemanticRegistry (already loaded/validated by the caller -- this module
    does not construct or validate one itself, mirroring kpi.query_planner's
    relationship to the registry)."""
    if not request.levels:
        raise ValueError("AnomalyRequest.levels must contain at least one BaselineLevel (typically 'global').")

    contract = registry.get(request.kpi_id)
    cfg = materiality_config_for(contract)
    kpi_kind = kpi_kind_for(contract)
    kpi_name = contract.get("name", request.kpi_id)

    config = baseline_config or BaselineConfig()
    selection = select_level(request.levels, cfg.minimum_observations, config)
    level = selection.level
    valid_periods = sum(1 for o in level.history if o.value is not None)
    confidence = confidence_for_level(level.level, valid_periods, selection.fallback_reason is not None,
                                       selection.insufficient_even_at_chosen_level)
    outcome = compute_baselines(level.history, request.period, config)

    warnings: list[str] = []
    baseline_info = BaselineInfo(
        baseline_method=outcome.primary_method, baseline_value=outcome.primary_value,
        history_periods=valid_periods, minimum_history_required=outcome.minimum_history_required,
        baseline_level=level.level, baseline_confidence=confidence, fallback_reason=selection.fallback_reason,
        all_methods=outcome.all_methods,
    )
    if selection.fallback_reason is not None:
        # The fallback level's history is that level's OWN aggregate (e.g. a
        # whole product_category's monthly revenue), not an estimate scaled to
        # this entity's typical size -- movement/business-impact figures below
        # compare the entity's raw value against that coarser aggregate, which
        # is a different (coarser) question than "is this entity's activity
        # unusual for an entity like it." Never hidden -- see task §7 -- and
        # this is exactly why baseline_confidence is never HIGH at a fallback
        # level (baseline.py's confidence_for_level) and the verdict is capped
        # at WATCH under low current-period sample size (materiality.decide).
        warnings.append(
            f"Baseline was computed at the '{level.level}' level (fallback: {selection.fallback_reason}) -- "
            "its value is that level's own aggregate, not scaled to this entity's typical size. Read "
            "movement/business-impact figures below as coarse, not precise."
        )

    current_quality_reasons: list[str] = []
    current_low_quality = False
    if cfg.minimum_observations is not None and request.observed_sample_size < cfg.minimum_observations:
        current_low_quality = True
        current_quality_reasons.append(
            f"Current period sample size ({request.observed_sample_size}) is below the contract's "
            f"minimum_observations ({cfg.minimum_observations})."
        )
    if (cfg.coverage_threshold_pct is not None and request.observed_coverage is not None
            and request.observed_coverage * 100 < cfg.coverage_threshold_pct):
        current_low_quality = True
        current_quality_reasons.append(
            f"Current period coverage ({request.observed_coverage * 100:.1f}%) is below the contract's "
            f"HIGH-confidence threshold ({cfg.coverage_threshold_pct}%)."
        )

    data_quality = DataQuality(
        current_period_sample_size=request.observed_sample_size, current_period_coverage=request.observed_coverage,
        baseline_history_periods=valid_periods, baseline_level_used=level.level, downgraded=False,
        reasons=list(current_quality_reasons),
    )

    # -- early exit: NULL / zero-denominator observed value (§14, test §13) --
    if request.observed_value is None:
        warnings.append(f"{kpi_name}'s observed value for {request.period} is NULL -- movement cannot be assessed.")
        materiality = MaterialityAssessment(
            verdict=VERDICT_INSUFFICIENT_DATA, score=None, tier_magnitude=None, tier_statistical=None,
            tier_business_impact=None, baseline_signals={}, reasons=[
                "Observed KPI value is NULL (e.g. a zero-denominator ratio, or no rows in scope) -- no "
                "movement can be assessed. This is a NULL/undefined value, distinct from a computed "
                "movement of zero."
            ],
        )
        return _empty_result(request, kpi_kind, baseline_info, data_quality, materiality, warnings)

    # -- early exit: no sufficient baseline anywhere in the fallback ladder --
    if selection.insufficient_even_at_chosen_level or outcome.primary_value is None:
        warnings.append(
            f"No sufficient baseline could be established at any level (entity -> category -> regional -> "
            f"global) for {kpi_name} in {request.period} -- insufficient history."
        )
        data_quality.downgraded = True
        materiality = MaterialityAssessment(
            verdict=VERDICT_INSUFFICIENT_DATA, score=None, tier_magnitude=None, tier_statistical=None,
            tier_business_impact=None, baseline_signals={}, reasons=[
                "Baseline could not be established at any fallback level -- there is not enough history "
                "anywhere in the hierarchy to say whether this movement is unusual."
            ],
        )
        return _empty_result(request, kpi_kind, baseline_info, data_quality, materiality, warnings)

    # -- normal path ----------------------------------------------------------
    baseline_value = outcome.primary_value
    absolute_change = request.observed_value - baseline_value
    if baseline_value == 0:
        percentage_change = None
        warnings.append("Baseline value is exactly 0 -- percentage_change is undefined, not infinity.")
    else:
        percentage_change = absolute_change / baseline_value * 100

    windowed = [o.value for o in level.history if o.value is not None][-config.rolling_window:]
    rolling_mean = outcome.all_methods.get("rolling_mean")
    z = (z_score(request.observed_value, rolling_mean, outcome.rolling_std)
         if rolling_mean is not None and outcome.rolling_std is not None else None)
    robust_z = (robust_z_score(request.observed_value, outcome.rolling_median, mad(windowed))
                if outcome.rolling_median is not None else None)
    percentile = percentile_rank(request.observed_value, windowed)
    assumptions = assumptions_note(len(windowed))
    signals_agree = (abs(z - robust_z) <= 1.0) if (z is not None and robust_z is not None) else None

    prev_val = outcome.all_methods.get("previous_period")
    prev_pct = ((request.observed_value - prev_val) / prev_val * 100) if prev_val not in (None, 0) else None
    movement = MovementInfo(
        absolute=absolute_change, percentage=percentage_change,
        previous_period_value=prev_val, previous_period_change_pct=prev_pct,
    )
    statistical_signals = StatisticalSignals(
        z_score=z, robust_z_score=robust_z, percentile=percentile,
        signals_agree=signals_agree, assumptions=assumptions,
    )

    business_impact = compute_business_impact(
        kpi_kind, kpi_name, request.observed_value, baseline_value,
        request.observed_sample_size, cfg.minimum_business_impact,
    )
    persistence = classify_persistence(
        request.observed_value, baseline_value, request.subsequent,
        cfg.absolute_threshold, cfg.relative_threshold, cfg.persistence_periods,
    )

    # -- alternate baseline methods, for the disagreement check only (§9/§13) --
    primary_signal = BaselineSignalSet(outcome.primary_method, absolute_change, percentage_change)
    alternates: list[BaselineSignalSet] = []
    if outcome.primary_method != "previous_period" and prev_val is not None:
        alt_abs = request.observed_value - prev_val
        alt_pct = (alt_abs / prev_val * 100) if prev_val != 0 else None
        alternates.append(BaselineSignalSet("previous_period", alt_abs, alt_pct))
    seasonal_val = outcome.all_methods.get("seasonal")
    if outcome.primary_method != "seasonal" and seasonal_val is not None:
        alt_abs = request.observed_value - seasonal_val
        alt_pct = (alt_abs / seasonal_val * 100) if seasonal_val != 0 else None
        alternates.append(BaselineSignalSet("seasonal", alt_abs, alt_pct))

    materiality = decide(
        primary=primary_signal, alternates=alternates, z=z, robust_z=robust_z, percentile=percentile,
        business_impact_magnitude=business_impact.magnitude,
        absolute_threshold=cfg.absolute_threshold, relative_threshold=cfg.relative_threshold,
        statistical_threshold=cfg.statistical_threshold, minimum_business_impact=cfg.minimum_business_impact,
        baseline_confidence=confidence, current_period_low_quality=current_low_quality,
        current_period_quality_reasons=current_quality_reasons,
    )
    if current_low_quality:
        data_quality.downgraded = True

    return AnomalyResult(
        kpi_id=request.kpi_id, period=request.period, observed_value=request.observed_value,
        baseline=baseline_info, movement=movement, statistical_signals=statistical_signals,
        business_impact=business_impact, persistence=persistence, data_quality=data_quality,
        materiality=materiality, warnings=warnings,
    )


def _empty_result(request: AnomalyRequest, kpi_kind: str, baseline: BaselineInfo, data_quality: DataQuality,
                   materiality: MaterialityAssessment, warnings: list[str]) -> AnomalyResult:
    """Used by both early-exit paths (NULL observed value; no sufficient
    baseline anywhere) -- every field is still populated (never a bare None
    result), just with explicit "not computable" placeholders instead of
    fabricated numbers."""
    return AnomalyResult(
        kpi_id=request.kpi_id, period=request.period, observed_value=request.observed_value,
        baseline=baseline,
        movement=MovementInfo(absolute=None, percentage=None, previous_period_value=None, previous_period_change_pct=None),
        statistical_signals=StatisticalSignals(z_score=None, robust_z_score=None, percentile=None,
                                                signals_agree=None, assumptions=[]),
        business_impact=BusinessImpact(
            kpi_kind=kpi_kind, magnitude=None, affected_population=request.observed_sample_size or None,
            denominator=request.observed_sample_size or None, meets_minimum_business_impact=None,
            business_interpretation="Not computable -- insufficient data.",
        ),
        persistence=Persistence(PERSISTENCE_UNKNOWN, 0, "Not computable -- insufficient data."),
        data_quality=data_quality, materiality=materiality, warnings=warnings,
    )
