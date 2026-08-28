"""Step 5: RBAC tests (task §6). EXECUTIVE / ANALYST / INTERNAL, reusing the
existing PUBLIC_ANALYTICAL/INTERNAL/RESTRICTED clearance scale -- never a
parallel system.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.models import AgentRole, InvestigationState, RequesterRole  # noqa: E402
from evidence.models import CLEARANCE_RANK, SecurityClassification  # noqa: E402
from tools import gateway, policy  # noqa: E402


def test_every_requester_role_has_a_clearance_mapping():
    for role in RequesterRole:
        assert role in policy.RBAC_CLEARANCE_FOR_ROLE
        assert policy.RBAC_CLEARANCE_FOR_ROLE[role] in CLEARANCE_RANK


def test_executive_capped_at_public_analytical():
    assert policy.clearance_for_role(RequesterRole.EXECUTIVE) == SecurityClassification.PUBLIC_ANALYTICAL.value


def test_analyst_reaches_internal():
    assert policy.clearance_for_role(RequesterRole.ANALYST) == SecurityClassification.INTERNAL.value


def test_internal_reaches_restricted():
    assert policy.clearance_for_role(RequesterRole.INTERNAL) == SecurityClassification.RESTRICTED.value


def test_unknown_role_refuses_to_guess():
    with pytest.raises(ValueError):
        policy.clearance_for_role("SUPERUSER")


@pytest.mark.parametrize("classification,requester_clearance,expected", [
    ("PUBLIC_ANALYTICAL", "PUBLIC_ANALYTICAL", True), ("INTERNAL", "PUBLIC_ANALYTICAL", False),
    ("INTERNAL", "INTERNAL", True), ("RESTRICTED", "INTERNAL", False), ("RESTRICTED", "RESTRICTED", True),
])
def test_clearance_sufficient_boundaries(classification, requester_clearance, expected):
    assert policy.clearance_sufficient(classification, requester_clearance) == expected


# ---------------------------------------------------------------------------
# End-to-end through the real gateway (task §6's own example: "seller-level
# evidence: INTERNAL"; "An EXECUTIVE investigation must not accidentally
# leak restricted seller identities through agent reasoning.")
# ---------------------------------------------------------------------------

def test_executive_investigation_never_sees_internal_classified_evidence(agent_ctx):
    state = InvestigationState(investigation_id="rbac1", requester_role=RequesterRole.EXECUTIVE, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "get_driver_decomposition", dict(
        kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
        period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
        period_previous_label="2017-10", top_n=10,
    ), agent_ctx)
    assert result.ok
    classifications = {agent_ctx.evidence_store[eid].security.classification.value for eid in result.result_ids}
    assert "INTERNAL" not in classifications
    assert "RESTRICTED" not in classifications


def test_analyst_investigation_can_see_internal_seller_evidence(agent_ctx):
    state = InvestigationState(investigation_id="rbac2", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "get_driver_decomposition", dict(
        kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
        period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
        period_previous_label="2017-10", segment_dimensions=["seller"], top_n=10,
    ), agent_ctx)
    assert result.ok
    classifications = {agent_ctx.evidence_store[eid].security.classification.value for eid in result.result_ids}
    assert "INTERNAL" in classifications


def test_executive_search_evidence_never_reaches_seller_attributed_reviews(agent_ctx):
    """Per evidence.engine's own documented rule: a review with an attributed
    seller is classified INTERNAL. An EXECUTIVE-clearance search must never
    surface one."""
    state = InvestigationState(investigation_id="rbac3", requester_role=RequesterRole.EXECUTIVE, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "search_evidence", dict(
        semantic_query="atraso na entrega, demora", structured_filters={"month": "2017-11"}, top_k=10,
    ), agent_ctx)
    assert result.ok
    if result.result.get("sufficient"):
        for eid in result.result["evidence_ids"]:
            ev = agent_ctx.evidence_store[eid]
            assert ev.security.classification.value != "INTERNAL"
