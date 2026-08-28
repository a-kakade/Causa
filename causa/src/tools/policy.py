"""
policy.py — Step 5: RBAC and tool-permission policy tables (task §3/§6).

Pure data + small pure-function lookups. No tool execution and no NetworkX/
pandas access lives here — src/evidence/access_control.py remains the one
place graph/evidence filtering actually happens; this module only decides
(a) which SecurityClassification clearance a RequesterRole is entitled to,
and (b) which tool names an AgentRole may call. Both are consulted by
src/tools/gateway.py before a tool ever executes (task §4: "Security must be
enforced at tool level, not only in prompts.").
"""

from __future__ import annotations

from agents.models import AgentRole, RequesterRole
from evidence.models import CLEARANCE_RANK, SecurityClassification

# ---------------------------------------------------------------------------
# RBAC: RequesterRole -> governed clearance (task §6)
# ---------------------------------------------------------------------------
#
# Reuses the EXISTING PUBLIC_ANALYTICAL/INTERNAL/RESTRICTED scale — never a
# parallel system. Rationale (docs/AGENT_SECURITY.md §2 has the full writeup):
#   EXECUTIVE -> PUBLIC_ANALYTICAL   business-level findings only; task §6's
#                                     own example ("An EXECUTIVE investigation
#                                     must not accidentally leak restricted
#                                     seller identities") requires this cap.
#   ANALYST   -> INTERNAL            can see seller-level internal evidence,
#                                     matching the clearance driver_engine.py
#                                     and evidence.engine.py already use for
#                                     "internal analysis" investigations.
#   INTERNAL  -> RESTRICTED          the highest-trust role (e.g. an internal
#                                     automated audit/compliance process) —
#                                     RESTRICTED is currently unused by any
#                                     governed KPI dimension (see
#                                     config/kpis.yaml), so in practice this
#                                     grants no more than ANALYST today, but
#                                     is deliberately provisioned for a future
#                                     RESTRICTED-classified dimension.
RBAC_CLEARANCE_FOR_ROLE: dict[RequesterRole, str] = {
    RequesterRole.EXECUTIVE: SecurityClassification.PUBLIC_ANALYTICAL.value,
    RequesterRole.ANALYST: SecurityClassification.INTERNAL.value,
    RequesterRole.INTERNAL: SecurityClassification.RESTRICTED.value,
}


def clearance_for_role(role: RequesterRole) -> str:
    if role not in RBAC_CLEARANCE_FOR_ROLE:
        raise ValueError(f"Unknown RequesterRole {role!r} — refusing to guess a clearance.")
    return RBAC_CLEARANCE_FOR_ROLE[role]


def clearance_sufficient(classification: str, requester_clearance: str) -> bool:
    return CLEARANCE_RANK.get(requester_clearance, 0) >= CLEARANCE_RANK.get(classification, 0)


# ---------------------------------------------------------------------------
# Tool permissions: AgentRole -> allowed tool names (task §3)
# ---------------------------------------------------------------------------
#
# No agent gets arbitrary SQL, arbitrary Python, or unrestricted database
# access (task §3) — enforced structurally: the tool names below are the ONLY
# ones ever registered in gateway.py (see analytics_tools.py/evidence_tools.py
# — neither module exposes anything resembling "execute_sql" or "run_python").
ALLOWED_TOOLS_PER_AGENT: dict[AgentRole, frozenset] = {
    AgentRole.ORCHESTRATOR: frozenset({
        # The Orchestrator itself never touches raw evidence — task §1A: "The
        # Orchestrator must NOT independently generate business conclusions."
        # It is not granted any analytics/evidence tool; it only delegates.
    }),
    AgentRole.HYPOTHESIS: frozenset({
        "get_kpi", "get_driver_decomposition", "get_concurrent_kpis", "search_evidence",
    }),
    AgentRole.EVIDENCE: frozenset({
        "get_kpi", "compare_kpi", "get_materiality", "get_driver_decomposition",
        "get_concurrent_kpis", "search_evidence", "get_evidence", "get_graph_neighbors",
    }),
    AgentRole.COUNTER_EVIDENCE: frozenset({
        "search_evidence", "get_evidence", "get_graph_neighbors", "get_driver_decomposition",
    }),
    AgentRole.CAUSAL_SELECTOR: frozenset({
        "get_evidence",   # only to re-read cited evidence tiers/methods when justifying a selection
    }),
    AgentRole.CONFIDENCE_JUDGE: frozenset({
        "get_evidence",   # only to re-read quality/freshness fields already attached to cited evidence
    }),
}

ALL_TOOL_NAMES = frozenset().union(*ALLOWED_TOOLS_PER_AGENT.values())


def is_tool_allowed(agent_role: AgentRole, tool_name: str) -> bool:
    return tool_name in ALLOWED_TOOLS_PER_AGENT.get(agent_role, frozenset())
