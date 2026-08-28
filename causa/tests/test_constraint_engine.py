"""Step 7: constraint_engine.py tests -- one test per status per constraint
type, pure synthetic business_context dicts."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.constraint_engine import evaluate_constraints  # noqa: E402
from decision.models import ConstraintStatus  # noqa: E402
from decision.ontology import DecisionScoringConfig  # noqa: E402


def _scoring():
    return DecisionScoringConfig.load()


def _status(constraint_name, checks):
    return next(c.status for c in checks if c.constraint == constraint_name)


# -- budget -------------------------------------------------------------

def test_budget_pass_when_available_and_no_pct_given():
    checks = evaluate_constraints(["budget"], {"budget_available": True}, "Operations Manager", _scoring())
    assert _status("budget", checks) == ConstraintStatus.PASS


def test_budget_warning_when_low_remaining_pct():
    ctx = {"budget_available": True, "budget_remaining_pct": 10}
    checks = evaluate_constraints(["budget"], ctx, "Operations Manager", _scoring())
    assert _status("budget", checks) == ConstraintStatus.WARNING


def test_budget_blocked_when_unavailable():
    checks = evaluate_constraints(["budget"], {"budget_available": False}, "Operations Manager", _scoring())
    assert _status("budget", checks) == ConstraintStatus.BLOCKED


def test_budget_warning_when_not_supplied():
    checks = evaluate_constraints(["budget"], {}, "Operations Manager", _scoring())
    assert _status("budget", checks) == ConstraintStatus.WARNING


# -- operational_capacity ------------------------------------------------

def test_operational_capacity_pass():
    ctx = {"operational_capacity_available": True}
    checks = evaluate_constraints(["operational_capacity"], ctx, "Operations Manager", _scoring())
    assert _status("operational_capacity", checks) == ConstraintStatus.PASS


def test_operational_capacity_blocked_at_full_utilization():
    ctx = {"operational_capacity_available": True, "operational_capacity_utilization_pct": 100}
    checks = evaluate_constraints(["operational_capacity"], ctx, "Operations Manager", _scoring())
    assert _status("operational_capacity", checks) == ConstraintStatus.BLOCKED


def test_operational_capacity_warning_near_full():
    ctx = {"operational_capacity_available": True, "operational_capacity_utilization_pct": 90}
    checks = evaluate_constraints(["operational_capacity"], ctx, "Operations Manager", _scoring())
    assert _status("operational_capacity", checks) == ConstraintStatus.WARNING


# -- inventory ------------------------------------------------------------

def test_inventory_pass_with_sufficient_units():
    checks = evaluate_constraints(["inventory"], {"inventory_units_available": 5000}, "Product Manager", _scoring())
    assert _status("inventory", checks) == ConstraintStatus.PASS


def test_inventory_warning_when_low():
    checks = evaluate_constraints(["inventory"], {"inventory_units_available": 50}, "Product Manager", _scoring())
    assert _status("inventory", checks) == ConstraintStatus.WARNING


def test_inventory_blocked_when_zero():
    checks = evaluate_constraints(["inventory"], {"inventory_units_available": 0}, "Product Manager", _scoring())
    assert _status("inventory", checks) == ConstraintStatus.BLOCKED


# -- geography --------------------------------------------------------------

def test_geography_pass_when_covered():
    checks = evaluate_constraints(["geography"], {"geography_coverage": True}, "Supply Chain Manager", _scoring())
    assert _status("geography", checks) == ConstraintStatus.PASS


def test_geography_blocked_when_not_covered():
    checks = evaluate_constraints(["geography"], {"geography_coverage": False}, "Supply Chain Manager", _scoring())
    assert _status("geography", checks) == ConstraintStatus.BLOCKED


def test_geography_warning_when_not_supplied():
    checks = evaluate_constraints(["geography"], {}, "Supply Chain Manager", _scoring())
    assert _status("geography", checks) == ConstraintStatus.WARNING


# -- decision_rights ----------------------------------------------------------

def test_decision_rights_pass_when_owner_authorized():
    ctx = {"authorized_owner_roles": ["Operations Manager", "Pricing Manager"]}
    checks = evaluate_constraints(["decision_rights"], ctx, "Operations Manager", _scoring())
    assert _status("decision_rights", checks) == ConstraintStatus.PASS


def test_decision_rights_blocked_when_owner_not_authorized():
    ctx = {"authorized_owner_roles": ["Pricing Manager"]}
    checks = evaluate_constraints(["decision_rights"], ctx, "Operations Manager", _scoring())
    assert _status("decision_rights", checks) == ConstraintStatus.BLOCKED


def test_decision_rights_warning_when_not_supplied():
    checks = evaluate_constraints(["decision_rights"], {}, "Operations Manager", _scoring())
    assert _status("decision_rights", checks) == ConstraintStatus.WARNING


# -- dispatch behavior ----------------------------------------------------------

def test_only_relevant_constraints_are_evaluated():
    checks = evaluate_constraints(["budget"], {}, "Operations Manager", _scoring())
    assert len(checks) == 1
    assert checks[0].constraint == "budget"


def test_evaluation_order_is_fixed_regardless_of_input_order():
    ctx = {"budget_available": True, "operational_capacity_available": True}
    checks_a = evaluate_constraints(["operational_capacity", "budget"], ctx, "Operations Manager", _scoring())
    checks_b = evaluate_constraints(["budget", "operational_capacity"], ctx, "Operations Manager", _scoring())
    assert [c.constraint for c in checks_a] == [c.constraint for c in checks_b] == ["budget", "operational_capacity"]


def test_empty_relevant_constraints_yields_no_checks():
    checks = evaluate_constraints([], {}, "Operations Manager", _scoring())
    assert checks == []
