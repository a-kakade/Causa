"""Step 8: end-to-end test -- all 4 personas generate from one shared demo
EvidencePackage; same numeric facts appear (in varying phrasing) across all
4; headline/ordering/detail level differ per persona."""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.models import (  # noqa: E402
    ActionRecommendation,
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

from story.config import StorytellingConfig  # noqa: E402
from story.engine import generate_kpi_story  # noqa: E402
from story.evidence_package import build_evidence_package  # noqa: E402
from story.models import Persona, ValidationStatus  # noqa: E402
from story.persona import PersonaEngine  # noqa: E402


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _obj(evidence_id, evidence_type, evidence_tier, value, unit, metric, direction="increase"):
    return EvidenceObject(
        evidence_id=evidence_id, evidence_type=evidence_type, evidence_tier=evidence_tier,
        claim=f"{metric} was {value}{unit or ''}.", value=ValueSpec(value=value, unit=unit),
        time=TimeRange(start="2017-10-01", end="2017-11-30"),
        dimensions={"metric": metric, "direction": direction}, confidence=Confidence.HIGH,
        source=SourceInfo(system="kpi_engine", component="kpi.engine.KPIEngine.compare_periods"),
        freshness=FreshnessInfo(processing_time=_now()), quality=QualityInfo(),
        security=SecurityInfo(classification=SecurityClassification.PUBLIC_ANALYTICAL, trust_level=TrustLevel.TRUSTED_SYSTEM),
        created_at=_now(),
    )


def _demo_package():
    """The task's own example numbers: Revenue +52.1%, Orders +62.9%, AOV
    -6.75%, Volume +R$417K, Mix -R$75.9K, Delivery +27.9%, Reviews -5.2%."""
    objs = [
        _obj("EV001", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 52.1, "percent", "revenue"),
        _obj("EV002", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, 62.9, "percent", "orders"),
        _obj("EV003", EvidenceType.KPI_MOVEMENT, EvidenceTier.T1_DESCRIPTIVE, -6.75, "percent", "aov", "decrease"),
        _obj("EV004", EvidenceType.DRIVER_CONTRIBUTION, EvidenceTier.T2_ARITHMETIC, 417000.0, "BRL", "volume"),
        _obj("EV005", EvidenceType.DRIVER_CONTRIBUTION, EvidenceTier.T2_ARITHMETIC, -75900.0, "BRL", "mix", "decrease"),
        _obj("EV006", EvidenceType.ANOMALY_SIGNAL, EvidenceTier.T3_STATISTICAL, 27.9, "percent",
             "on_time_delivery_rate", "decrease"),
        _obj("EV007", EvidenceType.CONCURRENT_KPI, EvidenceTier.T1_DESCRIPTIVE, -5.2, "percent",
             "avg_review_score", "decrease"),
    ]
    impact = ExpectedImpact(
        metric="on_time_delivery_rate", estimated_effect=0.06, effect_unit="pp", addressable_population=12500,
        confidence=0.78, calculated_impact=585.0, revenue_impact=None,
        effect_source=DataSource.HISTORICAL_ESTIMATE.value, population_source=DataSource.HISTORICAL_ESTIMATE.value,
        confidence_basis="test", is_estimable=True,
    )
    breakdown = ScoreBreakdown(
        confidence_factors={}, confidence_weights={}, confidence_score=0.78, controllability_score=0.9,
        controllability_basis="test", effort_score=0.2, effort_basis="test",
        priority_formula="impact * confidence * controllability / effort", priority_score=1679.5,
    )
    rec = ActionRecommendation(
        recommendation_id="rec_delivery_delay_expedite", driver="delivery_delay",
        driver_category="FULFILLMENT_LOGISTICS", controllable_lever="shipment_prioritization",
        possible_action="Expedite high-risk shipments.", expected_impact=impact, owner="Operations Manager",
        constraints=[], controllability=0.9, effort=0.2, priority_score=1679.5, monitoring_kpis=[],
        rationale="delivery_delay is associated with a movement in on_time_delivery_rate.",
        assumptions=["assumption"], score_breakdown=breakdown, tier=RecommendationTier.TOP,
        ranking_explanation=["ranked #1"], action_justified_by_evidence=False,
        generated_by=DecisionGeneratedBy.DETERMINISTIC_TEMPLATE, source_driver_signal_id="sig1",
    )
    return build_evidence_package(kpi_id="revenue", period="2017-11", evidence_objects=objs, recommendations=[rec])


def test_all_four_personas_generate_verified_stories():
    package = _demo_package()
    persona_engine = PersonaEngine.load()
    config = StorytellingConfig.load()

    stories = {
        persona: generate_kpi_story(persona, package, persona_engine=persona_engine, config=config, llm_client=None)
        for persona in Persona
    }

    for persona, story in stories.items():
        assert story.verification.status == ValidationStatus.APPROVED, f"{persona} story failed verification"
        assert story.evidence_package_hash == package.content_hash


def test_all_personas_preserve_the_same_trusted_numbers():
    package = _demo_package()
    persona_engine = PersonaEngine.load()
    config = StorytellingConfig.load()

    for persona in Persona:
        story = generate_kpi_story(persona, package, persona_engine=persona_engine, config=config, llm_client=None)
        all_text = " ".join(s.text for section in story.sections for s in section.statements)
        # Every numeric claim across the whole story must have matched real trusted evidence --
        # verified indirectly via story.verification.status == APPROVED (checked in the other test),
        # and directly here by re-extracting and matching every number mentioned anywhere in the story.
        from story.numeric_verifier import build_evidence_value_index, extract_and_normalize_numeric_claims, \
            match_numeric_claim
        index = build_evidence_value_index(package)
        for claim in extract_and_normalize_numeric_claims(all_text):
            matched = match_numeric_claim(claim, index, config.numeric_tolerance(), config.numeric_absolute_floor())
            assert matched.status == ValidationStatus.APPROVED, \
                f"{persona}: {claim.raw_text} did not match trusted evidence"


def test_different_personas_produce_different_headlines_or_content():
    package = _demo_package()
    persona_engine = PersonaEngine.load()
    config = StorytellingConfig.load()

    stories = {
        persona: generate_kpi_story(persona, package, persona_engine=persona_engine, config=config, llm_client=None)
        for persona in Persona
    }
    section_title_sets = {persona: tuple(s.title for s in story.sections) for persona, story in stories.items()}
    # At least two personas must have differently-ordered/titled sections (proving persona actually matters).
    assert len(set(section_title_sets.values())) > 1


def test_operations_story_includes_delivery_evidence_executive_story_may_not():
    package = _demo_package()
    persona_engine = PersonaEngine.load()
    config = StorytellingConfig.load()

    ops_story = generate_kpi_story(Persona.OPERATIONS, package, persona_engine=persona_engine, config=config,
                                    llm_client=None)
    ops_evidence_ids = {eid for section in ops_story.sections for s in section.statements for eid in s.evidence_ids}
    assert "EV006" in ops_evidence_ids  # delivery anomaly signal present in operations story


def test_finance_story_never_invents_margin_evidence():
    package = _demo_package()
    persona_engine = PersonaEngine.load()
    config = StorytellingConfig.load()

    finance_story = generate_kpi_story(Persona.FINANCE, package, persona_engine=persona_engine, config=config,
                                        llm_client=None)
    all_text = " ".join(s.text for section in finance_story.sections for s in section.statements).lower()
    assert "margin" not in all_text  # no margin evidence exists in the package -- deterministic template never invents it
