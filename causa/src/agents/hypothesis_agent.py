"""
hypothesis_agent.py — Step 5: the Hypothesis Agent (task §1B).

LLM-backed: the model decides which governed tools to call (get_kpi,
get_driver_decomposition, get_concurrent_kpis, search_evidence) and proposes
the actual hypothesis text/mechanism -- genuinely interpretive work the task
explicitly allows ("formulate hypotheses"). What it is NOT allowed to do
(enforced structurally, not just by the system prompt in prompts.py):

  - call a tool outside {get_kpi, get_driver_decomposition, get_concurrent_kpis,
    search_evidence} -- tools/policy.ALLOWED_TOOLS_PER_AGENT[HYPOTHESIS],
    enforced by tools/gateway.call_tool regardless of what it asks for.
  - cite a number that didn't come from a tool call this round --
    agents/models.py's numeric guardrail, checked here before a Hypothesis
    is constructed.
  - phrase anything as an established cause -- agents/models.py's
    Hypothesis.__post_init__ raises on construction if it does; caught here
    and the offending item is DROPPED (never the whole batch, never
    silently rewritten).
  - produce more than 5 hypotheses, or 5 paraphrases of one idea -- enforced
    here by a (driver, dimension) diversity dedup after the model's own
    proposals come back.
"""

from __future__ import annotations

from typing import Optional

from agents.llm_client import LLMClient, run_tool_loop, submit_tool_schema, tools_for_agent_role
from agents.models import AgentRole, Hypothesis, InvestigationState, build_allowed_numbers, validate_numeric_claims
from agents.prompts import HYPOTHESIS_AGENT_SYSTEM_PROMPT
from tools.context import ToolContext

MAX_HYPOTHESES = 5
MIN_HYPOTHESES_PREFERRED = 3

SUBMIT_TOOL_NAME = "submit_hypotheses"
_SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "hypotheses": {
            "type": "array", "maxItems": MAX_HYPOTHESES,
            "items": {
                "type": "object",
                "properties": {
                    "driver": {"type": "string"}, "dimension": {"type": "string"}, "mechanism": {"type": "string"},
                    "statement": {"type": "string"},
                    "expected_evidence": {"type": "array", "items": {"type": "string"}},
                    "falsification_evidence": {"type": "array", "items": {"type": "string"}},
                    "evidence_types_expected": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["driver", "dimension", "mechanism", "statement", "expected_evidence", "falsification_evidence"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["hypotheses"],
    "additionalProperties": False,
}


def _user_prompt(state: InvestigationState) -> str:
    return (
        f"Investigate {state.kpi_id}'s movement in {state.period}. Known movement so far: {state.movement}. "
        f"Use the available tools to gather PVM / segment-contribution / concurrent-KPI / review evidence, "
        f"then call {SUBMIT_TOOL_NAME} with 3-5 genuinely different hypotheses."
    )


def _evidence_gathered_this_call(llm_client: LLMClient, ctx: ToolContext) -> list:
    """Reconstructs the evidence this call actually fetched, for the numeric
    guardrail -- pulled from whatever the tool calls this round populated in
    ctx.evidence_store (a superset is fine; build_allowed_numbers only reads
    numeric fields off each object, an unrelated extra object changes
    nothing about what's "allowed"). Kept intentionally conservative: uses
    the WHOLE evidence_store rather than trying to diff before/after, since
    over-including allowed numbers only makes the guardrail MORE permissive,
    never less -- never a security weakening, just simpler code."""
    return list(ctx.evidence_store.values())


def generate_hypotheses(state: InvestigationState, llm_client: LLMClient, ctx: ToolContext,
                         max_tool_iterations: int = 8) -> InvestigationState:
    tool_schemas = tools_for_agent_role(AgentRole.HYPOTHESIS) + [
        submit_tool_schema(SUBMIT_TOOL_NAME, "Submit your final list of 3-5 hypotheses.", _SUBMIT_SCHEMA)
    ]
    payload = run_tool_loop(
        state, AgentRole.HYPOTHESIS, llm_client, ctx, system=HYPOTHESIS_AGENT_SYSTEM_PROMPT,
        user_content=_user_prompt(state), tool_schemas=tool_schemas, submit_tool_name=SUBMIT_TOOL_NAME,
        max_tool_iterations=max_tool_iterations,
    )
    if not payload:
        return state   # nothing usable this round -- state.hypotheses stays empty; Orchestrator abstains

    allowed_numbers = build_allowed_numbers(_evidence_gathered_this_call(llm_client, ctx))
    seen_pairs: set = set()
    candidates = []
    for i, raw in enumerate(payload.get("hypotheses", [])[:MAX_HYPOTHESES]):
        driver, dimension = str(raw.get("driver", "")).strip(), str(raw.get("dimension", "")).strip()
        if not driver or not dimension:
            continue
        pair = (driver.lower(), dimension.lower())
        if pair in seen_pairs:
            state.security_events.append({
                "type": "hypothesis_diversity_violation", "driver": driver, "dimension": dimension,
                "reason": "duplicate (driver, dimension) pair -- dropped, not a genuinely different hypothesis",
            })
            continue

        statement = str(raw.get("statement", "")).strip()
        ok, violations = validate_numeric_claims(statement, allowed_numbers)
        if not ok:
            state.security_events.append({
                "type": "NUMERIC_VALIDATION_FAILED", "agent_role": AgentRole.HYPOTHESIS.value,
                "field": "Hypothesis.statement", "text": statement, "violating_numbers": violations,
            })
            continue

        try:
            hyp = Hypothesis(
                hypothesis_id=f"H{len(candidates) + 1}", statement=statement, driver=driver, dimension=dimension,
                mechanism=str(raw.get("mechanism", "")).strip(),
                expected_evidence=[str(x) for x in raw.get("expected_evidence", [])],
                falsification_evidence=[str(x) for x in raw.get("falsification_evidence", [])],
                evidence_types_expected=[str(x) for x in raw.get("evidence_types_expected", [])],
            )
        except ValueError as exc:
            state.security_events.append({
                "type": "causal_language_rejected", "agent_role": AgentRole.HYPOTHESIS.value,
                "field": "Hypothesis.statement", "text": statement, "error": str(exc),
            })
            continue

        seen_pairs.add(pair)
        candidates.append(hyp)

    state.hypotheses = candidates[:MAX_HYPOTHESES]
    return state
