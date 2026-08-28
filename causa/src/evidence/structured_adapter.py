"""
structured_adapter.py — Step 4: converts Steps 3B/3C/3D's ALREADY-COMPUTED
result objects into governed EvidenceObjects (task §5).

STRICT RULE: this module never recomputes a KPI, never reads
data/processed/*.parquet, never imports pandas, and never calls
kpi.query_planner. It only accepts already-built KPIResult / ComparisonResult
/ AnomalyResult / DriverDecompositionResult objects and repackages their own
fields -- lineage/source/confidence/data_quality are copied or trivially
mapped from the source dataclass, never re-derived from raw data.
tests/test_structured_adapter.py::test_adapter_module_has_no_pandas_import
enforces this mechanically via a source scan.

Every evidence_type this module produces is checked against
evidence.models.POPULATED_IN_STEP4 before construction -- the concrete
enforcement of "Steps 3B-3D currently generate only T1/T2/T3" (task §1).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from anomaly.models import AnomalyResult
from drivers.models import ConcurrentKPIMovement, DriverContribution, DriverDecompositionResult, SegmentContribution
from kpi.models import ComparisonResult, KPIResult

from evidence.models import (
    TIER_FOR_EVIDENCE_TYPE,
    POPULATED_IN_STEP4,
    Confidence,
    EvidenceType,
    SecurityClassification,
    TrustLevel,
)
from evidence.schema import (
    EvidenceObject,
    FreshnessInfo,
    QualityInfo,
    SecurityInfo,
    SourceInfo,
    TimeRange,
    ValueSpec,
)

ADAPTER_VERSION = "1.0"

# KPIResult.data_quality / SegmentContribution.confidence / DriverContribution.confidence
# strings -> Confidence enum. Also covers AnomalyResult.baseline.baseline_confidence,
# which uses "NONE" instead of "UNKNOWN" for the same "no signal" meaning.
_CONFIDENCE_MAP = {
    "HIGH": Confidence.HIGH, "MEDIUM": Confidence.MEDIUM, "LOW": Confidence.LOW,
    "UNKNOWN": Confidence.UNKNOWN, "NONE": Confidence.UNKNOWN,
}
_QUALITY_RANK = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}


def _confidence_from(label: Optional[str]) -> Confidence:
    if label is None:
        return Confidence.UNKNOWN
    return _CONFIDENCE_MAP.get(label.upper(), Confidence.UNKNOWN)


def _worse_confidence(a: Optional[str], b: Optional[str]) -> Confidence:
    rank_a = _QUALITY_RANK.get((a or "UNKNOWN").upper(), 0)
    rank_b = _QUALITY_RANK.get((b or "UNKNOWN").upper(), 0)
    worse_label = a if rank_a <= rank_b else b
    return _confidence_from(worse_label)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(*parts: Any) -> str:
    canonical = "|".join(json.dumps(p, sort_keys=True, default=str) for p in parts)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def evidence_id_for(prefix: str, *deterministic_parts: Any) -> str:
    """Deterministic content-hash id: rerunning an adapter on identical inputs
    reproduces an identical evidence_id (required for reproducible graphs and
    the traceability tests)."""
    return f"ev_{prefix}_{_stable_hash(*deterministic_parts)}"


def _classification_for_kpi(registry: Any, kpi_id: str) -> SecurityClassification:
    return SecurityClassification(registry.get_security_classification(kpi_id))


def _assert_populated(evidence_type: EvidenceType) -> None:
    if evidence_type not in POPULATED_IN_STEP4:
        raise ValueError(
            f"{evidence_type.value} is not in evidence.models.POPULATED_IN_STEP4 -- Step 4 must never "
            "fabricate evidence of a type/tier reserved for a later step (task §1/§2)."
        )


def _quality_from_kpi_result(result: KPIResult) -> QualityInfo:
    return QualityInfo(completeness=result.coverage, coverage=result.coverage, source_reliability=1.0)


# ---------------------------------------------------------------------------
# KPIResult -> KPI_OBSERVATION
# ---------------------------------------------------------------------------

def kpi_result_to_evidence(result: KPIResult, registry: Any,
                            evidence_type: EvidenceType = EvidenceType.KPI_OBSERVATION) -> EvidenceObject:
    _assert_populated(evidence_type)
    period_label = result.dimensions.get("month", f"{result.period['start']}..{result.period['end']}")
    claim = (
        f"{result.kpi_id} for {period_label} was {result.value} "
        f"(sample_size={result.sample_size}, coverage={result.coverage})."
    )
    dims = {k: str(v) for k, v in result.dimensions.items()}
    return EvidenceObject(
        evidence_id=evidence_id_for("kpiobs", result.kpi_id, result.period, result.dimensions, evidence_type.value),
        evidence_type=evidence_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[evidence_type],
        claim=claim,
        value=ValueSpec(value=result.value, unit=None),
        time=TimeRange(start=result.period["start"], end=result.period["end"]),
        dimensions=dims,
        confidence=_confidence_from(result.data_quality),
        source=SourceInfo(system="kpi_engine", component="kpi.engine.KPIEngine.compute", version=ADAPTER_VERSION),
        lineage=[dict(item) for item in result.lineage],
        freshness=FreshnessInfo(event_time=result.period["end"], processing_time=_now_iso()),
        quality=_quality_from_kpi_result(result),
        security=SecurityInfo(classification=_classification_for_kpi(registry, result.kpi_id),
                               trust_level=TrustLevel.TRUSTED_SYSTEM),
        metadata={k: v for k, v in result.metadata.items() if isinstance(v, (str, int, float, bool)) or v is None},
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# ComparisonResult -> KPI_MOVEMENT
# ---------------------------------------------------------------------------

def comparison_result_to_evidence(comparison: ComparisonResult, registry: Any) -> EvidenceObject:
    evidence_type = EvidenceType.KPI_MOVEMENT
    _assert_populated(evidence_type)
    pct = comparison.percentage_change
    pct_str = f"{pct:+.2f}%" if pct is not None else "an undefined percentage change"
    claim = (
        f"{comparison.kpi_id} moved from {comparison.previous_value} ({comparison.previous.period['start']}.."
        f"{comparison.previous.period['end']}) to {comparison.current_value} ({comparison.current.period['start']}.."
        f"{comparison.current.period['end']}), a change of {comparison.absolute_change} ({pct_str})."
    )
    # current/previous share the same governed lineage chain by construction
    # (same kpi_id, same contract) -- copying current's verbatim is not a
    # re-derivation, just a choice of which identical copy to keep.
    return EvidenceObject(
        evidence_id=evidence_id_for("kpimove", comparison.kpi_id, comparison.previous.period,
                                     comparison.current.period, comparison.current.dimensions),
        evidence_type=evidence_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[evidence_type],
        claim=claim,
        value=ValueSpec(value=comparison.absolute_change, unit=None),
        time=TimeRange(start=comparison.previous.period["start"], end=comparison.current.period["end"]),
        dimensions={k: str(v) for k, v in comparison.current.dimensions.items()},
        confidence=_worse_confidence(comparison.current.data_quality, comparison.previous.data_quality),
        source=SourceInfo(system="kpi_engine", component="kpi.engine.KPIEngine.compare_periods",
                           version=ADAPTER_VERSION),
        lineage=[dict(item) for item in comparison.current.lineage],
        freshness=FreshnessInfo(event_time=comparison.current.period["end"], processing_time=_now_iso()),
        quality=QualityInfo(
            completeness=comparison.current.coverage, coverage=comparison.current.coverage, source_reliability=1.0,
        ),
        security=SecurityInfo(classification=_classification_for_kpi(registry, comparison.kpi_id),
                               trust_level=TrustLevel.TRUSTED_SYSTEM),
        metadata={
            "previous_value": comparison.previous_value, "current_value": comparison.current_value,
            "percentage_change": comparison.percentage_change,
        },
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# AnomalyResult -> ANOMALY_SIGNAL + STATISTICAL_RESULT
# ---------------------------------------------------------------------------

def anomaly_result_to_evidence(result: AnomalyResult, registry: Any) -> list[EvidenceObject]:
    """Returns exactly two objects. AnomalyResult carries no single top-level
    `.lineage` list of its own (unlike KPIResult/DriverContribution), so this
    is the one place in this module that ASSEMBLES a lineage trail rather than
    copying one verbatim -- documented here rather than left implicit."""
    classification = _classification_for_kpi(registry, result.kpi_id)
    assembled_lineage = [
        {"layer": "anomaly_engine", "reference": "src/anomaly/engine.py::detect"},
        {"layer": "baseline_method", "reference": result.baseline.baseline_method},
        {"layer": "kpi_lineage_pointer",
         "reference": f"see KPI_OBSERVATION evidence for kpi_id={result.kpi_id}, period={result.period}"},
    ]

    signal_type = EvidenceType.ANOMALY_SIGNAL
    _assert_populated(signal_type)
    signal_claim = (
        f"{result.kpi_id}'s {result.period} observation ({result.observed_value}) was assessed as "
        f"{result.materiality.verdict} materiality against a {result.baseline.baseline_method} baseline of "
        f"{result.baseline.baseline_value} (movement {result.movement.absolute}, {result.movement.percentage}%)."
    )
    signal = EvidenceObject(
        evidence_id=evidence_id_for("anomalysig", result.kpi_id, result.period, signal_type.value),
        evidence_type=signal_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[signal_type],
        claim=signal_claim,
        value=ValueSpec(value=result.materiality.score, unit="materiality_score_0_1"),
        time=TimeRange(start=result.period, end=result.period),
        dimensions={},
        confidence=_confidence_from(result.baseline.baseline_confidence),
        source=SourceInfo(system="anomaly_engine", component="anomaly.engine.detect", version=ADAPTER_VERSION),
        lineage=assembled_lineage,
        freshness=FreshnessInfo(event_time=result.period, processing_time=_now_iso()),
        quality=QualityInfo(
            coverage=result.data_quality.current_period_coverage,
            historical_sufficiency=(
                min(1.0, result.baseline.history_periods / result.baseline.minimum_history_required)
                if result.baseline.minimum_history_required else None
            ),
            source_reliability=1.0,
        ),
        security=SecurityInfo(classification=classification, trust_level=TrustLevel.TRUSTED_SYSTEM),
        metadata={
            "verdict": result.materiality.verdict, "score": result.materiality.score,
            "baseline_level": result.baseline.baseline_level, "downgraded": result.data_quality.downgraded,
        },
        created_at=_now_iso(),
    )

    stat_type = EvidenceType.STATISTICAL_RESULT
    _assert_populated(stat_type)
    stat_claim = (
        f"{result.kpi_id}'s {result.period} z-score was {result.statistical_signals.z_score} "
        f"(robust z-score {result.statistical_signals.robust_z_score}, percentile "
        f"{result.statistical_signals.percentile}) relative to its baseline distribution."
    )
    statistical = EvidenceObject(
        evidence_id=evidence_id_for("statresult", result.kpi_id, result.period, stat_type.value),
        evidence_type=stat_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[stat_type],
        claim=stat_claim,
        value=ValueSpec(value=result.statistical_signals.z_score, unit="z_score"),
        time=TimeRange(start=result.period, end=result.period),
        dimensions={},
        confidence=Confidence.HIGH if result.statistical_signals.signals_agree else Confidence.MEDIUM,
        source=SourceInfo(system="anomaly_engine", component="anomaly.statistics", version=ADAPTER_VERSION),
        lineage=assembled_lineage,
        freshness=FreshnessInfo(event_time=result.period, processing_time=_now_iso()),
        quality=QualityInfo(coverage=result.data_quality.current_period_coverage, source_reliability=1.0),
        security=SecurityInfo(classification=classification, trust_level=TrustLevel.TRUSTED_SYSTEM),
        metadata={
            "robust_z_score": result.statistical_signals.robust_z_score,
            "percentile": result.statistical_signals.percentile,
            "signals_agree": result.statistical_signals.signals_agree,
        },
        created_at=_now_iso(),
    )
    return [signal, statistical]


# ---------------------------------------------------------------------------
# DriverContribution (PVM) -> DRIVER_CONTRIBUTION
# ---------------------------------------------------------------------------

def driver_contribution_to_evidence(d: DriverContribution, kpi_id: str, base_lineage: list[dict[str, str]],
                                     registry: Any) -> EvidenceObject:
    evidence_type = EvidenceType.DRIVER_CONTRIBUTION
    _assert_populated(evidence_type)
    pct = d.contribution_pct_of_change
    pct_str = f"{pct:+.1f}% of total change" if pct is not None else "an undefined share of total change"
    claim = (
        f"The {d.driver} effect contributed {d.contribution_value:+.2f} to the {kpi_id} change from "
        f"{d.period_previous} to {d.period_current} ({pct_str}), via {d.method} decomposition."
    )
    return EvidenceObject(
        evidence_id=evidence_id_for("driver", kpi_id, d.period_previous, d.period_current, d.driver),
        evidence_type=evidence_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[evidence_type],
        claim=claim,
        value=ValueSpec(value=d.contribution_value, unit="BRL"),
        time=TimeRange(start=d.period_previous, end=d.period_current),
        dimensions={"driver": d.driver, "direction": d.direction},
        confidence=_confidence_from(d.confidence),
        source=SourceInfo(system="driver_engine", component="drivers.pvm.compute_pvm_bridge",
                           version=ADAPTER_VERSION),
        lineage=[dict(item) for item in (d.lineage or base_lineage)],
        freshness=FreshnessInfo(event_time=d.period_current, processing_time=_now_iso()),
        quality=QualityInfo(source_reliability=1.0),
        security=SecurityInfo(classification=_classification_for_kpi(registry, kpi_id),
                               trust_level=TrustLevel.TRUSTED_SYSTEM),
        metadata={"contribution_pct_of_change": d.contribution_pct_of_change, "method": d.method,
                  "evidence_type_source": d.evidence_type},
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# SegmentContribution -> SEGMENT_CONTRIBUTION
# ---------------------------------------------------------------------------

def segment_contribution_to_evidence(s: SegmentContribution, kpi_id: str, period_current: str,
                                      period_previous: str, base_lineage: list[dict[str, str]],
                                      registry: Any) -> EvidenceObject:
    evidence_type = EvidenceType.SEGMENT_CONTRIBUTION
    _assert_populated(evidence_type)
    dim = registry.get_dimension(kpi_id, s.segment_type)
    classification = SecurityClassification(dim["security_classification"]) if dim else \
        _classification_for_kpi(registry, kpi_id)
    share_str = f"{s.share_of_total_movement:.2f}% of the total movement" if s.share_of_total_movement is not None \
        else "an undefined share of the total movement"
    claim = (
        f"{s.segment_value} ({s.segment_type}) moved from {s.previous_value} to {s.current_value} between "
        f"{period_previous} and {period_current}, an absolute change of {s.absolute_change:+.2f} ({share_str})."
    )
    return EvidenceObject(
        evidence_id=evidence_id_for("segment", kpi_id, s.segment_type, s.segment_value, period_previous,
                                     period_current),
        evidence_type=evidence_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[evidence_type],
        claim=claim,
        value=ValueSpec(value=s.absolute_change, unit="BRL"),
        time=TimeRange(start=period_previous, end=period_current),
        dimensions={"segment_type": s.segment_type, "segment_value": s.segment_value},
        confidence=_confidence_from(s.confidence),
        source=SourceInfo(system="driver_engine", component="drivers.contribution.compute_segment_contributions",
                           version=ADAPTER_VERSION),
        lineage=[dict(item) for item in base_lineage] + [
            {"layer": "segment_method", "reference": s.method},
        ],
        freshness=FreshnessInfo(event_time=period_current, processing_time=_now_iso()),
        quality=QualityInfo(source_reliability=1.0),
        security=SecurityInfo(classification=classification, trust_level=TrustLevel.TRUSTED_SYSTEM),
        metadata={"rank": s.rank, "sample_size": s.sample_size, "history_periods": s.history_periods,
                  "percentage_change": s.percentage_change},
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# ConcurrentKPIMovement -> CONCURRENT_KPI
# ---------------------------------------------------------------------------

def concurrent_kpi_to_evidence(kpi_id: str, movement: ConcurrentKPIMovement, period_current: str,
                                period_previous: str, registry: Any) -> EvidenceObject:
    evidence_type = EvidenceType.CONCURRENT_KPI
    _assert_populated(evidence_type)
    pct_str = f"{movement.percentage_change:+.2f}%" if movement.percentage_change is not None else \
        "an undefined percentage change"
    claim = (
        f"{kpi_id} moved from {movement.previous_value} to {movement.current_value} between {period_previous} "
        f"and {period_current} ({pct_str}), reported as concurrent context only, not combined into a "
        f"conclusion about any other KPI's movement."
    )
    return EvidenceObject(
        evidence_id=evidence_id_for("concurrent", kpi_id, period_previous, period_current),
        evidence_type=evidence_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[evidence_type],
        claim=claim,
        value=ValueSpec(value=movement.absolute_change, unit=None),
        time=TimeRange(start=period_previous, end=period_current),
        dimensions={},
        confidence=Confidence.UNKNOWN,  # ConcurrentKPIMovement carries no data_quality of its own
        source=SourceInfo(system="kpi_engine", component="kpi.engine.KPIEngine.compare_periods",
                           version=ADAPTER_VERSION),
        lineage=list(registry.get_lineage_chain(kpi_id)),
        freshness=FreshnessInfo(event_time=period_current, processing_time=_now_iso()),
        quality=QualityInfo(source_reliability=1.0),
        security=SecurityInfo(classification=_classification_for_kpi(registry, kpi_id),
                               trust_level=TrustLevel.TRUSTED_SYSTEM),
        metadata={"previous_value": movement.previous_value, "current_value": movement.current_value},
        created_at=_now_iso(),
    )


# ---------------------------------------------------------------------------
# Top-level convenience: fan out an entire DriverDecompositionResult
# ---------------------------------------------------------------------------

def driver_decomposition_result_to_evidence_bundle(result: DriverDecompositionResult,
                                                     registry: Any) -> list[EvidenceObject]:
    """The one function engine.py calls per DriverDecompositionResult. Fans
    drivers + every segment_contributions[...] + every concurrent_kpis[...]
    out into a flat list, calling the functions above -- never recomputing
    anything result itself doesn't already carry."""
    kpi_id = result.kpi_id
    base_lineage = [dict(item) for item in result.lineage]
    bundle: list[EvidenceObject] = []

    for d in result.drivers:
        bundle.append(driver_contribution_to_evidence(d, kpi_id, base_lineage, registry))

    for contributions in result.segment_contributions.values():
        for s in contributions:
            bundle.append(segment_contribution_to_evidence(
                s, kpi_id, result.period_current, result.period_previous, base_lineage, registry))

    for concurrent_kpi_id, movement in result.concurrent_kpis.items():
        bundle.append(concurrent_kpi_to_evidence(
            concurrent_kpi_id, movement, result.period_current, result.period_previous, registry))

    return bundle
