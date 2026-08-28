"""Step 8: evidence_package.py tests -- valid evidence accepted, duplicate
IDs rejected, _infer_claim_type mapping pinned, empty package valid.

Builds REAL evidence.schema.EvidenceObject / causal.models.CausalResult /
decision.models.ActionRecommendation instances by hand (no canonical data),
matching the demo/test convention confirmed with the user.
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest  # noqa: E402

from causal.models import (  # noqa: E402
    CausalMethod,
    CausalResult,
    CausalStatus,
    CausalTier,
    EligibilityReport,
    EligibilityVerdict,
)
from decision.models import (  # noqa: E402
    ActionRecommendation,
    ConstraintStatus,
    ConstraintSeverity,
    DataSource,
    ExpectedImpact,
    GeneratedBy as DecisionGeneratedBy,
    RecommendationTier,
    ScoreBreakdown,
)
from evidence.models import Confidence, EvidenceTier, EvidenceType, SecurityClassification, TrustLevel  # noqa: E402
from evidence.schema import (  # noqa: E402
    EvidenceObject,
    FreshnessInfo,
    QualityInfo,
    SecurityInfo,
    SourceInfo,
    TimeRange,
    ValueSpec,
)

from story.evidence_package import (  # noqa: E402
    EvidencePackageError,
    build_evidence_package,
    evidence_item_from_action_recommendation,
    evidence_item_from_causal_result,
    evidence_item_from_evidence_object,
)
from story.models import ClaimType  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _evidence_object(evidence_id, evidence_type, evidence_tier, value, unit, metric="revenue"):
    return EvidenceObject(
        evidence_id=evidence_id, evidence_type=evidence_type, evidence_tier=evidence_tier,
        claim=f"{metric} was {value}{unit or ''}.", value=ValueSpec(value=value, unit=unit),
        time=TimeRange(start="2017-10-01", end="2017-11-30"),
        dimensions={"metric": metric, "direction": "increase"}, confidence=Confidence.HIGH,
        source=SourceInfo(system="kpi_engine", component="kpi.engine.KPIEngine.compare_periods"),
        freshness=FreshnessInfo(processing_time=_now()), quality=QualityInfo(),
        security=SecurityInfo(classification=SecurityClassification.PUBLIC_ANALYTICAL, trust_level=TrustLevel.TRUSTED_SYSTEM),
        created_at=_now(),
    )


def _causal_result(status, tier, hypothesis_id="H1"):
    eligibility = EligibilityReport(hypothesis_id=hypothesis_id, verdict=EligibilityVerdict.ELIGIBLE, checks=[])
    return CausalResult(
        hypothesis_id=hypothesis_id, method=CausalMethod.DESCRIPTIVE_ASSOCIATION, evidence_tier=tier, status=status,
        estimate={"value": 5.2}, uncertainty=None, assumptions=["association does not imply causation"],
        diagnostics=[], confounders=[], evidence_ids=["EV001"], limitations=["limited sample"],
        causal_claim_allowed=False, eligibility_report=eligibility,
    )


def _action_recommendation():
    impact = ExpectedImpact(
        metric="on_time_delivery_rate", estimated_effect=0.06, effect_unit="pp", addressable_population=12500,
        confidence=0.78, calculated_impact=585.0, revenue_impact=None, effect_source=DataSource.HISTORICAL_ESTIMATE.value,
        population_source=DataSource.HISTORICAL_ESTIMATE.value, confidence_basis="test", is_estimable=True,
    )
    breakdown = ScoreBreakdown(
        confidence_factors={}, confidence_weights={}, confidence_score=0.78, controllability_score=0.9,
        controllability_basis="test", effort_score=0.2, effort_basis="test",
        priority_formula="impact * confidence * controllability / effort", priority_score=100.0,
    )
    return ActionRecommendation(
        recommendation_id="rec_delivery_delay_expedite", driver="delivery_delay",
        driver_category="FULFILLMENT_LOGISTICS", controllable_lever="shipment_prioritization",
        possible_action="Expedite high-risk shipments.", expected_impact=impact, owner="Operations Manager",
        constraints=[], controllability=0.9, effort=0.2, priority_score=100.0, monitoring_kpis=[],
        rationale="delivery_delay is associated with a movement in on_time_delivery_rate.",
        assumptions=["assumption"], score_breakdown=breakdown, tier=RecommendationTier.TOP,
        ranking_explanation=["ranked #1"], action_justified_by_evidence=False,
        generated_by=DecisionGeneratedBy.DETERMINISTIC_TEMPLATE, source_driver_signal_id="sig1",
    )


# -- claim type inference mapping (pinned) -----------------------------------

def test_kpi_movement_t1_maps_to_fact():
    obj = _evidence_object("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 52.1, "percent")
    item = evidence_item_from_evidence_object(obj)
    assert item.claim_type == ClaimType.FACT


def test_driver_contribution_t2_maps_to_analytical_finding():
    obj = _evidence_object("EV004", EvidenceType.DRIVER_CONTRIBUTION, EvidenceTier.T2_ARITHMETIC, 417000.0, "BRL",
                            metric="volume")
    item = evidence_item_from_evidence_object(obj)
    assert item.claim_type == ClaimType.ANALYTICAL_FINDING


def test_anomaly_signal_t3_maps_to_association():
    obj = _evidence_object("EV006", EvidenceType.ANOMALY_SIGNAL, EvidenceTier.T3_STATISTICAL, 0.8, "materiality_score_0_1",
                            metric="on_time_delivery_rate")
    item = evidence_item_from_evidence_object(obj)
    assert item.claim_type == ClaimType.ASSOCIATION


def test_concurrent_kpi_maps_to_association():
    obj = _evidence_object("EV008", EvidenceType.CONCURRENT_KPI, EvidenceTier.T1_DESCRIPTIVE, -5.2, "percent",
                            metric="avg_review_score")
    item = evidence_item_from_evidence_object(obj)
    assert item.claim_type == ClaimType.ASSOCIATION


def test_customer_review_maps_to_fact():
    obj = _evidence_object("EV007", EvidenceType.CUSTOMER_REVIEW, EvidenceTier.T1_DESCRIPTIVE, None, None,
                            metric="avg_review_score")
    item = evidence_item_from_evidence_object(obj)
    assert item.claim_type == ClaimType.FACT


def test_causal_supported_maps_to_analytical_finding_never_fact_of_causation():
    result = _causal_result(CausalStatus.CAUSAL_SUPPORTED, CausalTier.T3_QUASI_EXPERIMENTAL)
    item = evidence_item_from_causal_result(result, "revenue", "2017-11")
    assert item.claim_type == ClaimType.ANALYTICAL_FINDING


def test_causal_descriptive_only_maps_to_fact():
    result = _causal_result(CausalStatus.DESCRIPTIVE_ONLY, CausalTier.T1_DESCRIPTIVE)
    item = evidence_item_from_causal_result(result, "revenue", "2017-11")
    assert item.claim_type == ClaimType.FACT


def test_causal_insufficient_maps_to_hypothesis():
    result = _causal_result(CausalStatus.CAUSAL_INSUFFICIENT, CausalTier.T1_DESCRIPTIVE)
    item = evidence_item_from_causal_result(result, "revenue", "2017-11")
    assert item.claim_type == ClaimType.HYPOTHESIS


def test_causal_rejected_maps_to_unknown():
    result = _causal_result(CausalStatus.CAUSAL_REJECTED, CausalTier.T1_DESCRIPTIVE)
    item = evidence_item_from_causal_result(result, "revenue", "2017-11")
    assert item.claim_type == ClaimType.UNKNOWN


# -- number/value fidelity ---------------------------------------------------

def test_evidence_item_value_copied_verbatim_never_recomputed():
    obj = _evidence_object("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 52.1, "percent")
    item = evidence_item_from_evidence_object(obj)
    assert item.value == 52.1
    assert item.unit == "percent"


def test_action_recommendation_wrapped_verbatim():
    rec = _action_recommendation()
    item = evidence_item_from_action_recommendation(rec)
    assert item.evidence_id == "rec_delivery_delay_expedite"
    assert item.value == 585.0
    assert item.confidence == 0.78
    assert item.source_recommendation is rec


# -- package building ---------------------------------------------------------

def test_build_evidence_package_accepts_valid_objects():
    objs = [_evidence_object("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 52.1, "percent")]
    package = build_evidence_package(kpi_id="revenue", period="2017-11", evidence_objects=objs)
    assert package.get("EV001") is not None
    assert package.content_hash


def test_build_evidence_package_rejects_duplicate_evidence_id():
    objs = [
        _evidence_object("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 52.1, "percent"),
        _evidence_object("EV001", EvidenceType.KPI_OBSERVATION, EvidenceTier.T1_DESCRIPTIVE, 10.0, "percent"),
    ]
    with pytest.raises(EvidencePackageError):
        build_evidence_package(kpi_id="revenue", period="2017-11", evidence_objects=objs)


def test_build_evidence_package_rejects_duplicate_recommendation_id():
    rec = _action_recommendation()
    with pytest.raises(EvidencePackageError):
        build_evidence_package(kpi_id="revenue", period="2017-11", recommendations=[rec, rec])


def test_empty_evidence_package_is_valid():
    package = build_evidence_package(kpi_id="revenue", period="2017-11")
    assert package.items == []
    assert package.all_ids() == set()


def test_package_includes_causal_results_and_recommendations():
    objs = [_evidence_object("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 52.1, "percent")]
    causal = [(_causal_result(CausalStatus.DESCRIPTIVE_ONLY, CausalTier.T1_DESCRIPTIVE), "revenue", "2017-11")]
    rec = _action_recommendation()
    package = build_evidence_package(kpi_id="revenue", period="2017-11", evidence_objects=objs,
                                      causal_results=causal, recommendations=[rec])
    assert package.get("EV001") is not None
    assert package.get("H1") is not None
    assert rec.recommendation_id in package.recommendation_ids()


def test_content_hash_changes_when_items_change():
    objs_a = [_evidence_object("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 52.1, "percent")]
    objs_b = [_evidence_object("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 99.9, "percent")]
    package_a = build_evidence_package(kpi_id="revenue", period="2017-11", evidence_objects=objs_a)
    package_b = build_evidence_package(kpi_id="revenue", period="2017-11", evidence_objects=objs_b)
    assert package_a.content_hash != package_b.content_hash
