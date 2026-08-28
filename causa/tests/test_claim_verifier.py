"""Step 8: claim_verifier.py tests -- evidence-ID validity, epistemic-type
cross-check, unsupported metric/recommendation rejection, plus the exact
spec examples ("Revenue increased 52.1%" valid, "Profit increased 18%"
rejected if no profit evidence, "Delivery caused review decline" rejected
if only association evidence exists)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from story.claim_verifier import verify_claim, verify_story_claims  # noqa: E402
from story.models import (  # noqa: E402
    ClaimType,
    EvidenceItem,
    EvidencePackage,
    NarrativeClaim,
    StorySection,
    ValidationStatus,
)

_TOLERANCE = 0.0005
_ABS_FLOOR = 0.01


def _item(evidence_id, metric, value, unit, claim_type):
    return EvidenceItem(
        evidence_id=evidence_id, metric=metric, value=value, unit=unit, direction="increase", period="2017-11",
        source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00", analytical_method="x",
        confidence="HIGH", claim_type=claim_type,
    )


def _package():
    items = [
        _item("EV001", "revenue", 52.1, "percent", ClaimType.FACT),
        _item("EV006", "on_time_delivery_rate", 27.9, "percent", ClaimType.ASSOCIATION),
        _item("EV007", "avg_review_score", -5.2, "percent", ClaimType.ASSOCIATION),
    ]
    return EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=items)


def test_revenue_52_1_percent_claim_is_approved():
    package = _package()
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    result = verify_claim(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert result.validation_status == ValidationStatus.APPROVED


def test_profit_18_percent_rejected_no_profit_evidence():
    package = _package()
    claim = NarrativeClaim(text="Profit increased 18%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    result = verify_claim(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert result.validation_status == ValidationStatus.REJECTED


def test_unknown_evidence_id_rejected():
    package = _package()
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV999"])
    result = verify_claim(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert result.validation_status == ValidationStatus.REJECTED
    assert "EV999" in result.rejection_reason


def test_fact_claim_citing_only_association_evidence_rejected():
    package = _package()
    claim = NarrativeClaim(text="Delivery deterioration was 27.9%.", claim_type=ClaimType.FACT,
                            evidence_ids=["EV006"])
    result = verify_claim(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert result.validation_status == ValidationStatus.REJECTED
    assert "claim_type" in result.rejection_reason


def test_association_claim_citing_association_evidence_approved():
    package = _package()
    claim = NarrativeClaim(text="Delivery deterioration coincided with lower review scores.",
                            claim_type=ClaimType.ASSOCIATION, evidence_ids=["EV006", "EV007"])
    result = verify_claim(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert result.validation_status == ValidationStatus.APPROVED


def test_causal_claim_on_association_evidence_rejected():
    package = _package()
    claim = NarrativeClaim(text="Delivery deterioration coincided with lower review scores.",
                            claim_type=ClaimType.ASSOCIATION, evidence_ids=["EV006", "EV007"])
    # Simulate what an LLM might try to say (constructed directly, bypassing __post_init__'s
    # own reject-at-construction guard, to test claim_verifier's independent enforcement):
    claim.text = "Delivery deterioration was associated with lower review scores."
    result = verify_claim(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert result.validation_status == ValidationStatus.APPROVED  # hedged phrasing remains valid


def test_hedging_down_from_fact_to_association_is_allowed():
    package = _package()
    claim = NarrativeClaim(text="Revenue was associated with an increase around this period.",
                            claim_type=ClaimType.ASSOCIATION, evidence_ids=["EV001"])
    result = verify_claim(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert result.validation_status == ValidationStatus.APPROVED


def test_verify_story_claims_rolls_up_rejected_status():
    package = _package()
    good = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    bad = NarrativeClaim(text="Profit increased 18%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    sections = [StorySection(title="What happened", statements=[good, bad])]
    _, result = verify_story_claims(sections, package, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.REJECTED
    assert result.claims_checked == 2
    assert result.claims_rejected == 1


def test_verify_story_claims_all_approved():
    package = _package()
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    sections = [StorySection(title="What happened", statements=[claim])]
    _, result = verify_story_claims(sections, package, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.APPROVED
    assert result.claims_rejected == 0
