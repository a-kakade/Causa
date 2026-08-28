"""
numeric_verifier.py — Step 8: deterministic numeric claim extraction,
normalization, and matching against a trusted EvidencePackage.

This is the MANDATORY, NON-LLM-JUDGED verifier the task requires: the LLM
is never asked "are these numbers correct?" -- this module performs the
comparison itself, extending (not duplicating) agents.models's numeric
guardrail (_NUMBER_PATTERN / extract_numeric_claims / validate_numeric_claims)
with two capabilities that guardrail does not have:
  1. currency-with-K/M-suffix expansion ("R$417K" -> 417000.0), needed
     because agents.models's existing pattern has no thousand/million
     suffix handling at all.
  2. mapping a claim to a SPECIFIC evidence_id (not just "some number in an
     allowed set") so a rejection reason can name the actual trusted value
     and its source, per the task's own required rejection-message format.

Never confuses 5.2% with 52% -- these differ by 10x, far outside any
reasonable tolerance, AND matching is unit-scoped (a 'percent' claim is
only ever compared against 'percent' evidence, never 'BRL' evidence), so
neither a magnitude coincidence nor a unit mismatch can produce a false
match.
"""

from __future__ import annotations

import re
from typing import Optional

from story.models import EvidencePackage, NarrativeClaim, NumericClaim, ValidationStatus

_NUMBER_PATTERN = re.compile(r"[-+]?R?\$?\s?\d[\d,]*\.?\d*[KkMm]?(?![a-zA-Z])\s?%?")

_SUFFIX_MULTIPLIER = {"k": 1_000, "K": 1_000, "m": 1_000_000, "M": 1_000_000}

# evidence.schema.ValueSpec.unit strings -> the unit vocabulary this module's
# extractor produces, so an EvidenceItem's unit and a claim's extracted unit
# can be compared directly. Any evidence unit not in this table falls back
# to "unitless" (never crashes, never silently drops the item from matching
# consideration -- an "unitless" claim can still match an "unitless"
# evidence value).
_EVIDENCE_UNIT_TO_CLAIM_UNIT: dict[str, str] = {
    "percent": "percent", "BRL": "BRL", "USD": "USD", "count": "unitless", "ratio": "unitless",
}


def _normalize_evidence_unit(unit: Optional[str]) -> str:
    if unit is None:
        return "unitless"
    return _EVIDENCE_UNIT_TO_CLAIM_UNIT.get(unit, "unitless")


def extract_and_normalize_numeric_claims(text: str, minimum_magnitude: float = 20.0) -> list[NumericClaim]:
    """Extracts every number-shaped token, classifies its unit, and
    normalizes K/M suffixes and sign. Deliberately liberal in what it
    extracts (matching agents.models.extract_numeric_claims's own liberal
    stance) -- claim_verifier.py decides what actually counts as a
    violation, not this function.

    Two exemptions, both reused from agents.models.validate_numeric_claims's
    own precedent (same false positives, same fix):
      - a bare (no currency/percent/suffix marker) 4-digit calendar year is
        a date reference, not a business number;
      - a bare, marker-free small integer below minimum_magnitude (e.g. the
        "11" a date string like "2017-11" spuriously yields once its
        separating hyphen is read as a minus sign) is a structural label,
        not a business claim."""
    claims: list[NumericClaim] = []
    for match in _NUMBER_PATTERN.finditer(text):
        raw = match.group()
        cleaned = raw.strip()
        if not cleaned or cleaned in ("+", "-"):
            continue

        is_currency = ("R$" in cleaned) or ("$" in cleaned)
        is_percent = "%" in cleaned
        suffix_match = re.search(r"[KkMm]", cleaned)
        multiplier = _SUFFIX_MULTIPLIER.get(suffix_match.group(), 1) if suffix_match else 1

        numeric_part = re.sub(r"[^\d.\-+]", "", cleaned)
        if not numeric_part or numeric_part in ("+", "-", "."):
            continue
        try:
            value = float(numeric_part)
        except ValueError:
            continue
        value *= multiplier

        if is_percent:
            unit = "percent"
        elif is_currency:
            unit = "BRL" if "R$" in cleaned else "USD"
        else:
            unit = "unitless"

        # A bare (no currency/percent/suffix marker), whole-number, 4-digit
        # calendar year (e.g. "2017" in "...in 2017-11.") is a date
        # reference, not a quantitative business claim -- same exemption
        # agents.models.validate_numeric_claims already applies, for the
        # identical reason (a real false positive was found and fixed
        # there: a hypothesis naming its own investigation period was
        # rejected outright because "2017" wasn't itself in allowed_numbers).
        if unit == "unitless" and multiplier == 1 and value == int(value):
            if 1900 <= value <= 2100:
                continue  # calendar year
            if abs(value) < minimum_magnitude:
                continue  # structural label (date fragment, numbering, rank), not a business claim

        claims.append(NumericClaim(raw_text=raw.strip(), normalized_value=value, unit=unit))
    return claims


def build_evidence_value_index(package: EvidencePackage) -> dict[str, tuple[float, str]]:
    """evidence_id -> (normalized_value, unit), built directly from
    EvidenceItem.value/.unit -- performs no computation, only unit-string
    normalization via _EVIDENCE_UNIT_TO_CLAIM_UNIT so a claim's unit and an
    evidence item's unit compare directly."""
    index: dict[str, tuple[float, str]] = {}
    for item in package.items:
        if isinstance(item.value, (int, float)):
            index[item.evidence_id] = (float(item.value), _normalize_evidence_unit(item.unit))
    return index


def match_numeric_claim(claim: NumericClaim, value_index: dict[str, tuple[float, str]],
                         tolerance: float, absolute_floor: float) -> NumericClaim:
    """Mutates and returns claim with matched_evidence_id/status/rejection_reason
    set. Unit-filtered: only compares against evidence whose normalized unit
    matches claim.unit -- a 'percent' claim is never matched against a 'BRL'
    evidence value even if the raw numbers happen to coincide."""
    unit_matching = {eid: (value, unit) for eid, (value, unit) in value_index.items() if unit == claim.unit}

    if not unit_matching:
        claim.status = ValidationStatus.REJECTED
        claim.rejection_reason = (
            f"No evidence with unit {claim.unit!r} exists in the evidence package -- claim value "
            f"{claim.raw_text!r} cannot be verified against any trusted metric."
        )
        return claim

    for eid, (value, _unit) in unit_matching.items():
        if abs(claim.normalized_value - value) <= max(tolerance * abs(value), absolute_floor):
            claim.status = ValidationStatus.APPROVED
            claim.matched_evidence_id = eid
            return claim

    closest_id, (closest_value, closest_unit) = min(
        unit_matching.items(), key=lambda kv: abs(claim.normalized_value - kv[1][0])
    )
    unit_suffix = "%" if claim.unit == "percent" else (" BRL" if claim.unit == "BRL" else "")
    claim.status = ValidationStatus.REJECTED
    claim.rejection_reason = (
        f"Claimed value {claim.raw_text!r} ({claim.normalized_value}{unit_suffix}) does not match trusted "
        f"evidence {closest_id!r}, which reports {closest_value}{unit_suffix}. REGENERATE using the trusted value."
    )
    return claim


def verify_numeric_claims(claim: NarrativeClaim, package: EvidencePackage, tolerance: float,
                           absolute_floor: float, minimum_magnitude: float = 20.0) -> NarrativeClaim:
    """Extracts numeric claims from claim.text, matches each against
    build_evidence_value_index(package), sets claim.numeric_claims. Does
    NOT set claim.validation_status itself -- claim_verifier.py's
    verify_claim() rolls this up alongside its other checks (evidence-ID
    existence, epistemic-type consistency, language rules)."""
    value_index = build_evidence_value_index(package)
    numeric_claims = extract_and_normalize_numeric_claims(claim.text, minimum_magnitude=minimum_magnitude)
    claim.numeric_claims = [
        match_numeric_claim(nc, value_index, tolerance, absolute_floor) for nc in numeric_claims
    ]
    return claim
