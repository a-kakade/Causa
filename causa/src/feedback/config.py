"""
config.py — Step 9: loader for config/feedback.yaml.

Structurally identical to story/config.py::StorytellingConfig: load,
validate, expose read-only accessors. No business logic. validate() also
cross-checks that config/feedback.yaml's documented taxonomy lists stay in
sync with the ENFORCED enums in feedback/models.py -- catching a config
drift (someone edits the YAML without updating the enum, or vice versa)
loudly at load time rather than silently.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from feedback.models import (
    ContextType,
    CorrectionType,
    FeedbackCategory,
    FeedbackRating,
    FeedbackStatus,
    ReviewStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FEEDBACK_CONFIG_PATH = REPO_ROOT / "config" / "feedback.yaml"


class FeedbackConfigError(Exception):
    """Raised when config/feedback.yaml fails validation."""


class FeedbackConfig:
    def __init__(self, raw_config: dict[str, Any]):
        self._raw = raw_config

    @classmethod
    def load(cls, config_path: Path = FEEDBACK_CONFIG_PATH) -> "FeedbackConfig":
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        instance = cls(raw_config)
        instance.validate()
        return instance

    def validate(self) -> None:
        errors: list[str] = []

        _check_enum_sync(self._raw.get("feedback_ratings", []), FeedbackRating, "feedback_ratings", errors)
        _check_enum_sync(self._raw.get("feedback_categories", []), FeedbackCategory, "feedback_categories", errors)
        _check_enum_sync(self._raw.get("feedback_statuses", []), FeedbackStatus, "feedback_statuses", errors)
        _check_enum_sync(self._raw.get("review_statuses", []), ReviewStatus, "review_statuses", errors)
        _check_enum_sync(self._raw.get("context_types", []), ContextType, "context_types", errors)
        _check_enum_sync(self._raw.get("correction_types", []), CorrectionType, "correction_types", errors)

        workflow = self._raw.get("review_workflow", {})
        if not isinstance(workflow.get("min_approvals_required"), int) or workflow.get("min_approvals_required") < 1:
            errors.append("review_workflow.min_approvals_required must be a positive integer")

        thresholds = self._raw.get("evaluation", {}).get("thresholds", {})
        for key, value in thresholds.items():
            if not isinstance(value, (int, float)) or not (0 <= value <= 1):
                errors.append(f"evaluation.thresholds.{key} must be a number between 0 and 1")

        if errors:
            raise FeedbackConfigError(
                f"{len(errors)} feedback config violation(s) found:\n  - " + "\n  - ".join(errors)
            )

    # -- read-only accessors ---------------------------------------------------

    def min_approvals_required(self) -> int:
        return int(self._raw["review_workflow"]["min_approvals_required"])

    def evaluation_thresholds(self) -> dict[str, float]:
        return dict(self._raw.get("evaluation", {}).get("thresholds", {}))

    def to_dict(self) -> dict[str, Any]:
        return dict(self._raw)


def _check_enum_sync(configured: list[str], enum_cls, field_name: str, errors: list[str]) -> None:
    configured_set = set(configured)
    enum_set = {member.value for member in enum_cls}
    if configured_set != enum_set:
        errors.append(
            f"{field_name} in config/feedback.yaml ({sorted(configured_set)}) does not match "
            f"feedback.models.{enum_cls.__name__} ({sorted(enum_set)})"
        )
