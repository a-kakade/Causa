"""
schemas.py — Step 5: Tool Gateway declarations (task §2).

    Agent -> Tool Gateway -> Authentication -> Authorization -> Input
        Validation -> Tool Execution -> Output Validation -> Evidence Object

Every tool registered in src/tools/gateway.py declares a ToolDefinition:
tool_name, allowed_agents, input_schema, output_schema, security_classification,
estimated_cost, estimated_latency (task §2's exact list). This module holds
only the declaration shapes — no execution logic (that's analytics_tools.py /
evidence_tools.py) and no policy tables (that's policy.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass(frozen=True)
class ToolParam:
    name: str
    type: str                      # "str" | "int" | "float" | "bool" | "list[str]" | "dict[str,str]"
    required: bool = True
    allowed_values: Optional[tuple] = None


@dataclass(frozen=True)
class ToolDefinition:
    tool_name: str
    allowed_agents: frozenset        # of agents.models.AgentRole values (strings)
    input_schema: tuple              # of ToolParam
    output_schema: str               # short description of the return shape, e.g. "list[EvidenceObject]"
    security_classification: str     # PUBLIC_ANALYTICAL | INTERNAL | RESTRICTED — the MINIMUM this tool
                                      # can ever return; a caller with lower clearance gets a filtered result,
                                      # never an error that leaks the existence of higher-clearance data.
    estimated_cost: float            # USD, 0.0 for every tool here (self-hosted, no paid API — task §20)
    estimated_latency_ms: float      # rough order-of-magnitude, documentation only, not enforced
    fn: Callable[..., Any]           # the actual (governed) implementation this definition wraps
    description: str = ""            # human/model-facing summary of what this tool does — the ONLY thing an
                                      # LLM-backed agent (Step 5's Hypothesis/Evidence/Counter-Evidence agents)
                                      # ever sees about a tool; never influences authorization (that's
                                      # allowed_agents + tools/policy.py, enforced in tools/gateway.py
                                      # regardless of what an LLM decides to request).


@dataclass
class ToolCallResult:
    tool_name: str
    ok: bool
    result: Any = None
    error: Optional[str] = None
    result_ids: list = field(default_factory=list)   # evidence_ids extracted from `result`, for the audit trace
