"""
generator.py — Step 8: the Evidence-Grounded Narrative Generator.

Produces claim-level statements from a NarrativePlan + EvidencePackage.
_deterministic_sections() is the safe, always-available, explicitly-labeled
fallback (GeneratedBy.DETERMINISTIC_TEMPLATE) -- every claim it builds is
constructed directly FROM the evidence using only that evidence's own
claim_type's allowed vocabulary, so it trivially passes claim_verifier.

The LLM path raises MalformedGeneratorOutput on any structural failure
(invalid JSON, missing keys, bad shapes) rather than silently falling back
here -- per the task's own requirement that malformed output be RETRIED
(with feedback) before any fallback decision is made. story/engine.py's
retry loop owns that decision; this module only ever attempts ONE
generation call per invocation.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from story import prompts
from story.language_rules import ALLOWED_VERBS
from story.models import ClaimType, EvidencePackage, GeneratedBy, NarrativeClaim, NarrativePlan, StorySection


class MalformedGeneratorOutput(Exception):
    """Raised when the LLM's response is not valid JSON matching the
    required {"headline", "sections":[{"title","statements":[...]}]} shape.
    Caught by story/engine.py's retry loop, which decides whether to
    regenerate-with-feedback or eventually fall back/fail -- never silently
    swallowed here."""


def _format_value(value, unit: Optional[str]) -> str:
    """Formats a value+unit into text numeric_verifier.py can actually
    parse back out (a literal '%'/'R$' marker, not the word 'percent'/'BRL')
    -- keeps the deterministic template self-consistent with the same
    numeric-claim extraction the LLM path is checked against."""
    if unit == "percent":
        return f"{value}%"
    if unit == "BRL":
        # Sign must precede the 'R$' marker (numeric_verifier.py's pattern
        # requires [-+]?R?\$? in that order) -- "-R$75900.0", never "R$-75900.0".
        sign = "-" if isinstance(value, (int, float)) and value < 0 else ""
        return f"{sign}R${abs(value) if isinstance(value, (int, float)) else value}"
    if unit:
        return f"{value} {unit}"
    return str(value)


def _period_phrase(period: str) -> str:
    """item.period is often a raw 'YYYY-MM-DD..YYYY-MM-DD' range (built by
    evidence_package.py directly from EvidenceObject.time) -- never embed
    that literally in generated prose: its digits are indistinguishable
    from a business number to numeric_verifier.py's extractor, and it
    reads poorly regardless. Reduces to just the trailing (most recent)
    year-month, which is exempted from numeric extraction as a calendar
    reference and reads naturally ("...in 2017-11.")."""
    end = period.split("..")[-1]
    return end[:7] if len(end) >= 7 else end  # "YYYY-MM-DD" -> "YYYY-MM"


def _fact_verb(item) -> str:
    """FACT claims use a direction-appropriate verb (never a fixed "increased"
    regardless of sign) -- ALLOWED_VERBS[FACT] offers both directions;
    item.direction (copied verbatim from the source EvidenceObject) picks
    between them, falling back to the first (increase-flavored) verb only
    when direction is unknown."""
    if item.direction == "decrease":
        return "decreased"
    return ALLOWED_VERBS[ClaimType.FACT][0]  # "increased"


def _deterministic_statement_text(item, other_metric: Optional[str] = None) -> str:
    verb = _fact_verb(item) if item.claim_type == ClaimType.FACT else ALLOWED_VERBS[item.claim_type][0]
    period = _period_phrase(item.period) or "the reported period"
    if item.claim_type == ClaimType.ASSOCIATION and other_metric:
        return f"{item.metric} {verb} {other_metric} in {period}."
    if item.claim_type == ClaimType.UNKNOWN:
        return f"Available evidence is insufficient to determine the {item.metric} movement in {period}."
    value_str = _format_value(item.value, item.unit) if item.value is not None else "an unquantified amount"
    return f"{item.metric} {verb} {value_str} in {period}."


def _deterministic_sections(plan: NarrativePlan, package: EvidencePackage) -> list[StorySection]:
    sections: list[StorySection] = []
    for plan_section in plan.sections:
        statements: list[NarrativeClaim] = []
        for evidence_id in plan_section.evidence_ids:
            item = package.get(evidence_id)
            if item is None:
                continue
            text = _deterministic_statement_text(item)
            statements.append(NarrativeClaim(text=text, claim_type=item.claim_type, evidence_ids=[evidence_id],
                                              confidence=item.confidence))
        # "Recommended action"-titled sections get their statements from
        # package.recommendations directly (the deterministic plan leaves
        # these evidence_ids empty -- see planner.py's _deterministic_plan).
        if plan_section.title.lower().startswith("recommended action"):
            for rec in package.recommendations:
                text = f"Recommended action: {rec.possible_action}"
                statements.append(NarrativeClaim(text=text, claim_type=ClaimType.ANALYTICAL_FINDING,
                                                  evidence_ids=[rec.recommendation_id],
                                                  confidence=rec.score_breakdown.confidence_score))
        sections.append(StorySection(title=plan_section.title, statements=statements))
    return sections


def _evidence_detail(package: EvidencePackage, plan: NarrativePlan) -> str:
    referenced_ids = {eid for s in plan.sections for eid in s.evidence_ids}
    lines = []
    for item in package.items:
        if item.evidence_id in referenced_ids:
            lines.append(f"{item.evidence_id}: {item.metric}={item.value}{item.unit or ''}, "
                         f"claim_type={item.claim_type.value}, confidence={item.confidence}")
    return "\n".join(lines)


def _recommendations_summary(package: EvidencePackage) -> str:
    if not package.recommendations:
        return "(none)"
    lines = []
    for rec in package.recommendations:
        lines.append(f"{rec.recommendation_id}: {rec.possible_action} (owner={rec.owner}, "
                     f"impact={rec.expected_impact.calculated_impact}, "
                     f"confidence={rec.score_breakdown.confidence_score})")
    return "\n".join(lines)


def _parse_generator_response(raw_text: str) -> list[StorySection]:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise MalformedGeneratorOutput(f"response is not valid JSON: {exc}") from exc

    if not isinstance(parsed, dict) or "sections" not in parsed:
        raise MalformedGeneratorOutput("response JSON missing required 'sections' key")
    if not isinstance(parsed["sections"], list):
        raise MalformedGeneratorOutput("'sections' must be a list")

    sections: list[StorySection] = []
    for raw_section in parsed["sections"]:
        if not isinstance(raw_section, dict) or "title" not in raw_section or "statements" not in raw_section:
            raise MalformedGeneratorOutput(f"malformed section entry: {raw_section!r}")
        statements: list[NarrativeClaim] = []
        for raw_statement in raw_section["statements"]:
            if not isinstance(raw_statement, dict):
                raise MalformedGeneratorOutput(f"malformed statement entry: {raw_statement!r}")
            for key in ("text", "evidence_ids", "claim_type"):
                if key not in raw_statement:
                    raise MalformedGeneratorOutput(f"statement missing required key {key!r}: {raw_statement!r}")
            try:
                claim_type = ClaimType(raw_statement["claim_type"])
            except ValueError as exc:
                raise MalformedGeneratorOutput(f"invalid claim_type {raw_statement['claim_type']!r}") from exc
            try:
                statements.append(NarrativeClaim(
                    text=str(raw_statement["text"]), claim_type=claim_type,
                    evidence_ids=list(raw_statement["evidence_ids"]), confidence=raw_statement.get("confidence"),
                ))
            except ValueError as exc:
                # NarrativeClaim.__post_init__ rejects unsupported causal language at construction --
                # treat this exactly like any other malformed-output case, retried with feedback.
                raise MalformedGeneratorOutput(f"statement text violates causal-language rule: {exc}") from exc
        sections.append(StorySection(title=str(raw_section["title"]), statements=statements))

    if not sections:
        raise MalformedGeneratorOutput("response contained zero sections")
    return sections


def generate_narrative(persona, plan: NarrativePlan, package: EvidencePackage, persona_engine, config: Any,
                        llm_client: Optional[Any] = None, feedback: Optional[str] = None
                        ) -> tuple[list[StorySection], GeneratedBy]:
    if llm_client is None:
        return _deterministic_sections(plan, package), GeneratedBy.DETERMINISTIC_TEMPLATE

    from agents.llm_client import LLMUnavailable

    persona_config = persona_engine.get(persona)
    plan_summary = "\n".join(f"{s.title}: {s.evidence_ids}" for s in plan.sections)
    user_message = prompts.build_generator_user_message(
        persona_config, plan_summary, _evidence_detail(package, plan), _recommendations_summary(package), feedback,
    )

    try:
        response = llm_client.create(
            system=prompts.GENERATOR_SYSTEM_PROMPT, messages=[llm_client.build_user_message(user_message)],
            tools=[], max_tokens=config.max_tokens_generator(),
        )
    except LLMUnavailable:
        return _deterministic_sections(plan, package), GeneratedBy.DETERMINISTIC_TEMPLATE

    text_blocks = [b.get("text", "") for b in response.content if b.get("type") == "text"]
    raw_text = "".join(text_blocks).strip()
    if not raw_text:
        raise MalformedGeneratorOutput("LLM response contained no text content")

    sections = _parse_generator_response(raw_text)
    return sections, GeneratedBy.LLM_GENERATED_VERIFIED
