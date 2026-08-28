"""
counter_evidence_agent.py — Step 5: the mandatory adversarial Counter-Evidence
Agent (task §1D) + the deterministic Contradiction Engine (task §12).

Two halves, deliberately split:
  - collect_counter_evidence(): LLM-backed. For every hypothesis with at
    least one SUPPORTS-classified item, the model actively searches for
    contradicting evidence, unaffected segments, temporal mismatches, weak
    sample sizes, and evidence-quality problems (task §1D's exact playbook,
    in prompts.py's system prompt). This is genuinely adversarial
    interpretation -- an appropriate LLM task.
  - score_contradiction_severity() / build_contradiction_records(): 100%
    DETERMINISTIC. The model's own contradiction_level opinion is recorded
    but NEVER used as the actual severity -- task §12: "Do not resolve
    contradictions by majority vote" applies just as much to "trust the
    model's self-report" as to any other shortcut. Severity is computed from
    real counts and a REAL two-proportion z-test already run by Step 4's
    graph.py (evidence.graph.check_low_score_rate_contradiction), never
    invented here.
"""

from __future__ import annotations

import re
from typing import Optional

from agents.llm_client import LLMClient, run_tool_loop, submit_tool_schema, tools_for_agent_role
from agents.models import (
    AgentRole,
    ContradictionRecord,
    ContradictionSeverity,
    CounterEvidenceReport,
    EvidenceClassification,
    InvestigationState,
    assert_no_unsupported_causal_language,
    build_allowed_numbers,
    validate_numeric_claims,
)
from agents.prompts import COUNTER_EVIDENCE_AGENT_SYSTEM_PROMPT
from tools.context import ToolContext

SUBMIT_TOOL_NAME = "submit_counter_evidence_report"
_SUBMIT_SCHEMA = {
    "type": "object",
    "properties": {
        "supporting_evidence": {"type": "array", "items": {"type": "string"}},
        "contradicting_evidence": {"type": "array", "items": {"type": "string"}},
        "unresolved_questions": {"type": "array", "items": {"type": "string"}},
        "contradiction_level": {"type": "string", "enum": ["NONE", "WEAK", "MODERATE", "STRONG"]},
    },
    "required": ["supporting_evidence", "contradicting_evidence", "unresolved_questions", "contradiction_level"],
    "additionalProperties": False,
}

# Same conventional two-sided-95% threshold graph.py's own docstring cites.
Z_STRONG_THRESHOLD = 1.96
N_STRONG_THRESHOLD = 30
_NOTE_PATTERN = re.compile(r"n=(\d+)\).*?n=(\d+)\).*?z=([\-0-9.]+|None)", re.DOTALL)


def _user_prompt(hypothesis, classified_for_hypothesis: list) -> str:
    supports = [c.evidence_id for c in classified_for_hypothesis if c.classification == EvidenceClassification.SUPPORTS]
    return (
        f"Hypothesis {hypothesis.hypothesis_id}: {hypothesis.statement}\n"
        f"driver={hypothesis.driver}, dimension={hypothesis.dimension}, mechanism={hypothesis.mechanism}\n"
        f"Currently supported by: {supports}\n"
        f"Try to prove this hypothesis WRONG: look for unaffected segments, opposite-direction segments, "
        f"weak sample sizes, temporal mismatches (check the PRIOR period pair too), and evidence-quality "
        f"problems. Then call {SUBMIT_TOOL_NAME}."
    )


def collect_counter_evidence(state: InvestigationState, llm_client: LLMClient, ctx: ToolContext,
                              max_tool_iterations: int = 8) -> InvestigationState:
    tool_schemas = tools_for_agent_role(AgentRole.COUNTER_EVIDENCE) + [
        submit_tool_schema(SUBMIT_TOOL_NAME, "Submit your counter-evidence findings for this hypothesis.", _SUBMIT_SCHEMA)
    ]

    for hypothesis in state.hypotheses:
        classified_for_hyp = [c for c in state.classified_evidence if c.hypothesis_id == hypothesis.hypothesis_id]
        if not any(c.classification == EvidenceClassification.SUPPORTS for c in classified_for_hyp):
            continue   # nothing worth attacking yet -- no support to counter

        payload = run_tool_loop(
            state, AgentRole.COUNTER_EVIDENCE, llm_client, ctx, system=COUNTER_EVIDENCE_AGENT_SYSTEM_PROMPT,
            user_content=_user_prompt(hypothesis, classified_for_hyp), tool_schemas=tool_schemas,
            submit_tool_name=SUBMIT_TOOL_NAME, max_tool_iterations=max_tool_iterations,
        )
        if not payload:
            state.counter_evidence_reports.append(CounterEvidenceReport(hypothesis_id=hypothesis.hypothesis_id))
            continue

        allowed_numbers = build_allowed_numbers(list(ctx.evidence_store.values()))

        def _valid_ids(raw_ids: list) -> list:
            out = []
            for eid in raw_ids:
                eid = str(eid).strip()
                if eid in ctx.evidence_store:
                    out.append(eid)
                else:
                    state.security_events.append({
                        "type": "hallucinated_evidence_id", "agent_role": AgentRole.COUNTER_EVIDENCE.value,
                        "hypothesis_id": hypothesis.hypothesis_id, "evidence_id": eid,
                    })
            return out

        supporting = _valid_ids(payload.get("supporting_evidence", []))
        contradicting = _valid_ids(payload.get("contradicting_evidence", []))

        questions = []
        for q in payload.get("unresolved_questions", []):
            q = str(q).strip()
            if not q:
                continue
            ok, violations = validate_numeric_claims(q, allowed_numbers)
            if not ok:
                state.security_events.append({
                    "type": "NUMERIC_VALIDATION_FAILED", "agent_role": AgentRole.COUNTER_EVIDENCE.value,
                    "field": "CounterEvidenceReport.unresolved_questions", "text": q, "violating_numbers": violations,
                })
                continue
            try:
                assert_no_unsupported_causal_language(q, "CounterEvidenceReport.unresolved_questions")
            except ValueError as exc:
                state.security_events.append({
                    "type": "causal_language_rejected", "agent_role": AgentRole.COUNTER_EVIDENCE.value,
                    "field": "CounterEvidenceReport.unresolved_questions", "text": q, "error": str(exc),
                })
                continue
            questions.append(q)

        # The model's own contradiction_level is recorded but NEVER used as
        # the real severity -- see module docstring. score_contradiction_severity
        # (deterministic, below) is what actually feeds build_contradiction_records.
        state.counter_evidence_reports.append(CounterEvidenceReport(
            hypothesis_id=hypothesis.hypothesis_id, supporting_evidence=supporting,
            contradicting_evidence=contradicting, unresolved_questions=questions,
            contradiction_level=ContradictionSeverity.NONE,   # placeholder; recomputed in build_contradiction_records
        ))

    return state


# ---------------------------------------------------------------------------
# Deterministic severity scoring + ContradictionRecord construction (task §12)
# ---------------------------------------------------------------------------

def _find_graph_z_test(hypothesis, ctx: ToolContext) -> Optional[dict]:
    """The ONE statistical contradiction check Step 4's own graph build
    actually computes (evidence.graph.check_low_score_rate_contradiction,
    attached to the avg_delivery_days movement node) -- reused here exactly
    as-is, never re-derived, and only consulted for hypotheses about that
    specific relationship. Other hypotheses get no bonus from this check
    (documented limitation, see STEP5_VALIDATION.md Known Limitations)."""
    is_delivery_review_hypothesis = (
        "delivery" in hypothesis.driver.lower() or "review" in hypothesis.dimension.lower()
        or "delivery" in hypothesis.dimension.lower()
    )
    if not is_delivery_review_hypothesis:
        return None

    delivery_kpi_node = "kpi_avg_delivery_days"
    if delivery_kpi_node not in ctx.graph:
        return None
    movement_node = None
    for _, target, attrs in ctx.graph.out_edges(delivery_kpi_node, data=True):
        if attrs.get("relationship_type") == "HAS_MOVEMENT":
            movement_node = target
            break
    if movement_node is None:
        return None

    for _, target, attrs in ctx.graph.out_edges(movement_node, data=True):
        if attrs.get("relationship_type") != "CONTRADICTS":
            continue
        note = attrs.get("note") or ""
        m = _NOTE_PATTERN.search(note)
        if not m:
            continue
        n1, n2, z_str = m.groups()
        try:
            z = float(z_str)
        except ValueError:
            z = None
        return {"z": z, "n_total": int(n1) + int(n2), "note": note}
    return None


def score_contradiction_severity(n_contradicts: int, graph_check: Optional[dict]) -> ContradictionSeverity:
    """Deterministic (task §12: 'Do not resolve contradictions by majority
    vote'; this is the concrete, auditable rule instead). Considers evidence
    quality via a REAL statistical test where one exists, and raw
    CONTRADICTS-classified evidence counts otherwise."""
    graph_z = graph_check.get("z") if graph_check else None
    graph_n = graph_check.get("n_total") if graph_check else None
    graph_strong = graph_z is not None and abs(graph_z) >= Z_STRONG_THRESHOLD and (graph_n or 0) >= N_STRONG_THRESHOLD
    graph_present_but_weak = graph_z is not None and not graph_strong

    if graph_strong and n_contradicts >= 1:
        return ContradictionSeverity.STRONG
    if n_contradicts >= 3:
        return ContradictionSeverity.STRONG
    if graph_strong or n_contradicts >= 2:
        return ContradictionSeverity.MODERATE
    if n_contradicts == 1 or graph_present_but_weak:
        return ContradictionSeverity.WEAK
    return ContradictionSeverity.NONE


def build_contradiction_records(state: InvestigationState, ctx: ToolContext) -> InvestigationState:
    """Pure re-derivation from what collect_counter_evidence already
    gathered -- NO new tool calls (task's own state-machine order: this runs
    in the CONTRADICTION_ANALYSIS stage, after COUNTER_EVIDENCE has already
    completed). unresolved=True always -- task §18/§12: never auto-resolved."""
    for hypothesis in state.hypotheses:
        report = next((r for r in state.counter_evidence_reports if r.hypothesis_id == hypothesis.hypothesis_id), None)
        classified_contradicts = [
            c.evidence_id for c in state.classified_evidence
            if c.hypothesis_id == hypothesis.hypothesis_id and c.classification == EvidenceClassification.CONTRADICTS
        ]
        contradicting_ids = sorted(set(classified_contradicts) | set(report.contradicting_evidence if report else []))
        supporting_ids = sorted(set(
            c.evidence_id for c in state.classified_evidence
            if c.hypothesis_id == hypothesis.hypothesis_id and c.classification == EvidenceClassification.SUPPORTS
        ) | set(report.supporting_evidence if report else []))

        graph_check = _find_graph_z_test(hypothesis, ctx)
        severity = score_contradiction_severity(len(contradicting_ids), graph_check)

        state.contradictions.append(ContradictionRecord(
            contradiction_id=f"CR-{hypothesis.hypothesis_id}", hypothesis_id=hypothesis.hypothesis_id,
            supporting_evidence=supporting_ids, contradicting_evidence=contradicting_ids, severity=severity,
            unresolved=True,
        ))
    return state
