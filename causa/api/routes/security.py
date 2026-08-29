"""
routes/security.py — GET /api/security/policy, POST /rbac-demo,
/prompt-injection-demo.

Reads src/tools/policy.py's tables directly and exposes them verbatim --
never redefines RBAC/tool-permission logic. Demo endpoints call the real
policy functions (clearance_sufficient) rather than returning a canned
result.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/policy")
def get_security_policy():
    from tools.policy import ALLOWED_TOOLS_PER_AGENT, RBAC_CLEARANCE_FOR_ROLE

    return {
        "rbac_clearance_for_role": {k.value: v for k, v in RBAC_CLEARANCE_FOR_ROLE.items()},
        "allowed_tools_per_agent": {k.value: sorted(v) for k, v in ALLOWED_TOOLS_PER_AGENT.items()},
        "clearance_scale": ["PUBLIC_ANALYTICAL", "INTERNAL", "RESTRICTED"],
        "notes": [
            "The Tool Gateway (src/tools/gateway.py::call_tool) is the single chokepoint every agent tool "
            "call passes through -- RBAC/clearance checks happen there, never in a prompt.",
            "This is a prototype without a real login system: the browser sends a ROLE NAME only; this "
            "server is the only place that maps a role to an actual clearance.",
        ],
    }


class RbacDemoRequest(BaseModel):
    role: str
    data_classification: str


@router.post("/rbac-demo")
def run_rbac_demo(body: RbacDemoRequest):
    from agents.models import RequesterRole
    from tools import policy

    try:
        role = RequesterRole(body.role)
    except ValueError:
        return {"allowed": False, "reason": f"Unknown role {body.role!r}"}
    clearance = policy.clearance_for_role(role)
    allowed = policy.clearance_sufficient(body.data_classification, clearance)
    return {
        "role": role.value, "requester_clearance": clearance,
        "data_classification": body.data_classification, "allowed": allowed,
        "reason": f"{role.value} resolves to clearance {clearance!r}; "
                  f"{'sufficient' if allowed else 'insufficient'} for {body.data_classification!r} data.",
    }


class PromptInjectionDemoRequest(BaseModel):
    text: str


@router.post("/prompt-injection-demo")
def run_prompt_injection_demo(body: PromptInjectionDemoRequest):
    from agents.security import wrap_untrusted_evidence

    wrapped = wrap_untrusted_evidence(body.text)
    return {
        "original_text": body.text,
        "wrapped_for_llm": wrapped,
        "note": "Untrusted evidence text is always wrapped in an explicit boundary before it reaches an "
                "LLM prompt (src/agents/security.py::wrap_untrusted_evidence) -- it is never concatenated "
                "into privileged instructions.",
    }
