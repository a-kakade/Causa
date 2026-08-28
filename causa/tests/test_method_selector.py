"""Step 6: deterministic method selector tests.

Pure, synthetic -- builds EligibilityReport/CausalHypothesis by hand (no
canonical data, no LLM), matching the style of
tests/test_confidence.py/test_contradictions.py's synthetic-dataclass tests.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from causal import causal_impact, method_selector  # noqa: E402
from causal.models import (  # noqa: E402
    CausalHypothesis,
    CausalMethod,
    CheckResult,
    CheckResultStatus,
    EligibilityReport,
    EligibilityVerdict,
)


def _hypothesis(**overrides):
    defaults = dict(
        hypothesis_id="H1", treatment="orders", outcome="revenue", unit_of_analysis="order",
        treatment_period={"start": "2017-10-01", "end": "2017-10-31"},
        outcome_period={"start": "2017-11-01", "end": "2017-11-30"},
        proposed_mechanism="X is associated with Y.", required_data=["revenue", "orders"],
        proposed_method=CausalMethod.PVM,
    )
    defaults.update(overrides)
    return CausalHypothesis(**defaults)


def _report(verdict=EligibilityVerdict.ELIGIBLE, hard=(), soft=()):
    checks = [CheckResult(name, CheckResultStatus.HARD_FAIL, "x") for name in hard]
    checks += [CheckResult(name, CheckResultStatus.SOFT_FAIL, "x") for name in soft]
    return EligibilityReport(hypothesis_id="H1", verdict=verdict, checks=checks,
                              hard_fail_checks=list(hard), soft_fail_checks=list(soft))


def test_pvm_selected_for_revenue_volume_price_mix_hypothesis_and_locked_to_t2():
    h = _hypothesis(treatment="orders", outcome="revenue", proposed_method=CausalMethod.PVM)
    result = method_selector.select_method(h, _report())
    assert result.method == CausalMethod.PVM
    assert "PVM" not in result.why_other_methods_rejected  # PVM was selected, not rejected


def test_descriptive_association_selected_when_no_group_structure_available():
    """A group-based hypothesis (treatment_dimension set) with no control
    group can reach neither PVM, DiD (needs both groups), nor ITS (needs
    treatment_dimension=None) -- it must fall all the way through to a plain
    descriptive association, given an otherwise fully ELIGIBLE report."""
    h = _hypothesis(treatment="customer_state", outcome="revenue", treatment_dimension="customer_state",
                     treatment_group_value="SP", control_group_value=None,
                     proposed_method=CausalMethod.DESCRIPTIVE_ASSOCIATION)
    result = method_selector.select_method(h, _report())
    assert result.method == CausalMethod.DESCRIPTIVE_ASSOCIATION


def test_did_selected_only_when_treatment_and_control_group_and_pre_period_present():
    h = _hypothesis(treatment="customer_state", outcome="revenue", treatment_dimension="customer_state",
                     treatment_group_value="SP", control_group_value="all_other_states",
                     proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES)
    result = method_selector.select_method(h, _report())
    assert result.method == CausalMethod.DIFFERENCE_IN_DIFFERENCES


def test_did_rejected_reason_cites_missing_control_group_specifically():
    h = _hypothesis(treatment="customer_state", outcome="revenue", treatment_dimension="customer_state",
                     treatment_group_value="SP", control_group_value=None,
                     proposed_method=CausalMethod.DESCRIPTIVE_ASSOCIATION)
    result = method_selector.select_method(h, _report())
    assert result.method != CausalMethod.DIFFERENCE_IN_DIFFERENCES
    reason = result.why_other_methods_rejected[CausalMethod.DIFFERENCE_IN_DIFFERENCES.value]
    assert "control_group_value" in reason


def test_its_selected_for_time_only_intervention_with_known_date():
    h = _hypothesis(treatment="revenue", outcome="revenue", treatment_dimension=None,
                     proposed_method=CausalMethod.INTERRUPTED_TIME_SERIES)
    result = method_selector.select_method(h, _report())
    assert result.method == CausalMethod.INTERRUPTED_TIME_SERIES


def test_causal_impact_falls_back_to_descriptive_when_unavailable(monkeypatch):
    monkeypatch.setattr(causal_impact, "is_causal_impact_available", lambda: False)
    h = _hypothesis(treatment="customer_state", outcome="revenue", treatment_dimension="customer_state",
                     treatment_group_value="SP", control_group_value=None,
                     proposed_method=CausalMethod.CAUSAL_IMPACT)
    result = method_selector.select_method(h, _report())
    assert result.method != CausalMethod.CAUSAL_IMPACT
    assert "METHOD_UNAVAILABLE" in result.why_other_methods_rejected[CausalMethod.CAUSAL_IMPACT.value] or \
        "not installed" in result.why_other_methods_rejected[CausalMethod.CAUSAL_IMPACT.value]


def test_causal_ineligible_verdict_short_circuits_to_method_none():
    h = _hypothesis()
    result = method_selector.select_method(h, _report(verdict=EligibilityVerdict.CAUSAL_INELIGIBLE,
                                                        hard=("treatment_precedes_outcome",)))
    assert result.method == CausalMethod.NONE


def test_why_other_methods_rejected_always_has_all_6_non_selected_keys():
    h = _hypothesis()
    result = method_selector.select_method(h, _report())
    assert len(result.why_other_methods_rejected) == 6
    assert set(result.why_other_methods_rejected) == {m.value for m in CausalMethod if m != result.method}


def test_method_selection_is_deterministic_given_identical_inputs():
    h = _hypothesis(treatment="customer_state", outcome="revenue", treatment_dimension="customer_state",
                     treatment_group_value="SP", control_group_value="all_other_states")
    report = _report()
    r1 = method_selector.select_method(h, report)
    r2 = method_selector.select_method(h, report)
    assert r1 == r2


def test_method_selector_never_imports_llm_client():
    path = REPO_ROOT / "src" / "causal" / "method_selector.py"
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names.add(getattr(node, "module", None) or "")
            for alias in node.names:
                names.add(alias.name)
    assert not any("llm" in n.lower() or "groq" in n.lower() for n in names)
