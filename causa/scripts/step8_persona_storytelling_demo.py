"""
step8_persona_storytelling_demo.py — builds a demo EvidencePackage from the
task's own exact example numbers (Revenue +52.1%, Orders +62.9%, AOV
-6.75%, Volume +R$417K, Mix -R$75.9K, Delivery +27.9%, Reviews -5.2%) plus
one Step 7-shaped ActionRecommendation, generates a KPIStory for all 4
required personas (Executive/Finance/Operations/Marketing) with
llm_client=None (deterministic, reproducible, no live API dependency for
the primary run -- matching scripts/step7_decision_engine_demo.py's own
precedent), runs the Step 8 pytest suite, and writes
reports/step8_validation.json.

Demonstrates that same evidence + different persona = different narrative,
while every numeric fact stays identical (and independently re-verified)
across all 4 stories.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
import time
from datetime import timezone
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

TEST_FILES = [
    "tests/test_story_models.py", "tests/test_persona_engine.py", "tests/test_evidence_package.py",
    "tests/test_language_rules.py", "tests/test_numeric_verifier.py", "tests/test_claim_verifier.py",
    "tests/test_narrative_planner.py", "tests/test_narrative_generator.py", "tests/test_story_retry.py",
    "tests/test_story_step7_integration.py", "tests/test_story_end_to_end.py",
]


def _now() -> str:
    return datetime.datetime.now(timezone.utc).isoformat()


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


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TEST_FILES, "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
            "failed_tests": failed, "all_passed": proc.returncode == 0}


def main() -> None:
    t_start = time.time()
    persona_engine = PersonaEngine.load()
    persona_engine.validate()
    config = StorytellingConfig.load()

    package = _demo_package()
    stories = {
        persona: generate_kpi_story(persona, package, persona_engine=persona_engine, config=config, llm_client=None)
        for persona in Persona
    }
    run_seconds = round(time.time() - t_start, 2)

    all_verified = all(story.verification.status == ValidationStatus.APPROVED for story in stories.values())
    section_titles = {p.value: [s.title for s in story.sections] for p, story in stories.items()}
    personas_differ = len({tuple(v) for v in section_titles.values()}) > 1

    value_checks = {
        "all_four_personas_generated": len(stories) == 4,
        "all_stories_verified_approved": all_verified,
        "personas_produce_different_section_ordering": personas_differ,
        "executive_story_present": Persona.EXECUTIVE in stories,
        "finance_story_present": Persona.FINANCE in stories,
        "operations_story_present": Persona.OPERATIONS in stories,
        "marketing_story_present": Persona.MARKETING in stories,
    }
    value_checks["all_checks_pass"] = all(value_checks.values())

    test_results = run_tests()

    report = {
        "generated_at": datetime.datetime.now(timezone.utc).isoformat(),
        "run_seconds": run_seconds,
        "required_value_checks": value_checks,
        "evidence_package": package.to_dict(),
        "stories": {persona.value: story.to_dict() for persona, story in stories.items()},
        "tests": test_results,
    }

    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "step8_validation.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"Step 8 demo complete in {run_seconds}s. Report written to {report_path}\n")
    for persona, story in stories.items():
        print(f"=== {persona.value} ===")
        print(f"Headline: {story.headline}")
        for section in story.sections:
            if section.statements:
                print(f"  [{section.title}]")
                for stmt in section.statements:
                    print(f"    - {stmt.text}")
        print(f"Verification: {story.verification.status.value} "
              f"({story.verification.claims_checked} checked, {story.verification.claims_rejected} rejected)")
        print()

    print(f"Required value checks all pass: {value_checks['all_checks_pass']}")
    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed "
          f"(all_passed={test_results['all_passed']})")

    if not value_checks["all_checks_pass"] or not test_results["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
