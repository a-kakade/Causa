"""
explanation.py — Step 7: converts a computed DecisionResult into
human-readable business language.

Answers "how do we know whether the action worked?" is monitoring.py's job;
this module answers "what should the business do, in plain English?" A
deterministic template narrative is ALWAYS available (zero LLM calls) --
this alone satisfies the human-readable requirement and is what every test
and the demo script exercise.

This is one of exactly two modules in src/decision/ allowed to import
agents.llm_client (the other is candidate_generator.py). The optional LLM
path may only VERBALIZE facts src/decision/ranking.py already computed --
never independently generate a number, a confidence, a priority, a
constraint, an owner, or a monitoring target. Every number in an LLM
narrative is checked against agents.models.build_allowed_numbers()/
validate_numeric_claims() (reused, not reimplemented) built from the
DecisionResult's OWN computed fields; any violation -- fabricated number or
unsupported causal language -- falls back to the deterministic template
rather than raising, so narrate() never crashes the caller.

narrate() is never called from inside ranking.run_decision_pipeline() --
always a separate, explicit, optional step a caller (the demo script)
invokes itself, keeping the core pipeline's determinism guarantee airtight
and independently testable without any LLM dependency.
"""

from __future__ import annotations

from typing import Any, Optional

from agents.models import assert_no_unsupported_causal_language, build_allowed_numbers, validate_numeric_claims

from decision.models import ActionRecommendation, DecisionResult


def _deterministic_narrative(result: DecisionResult) -> str:
    signal = result.driver_signal
    if result.top_recommendation is None:
        return (
            f"No actionable recommendation could be generated for driver {signal.driver!r} "
            f"({', '.join(result.pipeline_trace) if result.pipeline_trace else 'no reason recorded'})."
        )

    top = result.top_recommendation
    impact = top.expected_impact
    impact_text = (
        f"approximately {impact.estimated_effect} {impact.effect_unit} in {impact.metric}, "
        f"adjusted for {impact.confidence:.0%} confidence"
        if impact.is_estimable else "not quantifiable with currently available data"
    )
    constraint_summary = "; ".join(
        f"{c.constraint} ({c.status.value.lower()}): {c.details}" for c in top.constraints
    ) or "no constraints flagged"
    monitor_list = ", ".join(m.kpi for m in top.monitoring_kpis) or "no monitoring KPIs declared"

    lines = [
        f"Driver: {signal.driver} ({top.driver_category}) observed in {signal.kpi_id} for {signal.period}.",
        f"Top recommendation: {top.possible_action}",
        f"Controllable lever: {top.controllable_lever}",
        f"Expected impact: {impact_text}",
        f"Owner: {top.owner}",
        f"Constraints: {constraint_summary}",
        f"Priority score: {top.priority_score:.4f}",
        f"Monitor: {monitor_list}",
    ]
    if result.alternatives:
        lines.append(f"{len(result.alternatives)} alternative action(s) were also evaluated and ranked below this one.")
    if result.conditional:
        lines.append(f"{len(result.conditional)} action(s) are conditionally viable pending a flagged constraint.")
    if result.blocked:
        lines.append(f"{len(result.blocked)} action(s) are currently blocked and excluded from ranking.")
    return "\n".join(lines)


def _numeric_facts(result: DecisionResult) -> list[Any]:
    """Builds a flat list of objects exposing a `.value` attribute (matching
    agents.models.build_allowed_numbers()'s expected shape) plus raw
    metadata dicts, from every computed number in the DecisionResult."""
    class _Fact:
        def __init__(self, value):
            self.value = value
            self.metadata = {}

    facts: list[Any] = []
    for rec in ([result.top_recommendation] if result.top_recommendation else []) + result.alternatives + result.conditional + result.blocked:
        impact = rec.expected_impact
        for value in (impact.estimated_effect, impact.addressable_population, impact.confidence,
                      impact.calculated_impact, impact.revenue_impact, rec.controllability, rec.effort,
                      rec.priority_score, rec.score_breakdown.confidence_score):
            if isinstance(value, (int, float)):
                facts.append(_Fact(value))
        for m in rec.monitoring_kpis:
            for value in (m.expected_effect, m.warning_threshold):
                if isinstance(value, (int, float)):
                    facts.append(_Fact(value))
    return facts


def narrate(result: DecisionResult, llm_client: Optional[Any] = None) -> str:
    fallback = _deterministic_narrative(result)
    if llm_client is None:
        return fallback

    from agents.llm_client import LLMUnavailable

    prompt = (
        "Write a short, plain-English business narrative from the following already-computed decision "
        "result. Only describe facts present below -- never invent a number, confidence, priority, "
        "constraint, owner, or KPI target, and never claim the action definitely caused or will cause "
        f"anything.\n\nDecision result:\n{result.to_dict()}"
    )
    try:
        response = llm_client.create(
            system="You write plain-English narratives strictly from already-computed structured facts. "
                   "You never invent numbers or causal claims.",
            messages=[llm_client.build_user_message(prompt)], tools=[], max_tokens=400,
        )
    except LLMUnavailable:
        return fallback
    except Exception:
        return fallback

    text_blocks = [b.get("text", "") for b in response.content if b.get("type") == "text"]
    candidate = "\n".join(t.strip() for t in text_blocks if t.strip())
    if not candidate:
        return fallback

    try:
        assert_no_unsupported_causal_language(candidate, "explanation.narrate LLM output")
    except ValueError:
        return fallback

    allowed_numbers = build_allowed_numbers(_numeric_facts(result))
    ok, _violations = validate_numeric_claims(candidate, allowed_numbers)
    if not ok:
        return fallback

    return candidate
