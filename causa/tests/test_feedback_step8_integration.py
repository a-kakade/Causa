"""Step 9: integration with Step 8 KPIStory/claim structures (spec section
24) -- feedback references story_id/claim keys, the derived claim_key()
helper resolves back to a real NarrativeClaim without Step 8 growing a
claim_id field."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.capture import submit_feedback  # noqa: E402
from feedback.models import FeedbackRating, OutputType, claim_key  # noqa: E402
from story.models import (  # noqa: E402
    ClaimType,
    GeneratedBy,
    KPIStory,
    Persona,
    StorySection,
    NarrativeClaim,
    ValidationStatus,
    VerificationResult,
)


def _demo_story() -> KPIStory:
    sections = [
        StorySection(title="Overview", statements=[
            NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"]),
        ]),
        StorySection(title="Delivery & Reviews", statements=[
            NarrativeClaim(text="Delivery deterioration coincided with lower review scores.",
                            claim_type=ClaimType.ASSOCIATION, evidence_ids=["EV006", "EV007"]),
            NarrativeClaim(text="Delivery deterioration may have contributed to review composition shifts.",
                            claim_type=ClaimType.HYPOTHESIS, evidence_ids=["EV006"]),
        ]),
    ]
    return KPIStory(
        persona=Persona.EXECUTIVE, headline="Revenue up, reviews down", sections=sections,
        verification=VerificationResult(status=ValidationStatus.APPROVED, claims_checked=3, claims_rejected=0),
        generated_by=GeneratedBy.DETERMINISTIC_TEMPLATE, generated_at="2026-08-28T00:00:00+00:00",
        model_info={}, evidence_package_id="pkg1", evidence_package_version="1.0",
        evidence_package_hash="abc123", generation_attempts=1,
    )


def _resolve_claim_key(story: KPIStory, key: str) -> NarrativeClaim:
    story_id, section_index, claim_index = key.split(":")
    return story.sections[int(section_index)].statements[int(claim_index)]


def test_claim_key_resolves_to_real_claim():
    story = _demo_story()
    key = claim_key("STORY001", 1, 0)
    resolved = _resolve_claim_key(story, key)
    assert resolved.text == "Delivery deterioration coincided with lower review scores."


def test_feedback_references_specific_claim_in_story():
    story = _demo_story()
    target_key = claim_key("STORY001", 1, 0)
    fb = submit_feedback(
        FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1", story_id="STORY001",
        affected_claim_keys=[target_key],
        comment="No — November had a major holiday campaign.",
    )
    resolved = _resolve_claim_key(story, fb.affected_claim_keys[0])
    assert resolved.claim_type == ClaimType.ASSOCIATION
    assert "coincided with" in resolved.text


def test_feedback_does_not_mutate_original_story():
    story = _demo_story()
    original_text = story.sections[1].statements[0].text
    original_status = story.sections[1].statements[0].validation_status

    key = claim_key("STORY001", 1, 0)
    submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1", story_id="STORY001",
                     affected_claim_keys=[key], comment="wrong driver")

    # story object is completely untouched by feedback submission
    assert story.sections[1].statements[0].text == original_text
    assert story.sections[1].statements[0].validation_status == original_status


def test_multiple_claim_keys_across_sections():
    story = _demo_story()
    keys = [claim_key("STORY001", 1, 0), claim_key("STORY001", 1, 1)]
    fb = submit_feedback(FeedbackRating.MISSING_DRIVER, OutputType.STORY_CLAIM, session_id="s1",
                          story_id="STORY001", affected_claim_keys=keys)
    resolved = [_resolve_claim_key(story, k) for k in fb.affected_claim_keys]
    assert resolved[0].claim_type == ClaimType.ASSOCIATION
    assert resolved[1].claim_type == ClaimType.HYPOTHESIS
