"""
telemetry.py — Step 5: cost/token telemetry (task §20).

Two kinds of TelemetryRecord get appended to InvestigationState.telemetry:
  - record_llm_call(): one real Groq API call by an LLM-backed agent
    (Hypothesis/Evidence/Counter-Evidence) -- real model id, real
    input/output tokens (from the provider's own `usage` field), a real
    estimated cost from GROQ_PRICING_PER_MILLION_TOKENS.
  - record_deterministic_call(): one pass through a fully deterministic
    agent (Orchestrator/CausalSelector/ConfidenceJudge, or a tool-only call)
    -- model="deterministic_rule_engine_v1", 0 tokens, 0 cost, because that
    is genuinely true for these agents (see agents/models.py's module
    docstring for the full split rationale).

Pricing is APPROXIMATE and will drift as Groq's published rates change --
treat GROQ_PRICING_PER_MILLION_TOKENS as a best-effort estimate for the
prototype's cost telemetry, not a billing-accurate source of truth. An
unknown model id (or Groq's actual free-tier billing for these specific
keys, which may be $0 regardless of the table below) reports cost as 0.0
rather than guessing.
"""

from __future__ import annotations

from typing import Any

from agents.models import AgentRole, InvestigationState, TelemetryRecord

# USD per 1,000,000 tokens. Source: approximate published Groq rates at the
# time this was written; re-check https://groq.com/pricing before treating
# any number here as billing-accurate.
GROQ_PRICING_PER_MILLION_TOKENS: dict[str, dict[str, float]] = {
    # Verified live-reachable with the user's supplied keys and real
    # tool-calling support (see STEP5_VALIDATION.md §14/§17) -- "openai/gpt-oss-20b"
    # is the actual default (agents.llm_client.DEFAULT_MODEL).
    "openai/gpt-oss-20b": {"input": 0.10, "output": 0.50},
    "openai/gpt-oss-120b": {"input": 0.15, "output": 0.75},
    "compound-beta": {"input": 0.59, "output": 0.79},
    "compound-beta-mini": {"input": 0.10, "output": 0.10},
    # Kept for completeness / possible future availability -- NOT verified
    # reachable with this user's keys (see docs/AGENT_SECURITY.md §5).
    "llama-3.3-70b-versatile": {"input": 0.59, "output": 0.79},
    "llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
    "mixtral-8x7b-32768": {"input": 0.24, "output": 0.24},
}
_DEFAULT_PRICE = {"input": 0.0, "output": 0.0}


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    price = GROQ_PRICING_PER_MILLION_TOKENS.get(model, _DEFAULT_PRICE)
    return round(input_tokens / 1_000_000 * price["input"] + output_tokens / 1_000_000 * price["output"], 6)


def record_llm_call(state: InvestigationState, agent_role: AgentRole, response: Any,
                     latency_ms: float) -> TelemetryRecord:
    rec = TelemetryRecord(
        agent_role=agent_role.value, model=response.model, input_tokens=response.input_tokens,
        output_tokens=response.output_tokens, total_tokens=response.input_tokens + response.output_tokens,
        estimated_cost=estimate_cost(response.model, response.input_tokens, response.output_tokens),
        tool_calls=0, retrieval_calls=0, agent_latency_ms=round(latency_ms, 3), total_latency_ms=round(latency_ms, 3),
    )
    state.telemetry.append(rec)
    return rec


def record_deterministic_call(state: InvestigationState, agent_role: AgentRole, latency_ms: float,
                               tool_calls: int = 0, retrieval_calls: int = 0) -> TelemetryRecord:
    rec = TelemetryRecord(
        agent_role=agent_role.value, model="deterministic_rule_engine_v1", input_tokens=0, output_tokens=0,
        total_tokens=0, estimated_cost=0.0, tool_calls=tool_calls, retrieval_calls=retrieval_calls,
        agent_latency_ms=round(latency_ms, 3), total_latency_ms=round(latency_ms, 3),
    )
    state.telemetry.append(rec)
    return rec


def aggregate(state: InvestigationState) -> dict:
    total_input = sum(t.input_tokens for t in state.telemetry)
    total_output = sum(t.output_tokens for t in state.telemetry)
    return {
        "total_llm_calls": sum(1 for t in state.telemetry if t.model != "deterministic_rule_engine_v1"),
        "total_deterministic_calls": sum(1 for t in state.telemetry if t.model == "deterministic_rule_engine_v1"),
        "total_input_tokens": total_input, "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_estimated_cost": round(sum(t.estimated_cost for t in state.telemetry), 6),
        "total_tool_calls": len(state.audit_trace),
        "total_retrieval_calls": state.budgets.used_retrieval_calls,
        "total_agent_latency_ms": round(sum(t.agent_latency_ms for t in state.telemetry), 3),
        "by_agent_role": {
            role.value: {
                "calls": sum(1 for t in state.telemetry if t.agent_role == role.value),
                "tokens": sum(t.total_tokens for t in state.telemetry if t.agent_role == role.value),
                "cost": round(sum(t.estimated_cost for t in state.telemetry if t.agent_role == role.value), 6),
            }
            for role in AgentRole
        },
    }
