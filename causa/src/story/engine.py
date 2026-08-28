"""
engine.py — Step 8: the single entry point for the Persona-Aware KPI
Storytelling engine.

    EvidencePackage
        |
        v
    planner.plan_narrative()                 -- LLM-backed + deterministic fallback
        |
        v
    generator.generate_narrative()  <---+     -- LLM-backed + deterministic fallback
        |                              |
        v                              | retry with feedback (up to max_generation_retries)
    claim_verifier.verify_story_claims() -----+
        |
        v (APPROVED)                    (exhausted retries)
        |                                     |
        v                                     v
    KPIStory                    fallback (if allowed) or StoryGenerationFailed

No LLM import anywhere in THIS module -- it orchestrates planner.py/
generator.py, both of which accept llm_client=None and remain fully
functional. Every claim's numbers/confidence/priority/constraints/ownership
are computed deterministically upstream (Step 1-7) or verified
deterministically here (claim_verifier.py) -- this module's only job is
sequencing the retry loop and building observability/audit output, never
computing a business number itself.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from story import generator, planner
from story.claim_verifier import verify_story_claims
from story.config import StorytellingConfig
from story.generator import MalformedGeneratorOutput
from story.models import (
    GeneratedBy,
    KPIStory,
    NarrativeClaim,
    Persona,
    StoryGenerationFailed,
    ValidationStatus,
)
from story.persona import PersonaEngine

logger = logging.getLogger(__name__)


def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _build_feedback_message(rejected_claims: list[dict[str, str]]) -> str:
    """Task's exact required format, one line per rejected claim."""
    lines = [
        f'FAILED CLAIM: "{c["text"]}" ERROR: {c["reason"]} REGENERATE using the trusted value.'
        for c in rejected_claims
    ]
    return "\n".join(lines)


def _build_headline(sections, persona: Persona) -> str:
    """Deterministic extraction from the first FACT-type (or, failing that,
    any) claim's text -- never a fresh LLM-authored summary sentence
    standing outside claim-level grounding. Every headline is therefore
    itself traceable to a claim that was independently verified."""
    from story.models import ClaimType

    for section in sections:
        for claim in section.statements:
            if claim.claim_type == ClaimType.FACT:
                return claim.text
    for section in sections:
        if section.statements:
            return section.statements[0].text
    return f"No verified narrative available for {persona.value.title()}."


def _model_info(llm_client: Optional[Any], config: StorytellingConfig) -> dict[str, Any]:
    if llm_client is None:
        return {"provider": "deterministic_template"}
    model = config.model_override()
    if model is None:
        from agents.llm_client import DEFAULT_MODEL
        model = DEFAULT_MODEL
    return {"provider": "groq", "model": model, "prompt_version": config.prompt_version()}


def generate_kpi_story(persona: Persona, package: Any, *, persona_engine: Optional[PersonaEngine] = None,
                        config: Optional[StorytellingConfig] = None, llm_client: Optional[Any] = None
                        ) -> KPIStory:
    persona_engine = persona_engine or PersonaEngine.load()
    config = config or StorytellingConfig.load()

    plan = planner.plan_narrative(persona, package, persona_engine, config, llm_client)

    feedback: Optional[str] = None
    max_attempts = config.max_generation_retries() + 1
    verification = None
    verified_sections = None
    attempt = 0

    for attempt in range(1, max_attempts + 1):
        try:
            sections, generated_by = generator.generate_narrative(
                persona, plan, package, persona_engine, config, llm_client, feedback,
            )
        except MalformedGeneratorOutput as exc:
            logger.info("story.engine: persona=%s attempt=%d malformed generator output: %s",
                        persona.value, attempt, exc)
            feedback = (
                f"Your previous response was not valid JSON matching the required schema: {exc}. "
                f"Regenerate valid JSON matching the exact shape described in your system prompt."
            )
            continue

        verified_sections, verification = verify_story_claims(
            sections, package, config.numeric_tolerance(), config.numeric_absolute_floor(),
            config.minimum_magnitude(),
        )
        logger.info(
            "story.engine: persona=%s package_id=%s attempt=%d claims_checked=%d claims_rejected=%d "
            "verification_status=%s",
            persona.value, package.package_id, attempt, verification.claims_checked,
            verification.claims_rejected, verification.status.value,
        )

        if verification.status == ValidationStatus.APPROVED:
            headline = _build_headline(verified_sections, persona)
            return KPIStory(
                persona=persona, headline=headline, sections=verified_sections, verification=verification,
                generated_by=generated_by, generated_at=now_iso(), model_info=_model_info(llm_client, config),
                evidence_package_id=package.package_id, evidence_package_version=package.version,
                evidence_package_hash=package.content_hash, generation_attempts=attempt,
            )

        feedback = _build_feedback_message(verification.rejected_claims)

    # Exhausted all attempts without an APPROVED verification.
    if config.allow_deterministic_fallback():
        sections = generator._deterministic_sections(plan, package)
        verified_sections, verification = verify_story_claims(
            sections, package, config.numeric_tolerance(), config.numeric_absolute_floor(),
            config.minimum_magnitude(),
        )
        headline = _build_headline(verified_sections, persona)
        logger.info("story.engine: persona=%s falling back to deterministic template after %d attempt(s)",
                    persona.value, attempt)
        return KPIStory(
            persona=persona, headline=headline, sections=verified_sections, verification=verification,
            generated_by=GeneratedBy.DETERMINISTIC_TEMPLATE, generated_at=now_iso(),
            model_info={"provider": "deterministic_template"}, evidence_package_id=package.package_id,
            evidence_package_version=package.version, evidence_package_hash=package.content_hash,
            generation_attempts=attempt,
        )

    raise StoryGenerationFailed(
        f"Persona {persona.value}: no verified narrative after {attempt} attempt(s). "
        f"Last verification: {verification.claims_rejected if verification else '?'}/"
        f"{verification.claims_checked if verification else '?'} claims rejected."
    )
