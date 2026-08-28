"""
evidence_agent.py — Step 5: the Evidence Agent (task §1C).

LLM-backed: the model decides what additional evidence to request (task's
own words: "decide what evidence to request ... interpret evidence") for
each hypothesis in turn, and classifies each item it gathers as SUPPORTS /
CONTRADICTS / CONTEXT / INSUFFICIENT with a rationale.

LLM =/= quantitative truth, concretely enforced here (task's NON-NEGOTIABLE
PRINCIPLE), in order:
  1. Citation reality check -- every evidence_id the model classifies MUST
     already exist in ctx.evidence_store (i.e. actually came back from a
     real tool call). A cited id that doesn't exist is DROPPED, never
     invented into existence, and logged as a security event.
  2. Deterministic classification floor (_apply_floor) -- regardless of what
     the model says, low confidence / below-minimum sample size / a BLOCKED
     security_status forces INSUFFICIENT, and CONCURRENT_KPI evidence is
     always forced to CONTEXT (task §15 of Step 3D: never combined into a
     conclusion). The model's qualitative read is respected everywhere this
     floor doesn't apply.
  3. Numeric guardrail on every rationale string.
  4. Causal-language guardrail on every rationale string (construction-time,
     via ClassifiedEvidence.__post_init__).

Task §11: classification "must preserve the original evidence object. Do not
rewrite evidence numerically." -- ClassifiedEvidence.source_evidence holds
the ORIGINAL dict fetched from ctx.evidence_store, untouched.
"""

from __future__ import annotations

from agents.llm_client import LLMClient, run_tool_loop, submit_tool_schema, tools_for_agent_role
from agents.models import (
    AgentRole,
    ClassifiedEvidence,
    EvidenceClassification,
    InvestigationState,
    build_allowed_numbers,
    validate_numeric_claims,
)
from agents.prompts import EVIDENCE_AGENT_SYSTEM_PROMPT
from tools.context import ToolContext

MIN_SAMPLE_SIZE = 15   # reused verbatim from evidence.engine.build_november_2017_evidence_package's own threshold

SUBMIT_TOOL_NAME = "submit_evidence_classification"
_SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "classifications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "evidence_id": {"type": "string"},
                    "classification": {"type": "string", "enum": ["SUPPORTS", "CONTRADICTS", "CONTEXT", "INSUFFICIENT"]},
                    "rationale": {"type": "string"},
                },
                "required": ["evidence_id", "classification", "rationale"], "additionalProperties": False,
            },
        },
    },
    "required": ["classifications"], "additionalProperties": False,
}


def _user_prompt(hypothesis) -> str:
    return (
        f"Hypothesis {hypothesis.hypothesis_id}: {hypothesis.statement}\n"
        f"driver={hypothesis.driver}, dimension={hypothesis.dimension}, mechanism={hypothesis.mechanism}\n"
        f"expected_evidence (would SUPPORT): {hypothesis.expected_evidence}\n"
        f"falsification_evidence (would CONTRADICT): {hypothesis.falsification_evidence}\n"
        f"Gather whatever additional evidence you need and classify each item, then call {SUBMIT_TOOL_NAME}."
    )


def _apply_floor(ev: dict, llm_classification: str) -> tuple:
    """Returns (final_classification, reason_suffix). Overrides the model's
    classification only when a genuine, always-available quantitative gate
    fails -- never second-guesses a qualitative SUPPORTS/CONTRADICTS/CONTEXT
    call the model made when no gate applies."""
    if ev.get("evidence_type") == "CONCURRENT_KPI":
        return EvidenceClassification.CONTEXT.value, "forced CONTEXT: concurrent-KPI evidence is never support/contradict"
    if ev.get("confidence") in ("LOW", "UNKNOWN"):
        return EvidenceClassification.INSUFFICIENT.value, f"forced INSUFFICIENT: confidence={ev.get('confidence')}"
    security_status = (ev.get("security") or {}).get("security_status")
    if security_status == "BLOCKED":
        return EvidenceClassification.INSUFFICIENT.value, "forced INSUFFICIENT: security_status=BLOCKED"
    sample_size = (ev.get("metadata") or {}).get("sample_size")
    if sample_size is not None and sample_size < MIN_SAMPLE_SIZE:
        return EvidenceClassification.INSUFFICIENT.value, f"forced INSUFFICIENT: sample_size={sample_size} < {MIN_SAMPLE_SIZE}"
    return llm_classification, ""


def collect_evidence(state: InvestigationState, llm_client: LLMClient, ctx: ToolContext,
                      max_tool_iterations: int = 8) -> InvestigationState:
    tool_schemas = tools_for_agent_role(AgentRole.EVIDENCE) + [
        submit_tool_schema(SUBMIT_TOOL_NAME, "Submit your evidence classifications for this hypothesis.", _SUBMIT_SCHEMA)
    ]

    for hypothesis in state.hypotheses:
        payload = run_tool_loop(
            state, AgentRole.EVIDENCE, llm_client, ctx, system=EVIDENCE_AGENT_SYSTEM_PROMPT,
            user_content=_user_prompt(hypothesis), tool_schemas=tool_schemas, submit_tool_name=SUBMIT_TOOL_NAME,
            max_tool_iterations=max_tool_iterations,
        )
        if not payload:
            continue   # nothing usable for this hypothesis this round -- it simply gets no classified evidence

        allowed_numbers = build_allowed_numbers(list(ctx.evidence_store.values()))
        for raw in payload.get("classifications", []):
            evidence_id = str(raw.get("evidence_id", "")).strip()
            ev = ctx.evidence_store.get(evidence_id)
            if ev is None:
                state.security_events.append({
                    "type": "hallucinated_evidence_id", "agent_role": AgentRole.EVIDENCE.value,
                    "hypothesis_id": hypothesis.hypothesis_id, "evidence_id": evidence_id,
                    "reason": "model cited an evidence_id that was never produced by a real tool call -- dropped",
                })
                continue
            ev_dict = ev.model_dump()

            llm_classification = str(raw.get("classification", "")).strip().upper()
            final_classification, floor_reason = _apply_floor(ev_dict, llm_classification)
            try:
                final_enum = EvidenceClassification(final_classification)
            except ValueError:
                continue   # model returned a classification outside the enum -- drop rather than guess

            rationale = str(raw.get("rationale", "")).strip()
            if floor_reason:
                rationale = f"{rationale} [{floor_reason}]" if rationale else floor_reason

            ok, violations = validate_numeric_claims(rationale, allowed_numbers)
            if not ok:
                state.security_events.append({
                    "type": "NUMERIC_VALIDATION_FAILED", "agent_role": AgentRole.EVIDENCE.value,
                    "field": "ClassifiedEvidence.rationale", "text": rationale, "violating_numbers": violations,
                })
                continue

            try:
                classified = ClassifiedEvidence(
                    evidence_id=evidence_id, hypothesis_id=hypothesis.hypothesis_id, classification=final_enum,
                    rationale=rationale, source_evidence=ev,
                )
            except ValueError as exc:
                state.security_events.append({
                    "type": "causal_language_rejected", "agent_role": AgentRole.EVIDENCE.value,
                    "field": "ClassifiedEvidence.rationale", "text": rationale, "error": str(exc),
                })
                continue

            state.classified_evidence.append(classified)
            if evidence_id not in state.evidence_ids:
                state.evidence_ids.append(evidence_id)

    return state
