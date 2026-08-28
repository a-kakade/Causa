"""
claim_verifier.py — Step 8: the full claim-level gatekeeper.

Composes language_rules.py + numeric_verifier.py + evidence-ID/epistemic-
type/recommendation checks into one ordered pipeline per claim, then rolls
every claim in a story up into one VerificationResult. A story is APPROVED
only if EVERY claim passes -- one rejected claim rejects the whole
narrative (task's own "mismatch? REJECT" framing, applied at the story
level, not partial acceptance).
"""

from __future__ import annotations

from typing import Optional

from story import language_rules, numeric_verifier
from story.models import (
    ClaimType,
    CLAIM_TYPE_RANK,
    EvidencePackage,
    NarrativeClaim,
    StorySection,
    ValidationStatus,
    VerificationResult,
)


def _strongest_cited_claim_type(claim: NarrativeClaim, package: EvidencePackage) -> Optional[ClaimType]:
    """The strongest (highest-rank) ClaimType among all EvidenceItems this
    claim cites. None if no cited evidence_id resolves (evidence-ID
    existence is checked separately, before this is ever called)."""
    types = [package.get(eid).claim_type for eid in claim.evidence_ids if package.get(eid) is not None]
    if not types:
        return None
    return max(types, key=lambda t: CLAIM_TYPE_RANK[t])


def _references_recommendation(claim: NarrativeClaim, package: EvidencePackage) -> Optional[str]:
    """Returns the recommendation_id referenced by this claim's
    evidence_ids, if any (decision.models.ActionRecommendation.recommendation_id
    always starts with 'rec_' -- reused convention, not reinvented)."""
    for eid in claim.evidence_ids:
        if eid.startswith("rec_"):
            return eid
    return None


def verify_claim(claim: NarrativeClaim, package: EvidencePackage, tolerance: float,
                  absolute_floor: float, minimum_magnitude: float = 20.0) -> NarrativeClaim:
    """Runs all checks in order, short-circuiting on first failure. Sets
    claim.validation_status/rejection_reason and returns the (mutated)
    claim."""

    # 1. evidence_id existence -- unknown ids (excluding recommendation ids,
    #    checked separately in #6) are rejected outright.
    recommendation_id = _references_recommendation(claim, package)
    unknown_ids = [
        eid for eid in claim.evidence_ids
        if eid != recommendation_id and package.get(eid) is None
    ]
    if unknown_ids:
        claim.validation_status = ValidationStatus.REJECTED
        claim.rejection_reason = f"evidence_id(s) {unknown_ids!r} do not exist in the evidence package"
        return claim

    # 6. unsupported-recommendation check (checked early since it changes
    #    which evidence_ids are "real" for #2's epistemic check below).
    if recommendation_id is not None and recommendation_id not in package.recommendation_ids():
        claim.validation_status = ValidationStatus.REJECTED
        claim.rejection_reason = (
            f"claim references recommendation_id {recommendation_id!r}, which is not present in Step 7's "
            f"decision output"
        )
        return claim

    # 2. epistemic-type consistency -- a claim may hedge down from its
    #    evidence's strongest claim_type, never claim stronger. Only
    #    evaluated against non-recommendation evidence_ids (a recommendation
    #    citation carries no ClaimType of its own -- see evidence_package.py).
    non_recommendation_ids = [eid for eid in claim.evidence_ids if eid != recommendation_id]
    if non_recommendation_ids:
        strongest = _strongest_cited_claim_type(claim, package)
        if strongest is not None and CLAIM_TYPE_RANK[claim.claim_type] > CLAIM_TYPE_RANK[strongest]:
            claim.validation_status = ValidationStatus.REJECTED
            claim.rejection_reason = (
                f"claim_type={claim.claim_type.value} is not supported by cited evidence's strongest "
                f"claim_type {strongest.value}"
            )
            return claim

    # 3. language-rule check.
    language_violation = language_rules.violates_language_rule(claim.text, claim.claim_type)
    if language_violation is not None:
        claim.validation_status = ValidationStatus.REJECTED
        claim.rejection_reason = language_violation
        return claim

    # 4. numeric verification.
    claim = numeric_verifier.verify_numeric_claims(claim, package, tolerance, absolute_floor, minimum_magnitude)
    rejected_numeric = [nc for nc in claim.numeric_claims if nc.status == ValidationStatus.REJECTED]
    if rejected_numeric:
        claim.validation_status = ValidationStatus.REJECTED
        claim.rejection_reason = rejected_numeric[0].rejection_reason
        return claim

    # 5. unsupported-metric check: numeric claims present but none matched
    #    at all AND no evidence_ids were cited either -- a claim with real
    #    numbers, zero evidence_ids, and (by #4) all its numbers already
    #    rejected would have already returned above; this branch instead
    #    catches a claim citing evidence_ids that exist but whose value
    #    doesn't correspond to ANY number actually stated in the text (i.e.
    #    an evidence_id was cited decoratively, not truly grounding the claim).
    #    Handled conservatively: only fires when the claim has cited
    #    evidence_ids AND the claim's own text carries no numeric claims at
    #    all despite the cited evidence being numeric-valued and the
    #    claim_type being FACT/ANALYTICAL_FINDING (an ostensibly quantified
    #    claim type) -- avoids false positives on legitimately qualitative
    #    ASSOCIATION/HYPOTHESIS sentences.
    if claim.claim_type in (ClaimType.FACT, ClaimType.ANALYTICAL_FINDING) and not claim.numeric_claims:
        cited_numeric_evidence = [
            package.get(eid) for eid in non_recommendation_ids
            if package.get(eid) is not None and isinstance(package.get(eid).value, (int, float))
        ]
        if cited_numeric_evidence:
            claim.validation_status = ValidationStatus.REJECTED
            claim.rejection_reason = (
                f"claim_type={claim.claim_type.value} cites numeric evidence but states no verifiable "
                f"number of its own"
            )
            return claim

    claim.validation_status = ValidationStatus.APPROVED
    return claim


def verify_story_claims(sections: list[StorySection], package: EvidencePackage, tolerance: float = 0.0005,
                         absolute_floor: float = 0.01, minimum_magnitude: float = 20.0
                         ) -> tuple[list[StorySection], VerificationResult]:
    """Runs verify_claim over every NarrativeClaim in every section. Returns
    the (claim-status-updated) sections plus one rolled-up VerificationResult.
    status=APPROVED only if every claim is APPROVED."""
    checked = 0
    rejected: list[dict[str, str]] = []

    for section in sections:
        for claim in section.statements:
            verify_claim(claim, package, tolerance, absolute_floor, minimum_magnitude)
            checked += 1
            if claim.validation_status == ValidationStatus.REJECTED:
                rejected.append({"text": claim.text, "reason": claim.rejection_reason or "unknown"})

    status = ValidationStatus.REJECTED if rejected else ValidationStatus.APPROVED
    result = VerificationResult(status=status, claims_checked=checked, claims_rejected=len(rejected),
                                 rejected_claims=rejected)
    return sections, result
