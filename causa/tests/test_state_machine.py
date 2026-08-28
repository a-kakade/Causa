"""Step 5: state machine tests (task §8).

PLANNED -> SECURITY_VALIDATED -> HYPOTHESES_GENERATED -> EVIDENCE_COLLECTION
    -> COUNTER_EVIDENCE -> CONTRADICTION_ANALYSIS -> METHOD_SELECTION
    -> CONFIDENCE_EVALUATION -> COMPLETED, with ABSTAINED/NEEDS_CLARIFICATION/
BUDGET_EXCEEDED/SECURITY_BLOCKED as terminal alternatives. "Invalid
transitions must fail" is asserted directly against every non-adjacent pair.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.models import InvestigationState, InvestigationStatus, RequesterRole, TERMINAL_STATUSES  # noqa: E402
from agents.state_machine import ALLOWED_TRANSITIONS, InvalidTransitionError, is_terminal, transition  # noqa: E402

_S = InvestigationStatus
_LINEAR_CHAIN = [
    _S.PLANNED, _S.SECURITY_VALIDATED, _S.HYPOTHESES_GENERATED, _S.EVIDENCE_COLLECTION, _S.COUNTER_EVIDENCE,
    _S.CONTRADICTION_ANALYSIS, _S.METHOD_SELECTION, _S.CONFIDENCE_EVALUATION, _S.COMPLETED,
]


def _fresh_state() -> InvestigationState:
    return InvestigationState(investigation_id="t", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                               period="2017-11")


def test_full_linear_chain_succeeds():
    state = _fresh_state()
    for target in _LINEAR_CHAIN[1:]:
        transition(state, target)
    assert state.status == _S.COMPLETED
    assert state.status_history[0] == "PLANNED"
    assert state.status_history[-1] == "COMPLETED"


@pytest.mark.parametrize("target", [
    _S.EVIDENCE_COLLECTION, _S.COUNTER_EVIDENCE, _S.CONTRADICTION_ANALYSIS, _S.METHOD_SELECTION,
    _S.CONFIDENCE_EVALUATION, _S.COMPLETED,
])
def test_skipping_a_stage_from_planned_fails(target):
    state = _fresh_state()
    with pytest.raises(InvalidTransitionError):
        transition(state, target)


def test_going_backwards_fails():
    state = _fresh_state()
    transition(state, _S.SECURITY_VALIDATED)
    transition(state, _S.HYPOTHESES_GENERATED)
    with pytest.raises(InvalidTransitionError):
        transition(state, _S.PLANNED)
    with pytest.raises(InvalidTransitionError):
        transition(state, _S.SECURITY_VALIDATED)


@pytest.mark.parametrize("terminal", [_S.ABSTAINED, _S.BUDGET_EXCEEDED, _S.SECURITY_BLOCKED])
def test_terminal_alternatives_reachable_from_every_non_terminal_stage(terminal):
    for start in _LINEAR_CHAIN[:-1]:
        state = _fresh_state()
        state.status = start   # direct set only for test setup — normal code never does this
        transition(state, terminal)
        assert state.status == terminal


def test_needs_clarification_reachable_only_from_planned_and_confidence_evaluation():
    for start in _LINEAR_CHAIN:
        if start in (_S.PLANNED, _S.CONFIDENCE_EVALUATION, _S.COMPLETED):
            continue
        state = _fresh_state()
        state.status = start
        with pytest.raises(InvalidTransitionError):
            transition(state, _S.NEEDS_CLARIFICATION)

    for start in (_S.PLANNED, _S.CONFIDENCE_EVALUATION):
        state = _fresh_state()
        state.status = start
        transition(state, _S.NEEDS_CLARIFICATION)
        assert state.status == _S.NEEDS_CLARIFICATION


@pytest.mark.parametrize("terminal", [_S.COMPLETED, _S.ABSTAINED, _S.NEEDS_CLARIFICATION, _S.BUDGET_EXCEEDED,
                                       _S.SECURITY_BLOCKED])
def test_terminal_states_accept_no_further_transition(terminal):
    state = _fresh_state()
    state.status = terminal
    with pytest.raises(InvalidTransitionError):
        transition(state, _S.PLANNED)
    with pytest.raises(InvalidTransitionError):
        transition(state, _S.COMPLETED)


def test_is_terminal_matches_terminal_statuses_constant():
    for status in InvestigationStatus:
        assert is_terminal(status) == (status in TERMINAL_STATUSES)


def test_allowed_transitions_table_never_points_out_of_a_terminal_state():
    for terminal in TERMINAL_STATUSES:
        assert ALLOWED_TRANSITIONS.get(terminal, set()) == set()


# ---------------------------------------------------------------------------
# Structural: no module writes state.status directly (state_machine.py's own
# module docstring commitment) -- extended here to cover src/agents/*.py and
# src/tools/*.py, per this task's structural "state manipulation attempt"
# defense.
# ---------------------------------------------------------------------------

def test_no_module_assigns_status_directly():
    src_dir = REPO_ROOT / "src"
    offenders = []
    for path in list((src_dir / "agents").glob("*.py")) + list((src_dir / "tools").glob("*.py")):
        if path.name == "state_machine.py":
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and target.attr == "status":
                        offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, f"Direct state.status assignment found outside state_machine.py: {offenders}"
