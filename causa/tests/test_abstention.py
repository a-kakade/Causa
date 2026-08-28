"""Step 6: abstention-outcome tests, plus the real end-to-end November 2017
four-hypothesis integration test.

`compute_abstention_status` (causal.diagnostics) is the single, shared policy
every method wrapper calls into -- covered here directly (synthetic inputs)
and indirectly (real data) via the four Olist hypotheses that
scripts/step6_causal_validation.py also runs.
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from causal.diagnostics import compute_abstention_status  # noqa: E402
from causal.engine import run_causal_analysis  # noqa: E402
from causal.models import CausalHypothesis, CausalMethod, CausalStatus, CausalTier, EligibilityVerdict  # noqa: E402

OCT = ("2017-10-01", "2017-10-31")
NOV = ("2017-11-01", "2017-11-30")


def test_pvm_maps_to_arithmetic_only_status():
    status = compute_abstention_status(CausalTier.T2_ARITHMETIC, EligibilityVerdict.PARTIALLY_ELIGIBLE, True, False)
    assert status == CausalStatus.ARITHMETIC_ONLY


def test_descriptive_association_maps_to_descriptive_only_status():
    status = compute_abstention_status(CausalTier.T1_DESCRIPTIVE, EligibilityVerdict.INELIGIBLE, True, False)
    assert status == CausalStatus.DESCRIPTIVE_ONLY


def test_causal_ineligible_maps_to_causal_rejected_status():
    status = compute_abstention_status(CausalTier.T1_DESCRIPTIVE, EligibilityVerdict.CAUSAL_INELIGIBLE, False, False)
    assert status == CausalStatus.CAUSAL_REJECTED


def test_partially_eligible_with_failed_diagnostics_maps_to_causal_insufficient():
    status = compute_abstention_status(CausalTier.T3_QUASI_EXPERIMENTAL, EligibilityVerdict.PARTIALLY_ELIGIBLE,
                                        False, False)
    assert status == CausalStatus.CAUSAL_INSUFFICIENT


def test_eligible_with_all_diagnostics_passing_maps_to_causal_supported():
    status = compute_abstention_status(CausalTier.T3_QUASI_EXPERIMENTAL, EligibilityVerdict.ELIGIBLE, True, True)
    assert status == CausalStatus.CAUSAL_SUPPORTED


def test_never_forces_a_causal_conclusion_when_data_is_ambiguous():
    tiers = list(CausalTier)
    verdicts = list(EligibilityVerdict)
    for tier, verdict, diag_passed, claim_allowed in itertools.product(tiers, verdicts, (True, False), (True, False)):
        status = compute_abstention_status(tier, verdict, diag_passed, claim_allowed)
        assert isinstance(status, CausalStatus)
        if status == CausalStatus.CAUSAL_SUPPORTED:
            # CAUSAL_SUPPORTED is reachable only through the single explicit,
            # fully-earned combination -- never as a default/fallback.
            assert tier in (CausalTier.T3_QUASI_EXPERIMENTAL, CausalTier.T4_EXPERIMENTAL)
            assert verdict == EligibilityVerdict.ELIGIBLE
            assert diag_passed and claim_allowed


def test_no_control_group_scenario_yields_descriptive_only_not_a_forced_causal_claim(engine):
    h = CausalHypothesis(
        hypothesis_id="H_no_control", treatment="customer_state", outcome="revenue",
        unit_of_analysis="customer_state",
        treatment_period={"start": "2017-06-01", "end": "2017-10-31"}, outcome_period={"start": NOV[0], "end": NOV[1]},
        proposed_mechanism="Revenue growth may be associated with customers in SP.",
        required_data=["revenue"], proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        treatment_dimension="customer_state", treatment_group_value="SP", control_group_value=None,
    )
    result = run_causal_analysis(h, engine, engine.registry)
    assert result.causal_claim_allowed is False
    assert result.method != CausalMethod.DIFFERENCE_IN_DIFFERENCES
    assert result.status in (CausalStatus.DESCRIPTIVE_ONLY, CausalStatus.CAUSAL_INSUFFICIENT)


# ---------------------------------------------------------------------------
# The real November 2017, four-hypothesis integration test
# ---------------------------------------------------------------------------


def _order_volume_hypothesis():
    return CausalHypothesis(
        hypothesis_id="C1_order_volume", treatment="orders", outcome="revenue", unit_of_analysis="order",
        treatment_period={"start": OCT[0], "end": OCT[1]}, outcome_period={"start": NOV[0], "end": NOV[1]},
        proposed_mechanism="Order volume growth is associated with revenue growth via the PVM volume effect.",
        required_data=["revenue", "orders"], proposed_method=CausalMethod.PVM,
    )


def _category_growth_hypothesis():
    return CausalHypothesis(
        hypothesis_id="C2_category_growth", treatment="product_category", outcome="revenue",
        unit_of_analysis="product_category",
        treatment_period={"start": "2017-01-01", "end": "2017-11-30"}, outcome_period={"start": OCT[0], "end": NOV[1]},
        proposed_mechanism="Revenue growth may be associated with disproportionate growth in bed_bath_table.",
        required_data=["revenue"], proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        treatment_dimension="product_category", treatment_group_value="bed_bath_table",
        control_group_value="all_other_categories",
    )


def _delivery_review_hypothesis():
    return CausalHypothesis(
        hypothesis_id="C3_delivery_review", treatment="on_time_delivery_rate", outcome="avg_review_score",
        unit_of_analysis="order",
        treatment_period={"start": OCT[0], "end": OCT[1]}, outcome_period={"start": NOV[0], "end": NOV[1]},
        proposed_mechanism="Delivery timing may be associated with the review score customers subsequently submit.",
        required_data=["avg_delivery_days", "avg_review_score"], proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
    )


def _geographic_hypothesis():
    return CausalHypothesis(
        hypothesis_id="C4_geographic", treatment="customer_state", outcome="revenue", unit_of_analysis="customer_state",
        treatment_period={"start": "2017-01-01", "end": "2017-11-30"}, outcome_period={"start": OCT[0], "end": NOV[1]},
        proposed_mechanism="Revenue growth may be associated with disproportionate growth from customers in SP.",
        required_data=["revenue"], proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        treatment_dimension="customer_state", treatment_group_value="SP", control_group_value="all_other_states",
    )


def test_full_november_2017_run_produces_all_four_expected_statuses(engine):
    hypotheses = [_order_volume_hypothesis(), _category_growth_hypothesis(),
                  _delivery_review_hypothesis(), _geographic_hypothesis()]
    results = [run_causal_analysis(h, engine, engine.registry) for h in hypotheses]

    # Every real result: no causal claim, never SUPPORTED/T3/T4 -- the
    # honest, intended outcome on this dataset (task's own words: "this is a
    # successful outcome").
    for result in results:
        assert result.causal_claim_allowed is False
        assert result.evidence_tier in (CausalTier.T1_DESCRIPTIVE, CausalTier.T2_ARITHMETIC)
        assert result.status != CausalStatus.CAUSAL_SUPPORTED

    order_volume, category_growth, delivery_review, geographic = results
    assert order_volume.method == CausalMethod.PVM
    assert order_volume.evidence_tier == CausalTier.T2_ARITHMETIC
    assert order_volume.status == CausalStatus.ARITHMETIC_ONLY
    assert order_volume.evidence_ids  # real Step 4 evidence citations

    for result in (category_growth, delivery_review, geographic):
        assert result.evidence_tier == CausalTier.T1_DESCRIPTIVE
        assert result.status == CausalStatus.DESCRIPTIVE_ONLY

    # Category-growth and geographic both fail specifically because group
    # membership has no assignment timing.
    assert "treatment_precedes_outcome" in category_growth.eligibility_report.hard_fail_checks
    assert "treatment_precedes_outcome" in geographic.eligibility_report.hard_fail_checks

    # Delivery/review is the one hypothesis with a genuinely well-formed
    # temporal order (Oct delivery precedes Nov review) -- it fails on
    # control_variation (no clean group split), not on timing.
    assert "treatment_precedes_outcome" not in delivery_review.eligibility_report.hard_fail_checks
    assert delivery_review.confounders  # Black Friday is honestly reported, not hidden
