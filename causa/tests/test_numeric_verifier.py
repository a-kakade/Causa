"""Step 8: numeric_verifier.py tests -- the exact spec examples: 52.1% vs
52.1% pass; 52.10% vs 52.1% pass; 57% vs 52.1% fail (reason cites 52.1);
R$417K vs 417000 pass; unsupported number fail; 5.2% never confused with
52%."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from story.models import ClaimType, EvidenceItem, EvidencePackage, NarrativeClaim, ValidationStatus  # noqa: E402
from story.numeric_verifier import (  # noqa: E402
    build_evidence_value_index,
    extract_and_normalize_numeric_claims,
    match_numeric_claim,
    verify_numeric_claims,
)

_TOLERANCE = 0.0005
_ABS_FLOOR = 0.01


def _item(evidence_id, metric, value, unit):
    return EvidenceItem(
        evidence_id=evidence_id, metric=metric, value=value, unit=unit, direction="increase", period="2017-11",
        source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00", analytical_method="x",
        confidence="HIGH", claim_type=ClaimType.FACT,
    )


def _package():
    items = [
        _item("EV001", "revenue", 52.1, "percent"),
        _item("EV002", "orders", 62.9, "percent"),
        _item("EV003", "aov", -6.75, "percent"),
        _item("EV004", "volume", 417000.0, "BRL"),
        _item("EV005", "mix", -75900.0, "BRL"),
    ]
    return EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=items)


# -- extraction/normalization ---------------------------------------------------

def test_extract_percent_with_decimal():
    claims = extract_and_normalize_numeric_claims("Revenue increased 52.1%.")
    assert len(claims) == 1
    assert claims[0].normalized_value == 52.1
    assert claims[0].unit == "percent"


def test_extract_percent_with_trailing_decimal_zero_normalizes_same():
    a = extract_and_normalize_numeric_claims("Revenue increased 52.1%.")[0]
    b = extract_and_normalize_numeric_claims("Revenue increased 52.10%.")[0]
    assert a.normalized_value == b.normalized_value == 52.1


def test_extract_percent_with_leading_plus_sign():
    claims = extract_and_normalize_numeric_claims("Revenue grew +52.1% this period.")
    assert claims[0].normalized_value == 52.1


def test_extract_currency_with_k_suffix():
    claims = extract_and_normalize_numeric_claims("Volume contributed R$417K to the increase.")
    assert claims[0].normalized_value == 417000.0
    assert claims[0].unit == "BRL"


def test_extract_negative_currency_with_k_suffix():
    claims = extract_and_normalize_numeric_claims("Mix created a -R$75.9K headwind.")
    assert claims[0].normalized_value == -75900.0
    assert claims[0].unit == "BRL"


def test_5_2_percent_not_confused_with_52_percent():
    a = extract_and_normalize_numeric_claims("Reviews declined 5.2%.")[0]
    b = extract_and_normalize_numeric_claims("Orders increased 52%.")[0]
    assert a.normalized_value == 5.2
    assert b.normalized_value == 52.0
    assert a.normalized_value != b.normalized_value


# -- matching (the exact spec examples) ---------------------------------------

def test_52_1_percent_matches_trusted_52_1_percent():
    package = _package()
    index = build_evidence_value_index(package)
    claim = extract_and_normalize_numeric_claims("Revenue increased 52.1%.")[0]
    result = match_numeric_claim(claim, index, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.APPROVED
    assert result.matched_evidence_id == "EV001"


def test_52_10_percent_matches_trusted_52_1_percent():
    package = _package()
    index = build_evidence_value_index(package)
    claim = extract_and_normalize_numeric_claims("Revenue increased 52.10%.")[0]
    result = match_numeric_claim(claim, index, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.APPROVED


def test_57_percent_does_not_match_trusted_52_1_percent():
    package = _package()
    index = build_evidence_value_index(package)
    claim = extract_and_normalize_numeric_claims("Revenue increased 57%.")[0]
    result = match_numeric_claim(claim, index, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.REJECTED
    assert "52.1" in result.rejection_reason


def test_r417k_matches_trusted_417000():
    package = _package()
    index = build_evidence_value_index(package)
    claim = extract_and_normalize_numeric_claims("Volume contributed R$417K.")[0]
    result = match_numeric_claim(claim, index, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.APPROVED
    assert result.matched_evidence_id == "EV004"


def test_unsupported_number_rejected_no_matching_evidence():
    package = _package()
    index = build_evidence_value_index(package)
    claim = extract_and_normalize_numeric_claims("Profit increased 18%.")[0]
    result = match_numeric_claim(claim, index, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.REJECTED
    assert "18" not in result.rejection_reason or "does not match" in result.rejection_reason


def test_currency_claim_never_matches_percent_evidence():
    package = _package()
    index = build_evidence_value_index(package)
    # 52.1 as a currency claim (bare $ marker) should NOT match the 52.1 percent evidence.
    claim = extract_and_normalize_numeric_claims("Revenue was $52.1 today.")[0]
    assert claim.unit in ("USD",)
    result = match_numeric_claim(claim, index, _TOLERANCE, _ABS_FLOOR)
    assert result.status == ValidationStatus.REJECTED  # no USD-unit evidence exists


# -- full NarrativeClaim verification -----------------------------------------

def test_verify_numeric_claims_populates_narrative_claim():
    package = _package()
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    result = verify_numeric_claims(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert len(result.numeric_claims) == 1
    assert result.numeric_claims[0].status == ValidationStatus.APPROVED


def test_verify_numeric_claims_with_multiple_numbers_in_one_sentence():
    package = _package()
    claim = NarrativeClaim(
        text="Volume contributed R$417K while mix created a -R$75.9K headwind.",
        claim_type=ClaimType.ANALYTICAL_FINDING, evidence_ids=["EV004", "EV005"],
    )
    result = verify_numeric_claims(claim, package, _TOLERANCE, _ABS_FLOOR)
    assert len(result.numeric_claims) == 2
    assert all(nc.status == ValidationStatus.APPROVED for nc in result.numeric_claims)
