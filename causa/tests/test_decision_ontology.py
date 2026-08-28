"""Step 7: DecisionOntology / DecisionScoringConfig loader tests.

Loads the REAL config/decision_ontology.yaml and config/decision_scoring.yaml
-- these are governed contracts under test, the same posture
tests/tests_kpi_contracts.py takes toward config/kpis.yaml. No fixtures, no
LLM, no canonical data.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import pytest  # noqa: E402

from decision.ontology import DecisionConfigError, DecisionOntology, DecisionScoringConfig  # noqa: E402


def test_ontology_loads_and_validates_real_config():
    ontology = DecisionOntology.load()
    ontology.validate()  # must not raise
    assert "delivery_delay" in ontology.list_drivers()
    assert "aov_decline" in ontology.list_drivers()


def test_delivery_delay_maps_to_fulfillment_logistics_category():
    ontology = DecisionOntology.load()
    entry = ontology.get_driver("delivery_delay")
    assert entry is not None
    assert entry["driver_category"] == "FULFILLMENT_LOGISTICS"


def test_aov_decline_maps_to_pricing_product_mix_category():
    ontology = DecisionOntology.load()
    entry = ontology.get_driver("aov_decline")
    assert entry is not None
    assert entry["driver_category"] == "PRICING_PRODUCT_MIX"


def test_driver_resolves_by_alias():
    ontology = DecisionOntology.load()
    assert ontology.get_driver("seller_fulfillment_delay") is not None
    assert ontology.get_driver("seller_fulfillment_delay")["driver"] == "delivery_delay"


def test_unsupported_driver_returns_none_not_keyerror():
    ontology = DecisionOntology.load()
    assert ontology.get_driver("totally_unknown_driver_xyz") is None
    assert ontology.is_supported("totally_unknown_driver_xyz") is False


def test_delivery_delay_owners_are_operations_or_supply_chain():
    ontology = DecisionOntology.load()
    action_types = ontology.action_types_for("delivery_delay")
    assert len(action_types) > 1  # multiple candidate action types must exist
    owners = {o for a in action_types for o in a["likely_owners"]}
    assert owners & {"Operations Manager", "Supply Chain Manager"}


def test_aov_decline_owners_are_commercial_pricing_or_product():
    ontology = DecisionOntology.load()
    action_types = ontology.action_types_for("aov_decline")
    assert len(action_types) > 1
    owners = {o for a in action_types for o in a["likely_owners"]}
    assert owners & {"Commercial Manager", "Pricing Manager", "Product Manager"}


def test_all_action_ids_globally_unique():
    ontology = DecisionOntology.load()
    seen = set()
    for driver in ontology.list_drivers():
        for action_type in ontology.action_types_for(driver):
            aid = action_type["action_id"]
            assert aid not in seen, f"duplicate action_id: {aid}"
            seen.add(aid)


def test_scoring_config_loads_and_weights_sum_to_one():
    scoring = DecisionScoringConfig.load()
    assert abs(sum(scoring.confidence_weights.values()) - 1.0) < 1e-9


def test_scoring_config_tier_tables_monotonic():
    scoring = DecisionScoringConfig.load()
    effort = scoring.effort_tier_scores
    assert effort["LOW"] < effort["MEDIUM"] < effort["HIGH"]
    controllability = scoring.controllability_tier_scores
    assert controllability["LOW"] < controllability["MEDIUM"] < controllability["HIGH"]


def test_scoring_config_rejects_bad_weight_sum(tmp_path):
    bad_yaml = tmp_path / "bad_scoring.yaml"
    bad_yaml.write_text(
        "version: '1.0'\n"
        "confidence_weights:\n"
        "  driver_confidence: 0.9\n"
        "  data_quality: 0.9\n"
        "  historical_support: 0.1\n"
        "  action_link_strength: 0.1\n"
        "action_link_strength_scores: {WEAK: 0.25, MODERATE: 0.6, STRONG: 0.9}\n"
        "effort_tier_scores: {LOW: 0.2, MEDIUM: 0.5, HIGH: 0.85}\n"
        "controllability_tier_scores: {LOW: 0.25, MEDIUM: 0.55, HIGH: 0.9}\n"
        "data_quality_scores: {HIGH: 1.0, MEDIUM: 0.6, LOW: 0.3, UNKNOWN: 0.1}\n"
        "prioritization: {formula: 'impact * confidence * controllability / effort', divide_by_zero_floor: 0.05}\n"
    )
    with pytest.raises(DecisionConfigError):
        DecisionScoringConfig.load(bad_yaml)


def test_unsupported_driver_policy_is_abstain():
    ontology = DecisionOntology.load()
    assert ontology.unsupported_driver_policy() == "abstain"
