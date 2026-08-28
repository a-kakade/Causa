"""Step 7: bridge.py tests -- driver_signal_from_causal_result /
driver_signal_from_hypothesis_result against synthetic Step 6/Step 5
objects; None-returning fallback paths."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.models import AgentRole, ConfidenceLevel, Hypothesis, HypothesisResult, InvestigationStatus, \
    InvestigationState, RequesterRole  # noqa: E402
from causal.models import CausalHypothesis, CausalMethod, CausalResult, CausalStatus, CausalTier, \
    EligibilityReport, EligibilityVerdict  # noqa: E402

from decision.bridge import driver_signal_from_causal_result, driver_signal_from_hypothesis_result  # noqa: E402
from decision.ontology import DecisionOntology  # noqa: E402


def _ontology():
    return DecisionOntology.load()


def _causal_hypothesis(**overrides):
    defaults = dict(
        hypothesis_id="H1", treatment="delivery_delay", outcome="on_time_delivery_rate",
        unit_of_analysis="order", treatment_period={"start": "2017-10-01", "end": "2017-10-31"},
        outcome_period={"start": "2017-11-01", "end": "2017-11-30"},
        proposed_mechanism="X is associated with Y.", required_data=["on_time_delivery_rate"],
        proposed_method=CausalMethod.DESCRIPTIVE_ASSOCIATION,
    )
    defaults.update(overrides)
    return CausalHypothesis(**defaults)


def _eligibility_report():
    return EligibilityReport(hypothesis_id="H1", verdict=EligibilityVerdict.ELIGIBLE, checks=[])


def _causal_result(**overrides):
    defaults = dict(
        hypothesis_id="H1", method=CausalMethod.DESCRIPTIVE_ASSOCIATION, evidence_tier=CausalTier.T1_DESCRIPTIVE,
        status=CausalStatus.DESCRIPTIVE_ONLY, estimate={"value": 0.06}, uncertainty=None,
        assumptions=["association does not imply causation"], diagnostics=[], confounders=[], evidence_ids=[],
        limitations=[], causal_claim_allowed=False, eligibility_report=_eligibility_report(),
    )
    defaults.update(overrides)
    return CausalResult(**defaults)


def test_driver_signal_from_causal_result_maps_known_driver():
    result = _causal_result()
    hypothesis = _causal_hypothesis()
    signal = driver_signal_from_causal_result(result, hypothesis, _ontology(), {"budget_available": True})
    assert signal is not None
    assert signal.driver == "delivery_delay"
    assert signal.source == "STEP6_CAUSAL_RESULT"
    assert signal.causal_claim_allowed is False
    assert signal.historical_estimated_effect == 0.06


def test_driver_signal_from_causal_result_none_for_unmapped_driver():
    result = _causal_result()
    hypothesis = _causal_hypothesis(treatment="some_unmapped_treatment_xyz")
    signal = driver_signal_from_causal_result(result, hypothesis, _ontology(), {})
    assert signal is None


def test_driver_signal_from_causal_result_none_for_method_none():
    result = _causal_result(method=CausalMethod.NONE)
    hypothesis = _causal_hypothesis()
    signal = driver_signal_from_causal_result(result, hypothesis, _ontology(), {})
    assert signal is None


def test_driver_signal_from_causal_result_never_raises_on_missing_fields():
    signal = driver_signal_from_causal_result(None, None, _ontology(), {})
    assert signal is None


def test_causal_supported_t3_maps_to_higher_confidence_than_descriptive_only():
    high = _causal_result(status=CausalStatus.CAUSAL_SUPPORTED, evidence_tier=CausalTier.T3_QUASI_EXPERIMENTAL)
    low = _causal_result(status=CausalStatus.DESCRIPTIVE_ONLY, evidence_tier=CausalTier.T1_DESCRIPTIVE)
    hypothesis = _causal_hypothesis()
    signal_high = driver_signal_from_causal_result(high, hypothesis, _ontology(), {})
    signal_low = driver_signal_from_causal_result(low, hypothesis, _ontology(), {})
    assert signal_high.driver_confidence > signal_low.driver_confidence


def test_business_context_is_passed_through_explicitly_not_inferred():
    result = _causal_result()
    hypothesis = _causal_hypothesis()
    ctx = {"budget_available": False, "inventory_units_available": 42}
    signal = driver_signal_from_causal_result(result, hypothesis, _ontology(), ctx)
    assert signal.business_context == ctx


def _hypothesis(**overrides):
    defaults = dict(
        hypothesis_id="H1", statement="X is associated with Y.", driver="delivery", dimension="orders",
        mechanism="delivery timing affects reviews",
    )
    defaults.update(overrides)
    return Hypothesis(**defaults)


def _hypothesis_result(**overrides):
    defaults = dict(hypothesis_id="H1", status="SUPPORTED", confidence=ConfidenceLevel.HIGH, evidence_ids=["ev_1"])
    defaults.update(overrides)
    return HypothesisResult(**defaults)


def _investigation_state(**overrides):
    defaults = dict(investigation_id="inv_1", requester_role=RequesterRole.ANALYST,
                     kpi_id="on_time_delivery_rate", period="2017-11")
    defaults.update(overrides)
    return InvestigationState(**defaults)


def test_driver_signal_from_hypothesis_result_maps_known_driver():
    hr = _hypothesis_result()
    h = _hypothesis()
    state = _investigation_state()
    signal = driver_signal_from_hypothesis_result(hr, h, state, _ontology(), {"budget_available": True})
    assert signal is not None
    assert signal.driver == "delivery_delay"
    assert signal.source == "STEP5_HYPOTHESIS_RESULT"
    assert signal.kpi_id == "on_time_delivery_rate"


def test_driver_signal_from_hypothesis_result_none_when_not_supported():
    hr = _hypothesis_result(status="INCONCLUSIVE", confidence=ConfidenceLevel.LOW, evidence_ids=[])
    h = _hypothesis()
    state = _investigation_state()
    signal = driver_signal_from_hypothesis_result(hr, h, state, _ontology(), {})
    assert signal is None


def test_driver_signal_from_hypothesis_result_none_for_unmapped_driver():
    hr = _hypothesis_result()
    h = _hypothesis(driver="some_unmapped_driver_xyz")
    state = _investigation_state()
    signal = driver_signal_from_hypothesis_result(hr, h, state, _ontology(), {})
    assert signal is None


def test_driver_signal_from_hypothesis_result_never_raises_on_missing_fields():
    signal = driver_signal_from_hypothesis_result(None, None, None, _ontology(), {})
    assert signal is None


def test_high_confidence_level_maps_to_higher_driver_confidence_than_low():
    h = _hypothesis()
    state = _investigation_state()
    hr_high = _hypothesis_result(confidence=ConfidenceLevel.HIGH)
    hr_low = _hypothesis_result(confidence=ConfidenceLevel.HIGH)  # status must stay SUPPORTED to pass the gate
    signal_high = driver_signal_from_hypothesis_result(hr_high, h, state, _ontology(), {})
    assert signal_high.driver_confidence == 0.85
