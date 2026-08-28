"""
planner.py — Step 8: the Narrative Planner.

Decides which evidence matters, what order to present it in, what to omit
-- NEVER creates new evidence. May optionally use an LLM to refine the
deterministic persona-driven ordering, but the LLM's output is always
validated (every evidence_id must exist) before being trusted; any
violation, malformed JSON, or unavailable LLM falls back to the fully
deterministic plan. This function never raises -- it always returns a
usable NarrativePlan.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from story import prompts
from story.models import EvidencePackage, NarrativePlan, NarrativePlanSection, Persona
from story.persona import PersonaEngine


def _deterministic_plan(persona: Persona, package: EvidencePackage, persona_engine: PersonaEngine) -> NarrativePlan:
    """Zero-LLM fallback: buckets persona_engine.select_and_order()'s output
    into the persona's configured section_order, truncated to
    max_statements_per_section evidence_ids per section. Always produces a
    valid NarrativePlan (possibly with empty sections) even for an empty
    package."""
    config = persona_engine.get(persona)
    ordered_items = persona_engine.select_and_order(persona, package)
    section_titles = config.get("section_order", ["Overview"])
    max_per_section = config.get("max_statements_per_section", 3)

    # Distribute ordered_items round-robin-free: the first (non-headline)
    # section gets first max_per_section items, the next gets the next
    # batch, etc. -- deterministic, simple, and never drops an item
    # silently (any remainder past the last section is appended there).
    content_sections = [t for t in section_titles if t.lower() != "headline"]
    sections: list[NarrativePlanSection] = []
    cursor = 0
    for i, title in enumerate(content_sections):
        if title.lower().startswith("recommended action"):
            sections.append(NarrativePlanSection(title=title, evidence_ids=[]))  # populated by generator from recommendations
            continue
        is_last = i == len(content_sections) - 1
        batch = ordered_items[cursor: cursor + max_per_section] if not is_last else ordered_items[cursor:]
        sections.append(NarrativePlanSection(title=title, evidence_ids=[item.evidence_id for item in batch]))
        cursor += max_per_section

    return NarrativePlan(persona=persona, sections=sections)


def _evidence_summary(items) -> str:
    return "\n".join(f"{item.evidence_id}: {item.metric}={item.value}{item.unit or ''}, "
                      f"claim_type={item.claim_type.value}" for item in items)


def plan_narrative(persona: Persona, package: EvidencePackage, persona_engine: PersonaEngine, config: Any,
                    llm_client: Optional[Any] = None) -> NarrativePlan:
    fallback = _deterministic_plan(persona, package, persona_engine)
    if llm_client is None:
        return fallback

    from agents.llm_client import LLMUnavailable

    persona_config = persona_engine.get(persona)
    ordered_items = persona_engine.select_and_order(persona, package)
    user_message = prompts.build_planner_user_message(persona_config, _evidence_summary(ordered_items))

    try:
        response = llm_client.create(
            system=prompts.PLANNER_SYSTEM_PROMPT, messages=[llm_client.build_user_message(user_message)],
            tools=[], max_tokens=config.max_tokens_planner(),
        )
    except LLMUnavailable:
        return fallback
    except Exception:
        return fallback

    text_blocks = [b.get("text", "") for b in response.content if b.get("type") == "text"]
    raw_text = "".join(text_blocks).strip()
    if not raw_text:
        return fallback

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        return fallback

    if not isinstance(parsed, dict) or "sections" not in parsed or not isinstance(parsed["sections"], list):
        return fallback

    valid_ids = package.all_ids()
    sections: list[NarrativePlanSection] = []
    for raw_section in parsed["sections"]:
        if not isinstance(raw_section, dict) or "title" not in raw_section or "evidence_ids" not in raw_section:
            return fallback
        evidence_ids = raw_section["evidence_ids"]
        if not isinstance(evidence_ids, list) or any(not isinstance(e, str) for e in evidence_ids):
            return fallback
        unknown = [eid for eid in evidence_ids if eid not in valid_ids]
        if unknown:
            return fallback  # unknown evidence_id anywhere in the plan -- reject the WHOLE plan, never partial
        sections.append(NarrativePlanSection(title=str(raw_section["title"]), evidence_ids=list(evidence_ids)))

    if not sections:
        return fallback

    return NarrativePlan(persona=persona, sections=sections)
