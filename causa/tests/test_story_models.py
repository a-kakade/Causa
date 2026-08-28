"""Step 8: story.models dataclass shape tests -- __post_init__ causal-
language rejection, to_dict() round-trips. Pure synthetic, no fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest  # noqa: E402

from story.models import (  # noqa: E402
    ClaimType,
    EvidenceItem,
    EvidencePackage,
    GeneratedBy,
    KPIStory,
    NarrativeClaim,
    NarrativePlan,
    NarrativePlanSection,
    NumericClaim,
    Persona,
    StorySection,
    ValidationStatus,
    VerificationResult,
)


def _evidence_item(**overrides):
    defaults = dict(
        evidence_id="EV001", metric="revenue", value=52.1, unit="percent", direction="increase",
        period="2017-11", source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00",
        analytical_method="period_over_period_change", confidence="HIGH", claim_type=ClaimType.FACT,
    )
    defaults.update(overrides)
    return EvidenceItem(**defaults)


def test_evidence_item_to_dict_round_trips_basic_fields():
    item = _evidence_item()
    d = item.to_dict()
    assert d["evidence_id"] == "EV001"
    assert d["value"] == 52.1
    assert d["claim_type"] == "FACT"


def test_evidence_item_confidence_handles_categorical_and_numeric():
    categorical = _evidence_item(confidence="HIGH")
    numeric = _evidence_item(confidence=0.78)
    assert categorical.to_dict()["confidence"] == "HIGH"
    assert numeric.to_dict()["confidence"] == 0.78


def test_evidence_package_get_and_all_ids():
    items = [_evidence_item(evidence_id="EV001"), _evidence_item(evidence_id="EV002", metric="orders")]
    package = EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=items)
    assert package.get("EV001") is not None
    assert package.get("EV999") is None
    assert package.all_ids() == {"EV001", "EV002"}


def test_narrative_claim_rejects_causal_language_at_construction():
    with pytest.raises(ValueError):
        NarrativeClaim(text="Delivery deterioration caused the review decline.", claim_type=ClaimType.ASSOCIATION,
                        evidence_ids=["EV001"])


def test_narrative_claim_accepts_hedged_language():
    claim = NarrativeClaim(text="Delivery deterioration coincided with lower review scores.",
                            claim_type=ClaimType.ASSOCIATION, evidence_ids=["EV001"])
    assert claim.validation_status == ValidationStatus.PENDING


def test_narrative_claim_to_dict_includes_numeric_claims():
    numeric = NumericClaim(raw_text="52.1%", normalized_value=52.1, unit="percent", matched_evidence_id="EV001",
                            status=ValidationStatus.APPROVED)
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"],
                            numeric_claims=[numeric])
    d = claim.to_dict()
    assert d["numeric_claims"][0]["normalized_value"] == 52.1
    assert d["numeric_claims"][0]["status"] == "APPROVED"


def test_story_section_to_dict():
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    section = StorySection(title="What happened", statements=[claim])
    d = section.to_dict()
    assert d["title"] == "What happened"
    assert len(d["statements"]) == 1


def test_narrative_plan_to_dict():
    plan = NarrativePlan(persona=Persona.EXECUTIVE,
                          sections=[NarrativePlanSection(title="What happened", evidence_ids=["EV001"])])
    d = plan.to_dict()
    assert d["persona"] == "EXECUTIVE"
    assert d["sections"][0]["evidence_ids"] == ["EV001"]


def test_verification_result_to_dict():
    result = VerificationResult(status=ValidationStatus.APPROVED, claims_checked=5, claims_rejected=0)
    assert result.to_dict()["status"] == "APPROVED"


def test_kpi_story_to_dict_full_shape():
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    section = StorySection(title="What happened", statements=[claim])
    verification = VerificationResult(status=ValidationStatus.APPROVED, claims_checked=1, claims_rejected=0)
    story = KPIStory(
        persona=Persona.EXECUTIVE, headline="Revenue grew 52.1%.", sections=[section], verification=verification,
        generated_by=GeneratedBy.DETERMINISTIC_TEMPLATE, generated_at="2026-08-28T12:00:00+00:00",
        model_info={"provider": "deterministic_template"}, evidence_package_id="pkg1",
        evidence_package_version="1.0", evidence_package_hash="abc123", generation_attempts=1,
    )
    d = story.to_dict()
    assert d["persona"] == "EXECUTIVE"
    assert d["generated_by"] == "DETERMINISTIC_TEMPLATE"
    assert d["verification"]["status"] == "APPROVED"


def test_claim_type_rank_is_total_order_fact_strongest():
    from story.models import CLAIM_TYPE_RANK
    assert CLAIM_TYPE_RANK[ClaimType.FACT] > CLAIM_TYPE_RANK[ClaimType.ANALYTICAL_FINDING]
    assert CLAIM_TYPE_RANK[ClaimType.ANALYTICAL_FINDING] > CLAIM_TYPE_RANK[ClaimType.ASSOCIATION]
    assert CLAIM_TYPE_RANK[ClaimType.ASSOCIATION] > CLAIM_TYPE_RANK[ClaimType.HYPOTHESIS]
    assert CLAIM_TYPE_RANK[ClaimType.HYPOTHESIS] > CLAIM_TYPE_RANK[ClaimType.UNKNOWN]
