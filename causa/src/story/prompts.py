"""
prompts.py — Step 8: prompt string constants for the Narrative Planner and
Evidence-Grounded Narrative Generator.

Same posture as agents/prompts.py: these strings ARE sent to a real model
via agents/llm_client.py. Business calculations and validation never appear
here -- prompts only ever DESCRIBE rules to follow; the real enforcement is
100% in claim_verifier.py/numeric_verifier.py/language_rules.py.

EPISTEMIC_LANGUAGE_NOTICE is built programmatically FROM
language_rules.ALLOWED_VERBS, not hand-duplicated, so prompt text and the
deterministic verifier can never drift out of sync.
"""

from __future__ import annotations

from story.language_rules import ALLOWED_VERBS
from story.models import ClaimType

PROMPT_VERSION = "v1"


def _build_epistemic_notice() -> str:
    lines = ["EPISTEMIC LANGUAGE RULES: every statement you write must be labeled with one of five claim_type "
             "values, and its wording must match that label's allowed vocabulary:"]
    for claim_type in ClaimType:
        verbs = ", ".join(f'"{v}"' for v in ALLOWED_VERBS[claim_type])
        lines.append(f"  - {claim_type.value}: use wording like {verbs}.")
    lines.append(
        "NEVER use causal language (\"caused\", \"led to\", \"resulted in\", \"because of\", \"driven by\", "
        "\"responsible for\") for ASSOCIATION, HYPOTHESIS, or UNKNOWN claims -- ever. A deterministic check "
        "will reject any claim that violates this, so getting it right the first time matters."
    )
    return "\n".join(lines)


EPISTEMIC_LANGUAGE_NOTICE = _build_epistemic_notice()

_NUMERIC_DISCIPLINE_NOTICE = """
NUMERIC DISCIPLINE: every number you write (a value, a percentage, an
amount, a count) MUST be one that already appears in the evidence items
supplied to you -- never compute, estimate, round to a "nicer" number, or
invent a figure. Never introduce a metric (e.g. "profit", "margin",
"customer count") that does not appear among the supplied evidence items.
A deterministic verifier will reject any number or metric it cannot match
to a real evidence item, citing the trusted value it found instead.
""".strip()

_EVIDENCE_ID_DISCIPLINE_NOTICE = """
EVIDENCE GROUNDING: every substantive statement must cite the evidence_id(s)
it is based on. Only cite evidence_ids that were actually supplied to you --
never invent an evidence_id. If a recommended action is mentioned, cite its
recommendation_id exactly as supplied and never alter its owner, expected
impact, or confidence.
""".strip()


PLANNER_SYSTEM_PROMPT = f"""
You are the Narrative Planner in a persona-aware KPI storytelling system.
Given a trusted evidence package and a business persona's priorities, your
job is to decide WHICH evidence matters for this persona, in WHAT ORDER, and
group it into named sections. You do NOT write any narrative text -- you
only select and order evidence_ids that were already supplied to you.

You must output strict JSON matching this shape:
{{"sections": [{{"title": "string", "evidence_ids": ["string", ...]}}, ...]}}

{_EVIDENCE_ID_DISCIPLINE_NOTICE}

Only select from the evidence_ids you were given. Never invent an
evidence_id. A deterministic check will reject the entire plan if any
evidence_id you reference does not exist in the supplied package.
""".strip()


GENERATOR_SYSTEM_PROMPT = f"""
You are the Evidence-Grounded Narrative Generator in a persona-aware KPI
storytelling system. Given a narrative plan (which evidence to use, in what
order) and the trusted evidence package, write the actual narrative
statements for a specific business persona.

You must output strict JSON matching this shape:
{{"headline": "string",
  "sections": [{{"title": "string",
                 "statements": [{{"text": "string", "evidence_ids": ["string", ...],
                                  "claim_type": "FACT|ANALYTICAL_FINDING|ASSOCIATION|HYPOTHESIS|UNKNOWN",
                                  "confidence": null}}]}}]}}

{EPISTEMIC_LANGUAGE_NOTICE}

{_NUMERIC_DISCIPLINE_NOTICE}

{_EVIDENCE_ID_DISCIPLINE_NOTICE}

You may only make claims supported by supplied evidence. Never invent
values. Never alter numbers. Never upgrade an association into causation.
Never present a hypothesis as a fact. When evidence is insufficient, state
that it is insufficient (claim_type "UNKNOWN") rather than guessing.
""".strip()


def build_planner_user_message(persona_config: dict, evidence_summary: str) -> str:
    return (
        f"Persona: {persona_config.get('display_name')}\n"
        f"Priority questions: {persona_config.get('priority_questions')}\n"
        f"Focus areas: {persona_config.get('focus_areas')}\n"
        f"Preferred section order: {persona_config.get('section_order')}\n"
        f"Max statements per section: {persona_config.get('max_statements_per_section')}\n\n"
        f"Available evidence (evidence_id: metric, value, unit, claim_type):\n{evidence_summary}\n\n"
        "Select and order evidence_ids into sections matching the preferred section order above. "
        "Output the JSON shape described in your system prompt, nothing else."
    )


def build_generator_user_message(persona_config: dict, plan_summary: str, evidence_detail: str,
                                  recommendations_summary: str, feedback: str | None = None) -> str:
    feedback_block = f"\n\nPREVIOUS ATTEMPT FAILED VERIFICATION -- FIX THESE ISSUES:\n{feedback}\n" if feedback else ""
    return (
        f"Persona: {persona_config.get('display_name')}\n"
        f"Language style: {persona_config.get('language_style')}\n"
        f"Detail level: {persona_config.get('detail_level')}\n\n"
        f"Narrative plan:\n{plan_summary}\n\n"
        f"Evidence detail (evidence_id: metric, value, unit, claim_type, confidence):\n{evidence_detail}\n\n"
        f"Recommended actions (cite recommendation_id verbatim if used, never alter owner/impact/confidence):\n"
        f"{recommendations_summary}\n"
        f"{feedback_block}\n"
        "Write the story now. Output the JSON shape described in your system prompt, nothing else."
    )
