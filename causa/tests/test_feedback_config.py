"""Step 9: config.py tests -- config/feedback.yaml loads and validates, and
stays in sync with the enforced enums in feedback/models.py."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from feedback.config import FeedbackConfig, FeedbackConfigError  # noqa: E402


def test_config_loads_and_validates():
    config = FeedbackConfig.load()
    assert config.min_approvals_required() >= 1


def test_evaluation_thresholds_present():
    config = FeedbackConfig.load()
    thresholds = config.evaluation_thresholds()
    assert "causal_correctness" in thresholds
    assert 0 <= thresholds["causal_correctness"] <= 1


def test_out_of_sync_category_list_raises():
    config = FeedbackConfig({
        "feedback_ratings": ["CORRECT"],  # incomplete on purpose
        "feedback_categories": ["DATA"],
        "feedback_statuses": ["UNREVIEWED"],
        "review_statuses": ["PENDING"],
        "context_types": ["OTHER"],
        "correction_types": ["OTHER"],
        "review_workflow": {"min_approvals_required": 1},
        "evaluation": {"thresholds": {}},
    })
    try:
        config.validate()
        assert False, "expected FeedbackConfigError"
    except FeedbackConfigError:
        pass


def test_invalid_threshold_raises():
    config = FeedbackConfig.load()
    raw = config.to_dict()
    raw["evaluation"]["thresholds"]["numeric_accuracy"] = 5.0  # out of [0,1]
    bad_config = FeedbackConfig(raw)
    try:
        bad_config.validate()
        assert False, "expected FeedbackConfigError"
    except FeedbackConfigError:
        pass
