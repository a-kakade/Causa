"""Step 7: scoring.py tests -- priority arithmetic, divide-by-zero guard,
tier lookups, config swap changes output."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.ontology import DecisionScoringConfig  # noqa: E402
from decision.scoring import compute_controllability, compute_effort, compute_priority  # noqa: E402


def _scoring():
    return DecisionScoringConfig.load()


def test_controllability_tier_lookup():
    scoring = _scoring()
    score, basis = compute_controllability({"controllability_tier": "HIGH"}, scoring)
    assert score == scoring.controllability_tier_scores["HIGH"]
    assert "HIGH" in basis


def test_effort_tier_lookup():
    scoring = _scoring()
    score, basis = compute_effort({"effort_tier": "LOW"}, scoring)
    assert score == scoring.effort_tier_scores["LOW"]
    assert "LOW" in basis


def test_priority_formula_correctness():
    scoring = _scoring()
    priority = compute_priority(impact=1000.0, confidence=0.8, controllability=0.9, effort=0.5, scoring_config=scoring)
    assert priority == (1000.0 * 0.8 * 0.9) / 0.5


def test_priority_divide_by_zero_guarded():
    scoring = _scoring()
    # effort=0.0 must not raise ZeroDivisionError -- clamped to the config floor.
    priority = compute_priority(impact=100.0, confidence=0.5, controllability=0.5, effort=0.0, scoring_config=scoring)
    floor = scoring.divide_by_zero_floor()
    assert priority == (100.0 * 0.5 * 0.5) / floor


def test_priority_with_unestimable_impact_treated_as_zero_not_fabricated():
    scoring = _scoring()
    priority = compute_priority(impact=None, confidence=0.9, controllability=0.9, effort=0.5, scoring_config=scoring)
    assert priority == 0.0


def test_higher_impact_yields_higher_priority():
    scoring = _scoring()
    low = compute_priority(impact=100.0, confidence=0.5, controllability=0.5, effort=0.5, scoring_config=scoring)
    high = compute_priority(impact=1000.0, confidence=0.5, controllability=0.5, effort=0.5, scoring_config=scoring)
    assert high > low


def test_higher_effort_yields_lower_priority():
    scoring = _scoring()
    low_effort = compute_priority(impact=100.0, confidence=0.5, controllability=0.5, effort=0.2, scoring_config=scoring)
    high_effort = compute_priority(impact=100.0, confidence=0.5, controllability=0.5, effort=0.9, scoring_config=scoring)
    assert low_effort > high_effort


def test_controllability_config_swap_changes_output(tmp_path):
    custom_yaml = tmp_path / "custom_scoring.yaml"
    custom_yaml.write_text(
        "version: '1.0'\n"
        "confidence_weights: {driver_confidence: 0.35, data_quality: 0.25, historical_support: 0.25, action_link_strength: 0.15}\n"
        "action_link_strength_scores: {WEAK: 0.25, MODERATE: 0.6, STRONG: 0.9}\n"
        "effort_tier_scores: {LOW: 0.2, MEDIUM: 0.5, HIGH: 0.85}\n"
        "controllability_tier_scores: {LOW: 0.1, MEDIUM: 0.2, HIGH: 0.3}\n"  # different from the default config
        "data_quality_scores: {HIGH: 1.0, MEDIUM: 0.6, LOW: 0.3, UNKNOWN: 0.1}\n"
        "prioritization: {formula: 'impact * confidence * controllability / effort', divide_by_zero_floor: 0.05}\n"
    )
    custom = DecisionScoringConfig.load(custom_yaml)
    default = _scoring()
    score_custom, _ = compute_controllability({"controllability_tier": "HIGH"}, custom)
    score_default, _ = compute_controllability({"controllability_tier": "HIGH"}, default)
    assert score_custom != score_default
    assert score_custom == 0.3
