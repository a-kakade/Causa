"""
state_machine.py — Step 5: the investigation state machine (task §8).

    PLANNED -> SECURITY_VALIDATED -> HYPOTHESES_GENERATED -> EVIDENCE_COLLECTION
        -> COUNTER_EVIDENCE -> CONTRADICTION_ANALYSIS -> METHOD_SELECTION
        -> CONFIDENCE_EVALUATION -> COMPLETED

Terminal alternatives (task §8): ABSTAINED, NEEDS_CLARIFICATION,
BUDGET_EXCEEDED, SECURITY_BLOCKED.

"Invalid transitions must fail" (task §8) is enforced mechanically: the ONLY
way InvestigationState.status ever changes is through `transition()` below,
which consults ALLOWED_TRANSITIONS and raises InvalidTransitionError rather
than silently accepting an out-of-order or fabricated jump. Nothing in
src/agents/ or src/tools/ ever writes `state.status = ...` directly — grepped
for and enforced by tests/test_state_machine.py::
test_no_module_assigns_status_directly.
"""

from __future__ import annotations

from agents.models import InvestigationState, InvestigationStatus, TERMINAL_STATUSES

_S = InvestigationStatus

# The linear "happy path" chain, task §8's exact order.
_LINEAR_CHAIN = [
    _S.PLANNED, _S.SECURITY_VALIDATED, _S.HYPOTHESES_GENERATED, _S.EVIDENCE_COLLECTION,
    _S.COUNTER_EVIDENCE, _S.CONTRADICTION_ANALYSIS, _S.METHOD_SELECTION,
    _S.CONFIDENCE_EVALUATION, _S.COMPLETED,
]

# Terminal alternatives reachable from most non-terminal states (task §8: the
# Orchestrator can abstain, hit a budget wall, or get security-blocked at any
# point in the pipeline). NEEDS_CLARIFICATION is reachable only from the two
# points a genuine ambiguity would first be discovered: right after planning
# (an unresolvable KPI/period request) or after confidence evaluation (the
# Confidence Judge itself can output NEEDS_CLARIFICATION, task §1F) — it is
# deliberately NOT reachable from every state, unlike ABSTAINED/
# BUDGET_EXCEEDED/SECURITY_BLOCKED, which can happen anywhere.
ALLOWED_TRANSITIONS: dict[InvestigationStatus, set[InvestigationStatus]] = {}
for i, state in enumerate(_LINEAR_CHAIN[:-1]):
    ALLOWED_TRANSITIONS[state] = {_LINEAR_CHAIN[i + 1]}

ALLOWED_TRANSITIONS[_S.PLANNED].add(_S.NEEDS_CLARIFICATION)
ALLOWED_TRANSITIONS[_S.CONFIDENCE_EVALUATION].add(_S.NEEDS_CLARIFICATION)

for state in list(_LINEAR_CHAIN[:-1]):
    ALLOWED_TRANSITIONS.setdefault(state, set())
    ALLOWED_TRANSITIONS[state].update({_S.ABSTAINED, _S.BUDGET_EXCEEDED, _S.SECURITY_BLOCKED})

ALLOWED_TRANSITIONS[_S.COMPLETED] = set()
for terminal in (_S.ABSTAINED, _S.NEEDS_CLARIFICATION, _S.BUDGET_EXCEEDED, _S.SECURITY_BLOCKED):
    ALLOWED_TRANSITIONS[terminal] = set()   # terminal — task §8, no transition out


class InvalidTransitionError(ValueError):
    pass


def transition(state: InvestigationState, new_status: InvestigationStatus, *, reason: str = "") -> InvestigationState:
    """The ONLY sanctioned way to change `state.status`. Mutates and returns
    the same InvestigationState (kept consistent with how the Orchestrator
    threads state through each agent call)."""
    current = state.status
    if current in TERMINAL_STATUSES:
        raise InvalidTransitionError(f"Investigation is already terminal ({current.value}); cannot transition to "
                                      f"{new_status.value}.")
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise InvalidTransitionError(
            f"Invalid transition {current.value} -> {new_status.value}. Allowed from {current.value}: "
            f"{sorted(s.value for s in allowed)}."
        )
    state.status = new_status
    state.status_history.append(new_status.value if not reason else f"{new_status.value} ({reason})")
    return state


def is_terminal(status: InvestigationStatus) -> bool:
    return status in TERMINAL_STATUSES
