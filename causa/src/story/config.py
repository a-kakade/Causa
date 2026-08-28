"""
config.py — Step 8: loader for config/storytelling.yaml.

Structurally identical to decision/ontology.py's DecisionScoringConfig:
load, validate, expose read-only accessors. No business logic, no
computation -- only load/validate/accessor. See src/story/persona.py for
the sibling persona-definition loader (kept in its own file since it also
carries selection logic, not just config access).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
STORYTELLING_CONFIG_PATH = REPO_ROOT / "config" / "storytelling.yaml"


class StorytellingConfigError(Exception):
    """Raised when config/storytelling.yaml fails validation. Never raised
    for a generation/verification error -- this module doesn't run either."""


class StorytellingConfig:
    def __init__(self, raw_config: dict[str, Any]):
        self._raw = raw_config

    @classmethod
    def load(cls, config_path: Path = STORYTELLING_CONFIG_PATH) -> "StorytellingConfig":
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        instance = cls(raw_config)
        instance.validate()
        return instance

    def validate(self) -> None:
        errors: list[str] = []

        llm = self._raw.get("llm", {})
        if not isinstance(llm.get("temperature"), (int, float)):
            errors.append("llm.temperature must be a number")
        for key in ("max_tokens_planner", "max_tokens_generator"):
            if not isinstance(llm.get(key), int) or llm.get(key) <= 0:
                errors.append(f"llm.{key} must be a positive integer")

        generation = self._raw.get("generation", {})
        if not isinstance(generation.get("max_generation_retries"), int) or generation.get("max_generation_retries") < 0:
            errors.append("generation.max_generation_retries must be a non-negative integer")

        verification = self._raw.get("verification", {})
        for key in ("numeric_tolerance", "numeric_absolute_floor", "minimum_magnitude"):
            value = verification.get(key)
            if not isinstance(value, (int, float)) or value < 0:
                errors.append(f"verification.{key} must be a non-negative number")

        fallback = self._raw.get("fallback", {})
        if not isinstance(fallback.get("allow_deterministic_fallback"), bool):
            errors.append("fallback.allow_deterministic_fallback must be a boolean")

        if errors:
            raise StorytellingConfigError(
                f"{len(errors)} storytelling config violation(s) found:\n  - " + "\n  - ".join(errors)
            )

    # -- read-only accessors ---------------------------------------------------

    def model_override(self) -> str | None:
        return self._raw["llm"]["model"]

    def temperature(self) -> float:
        return float(self._raw["llm"]["temperature"])

    def max_tokens_planner(self) -> int:
        return int(self._raw["llm"]["max_tokens_planner"])

    def max_tokens_generator(self) -> int:
        return int(self._raw["llm"]["max_tokens_generator"])

    def max_generation_retries(self) -> int:
        return int(self._raw["generation"]["max_generation_retries"])

    def prompt_version(self) -> str:
        return self._raw["generation"]["prompt_version"]

    def numeric_tolerance(self) -> float:
        return float(self._raw["verification"]["numeric_tolerance"])

    def numeric_absolute_floor(self) -> float:
        return float(self._raw["verification"]["numeric_absolute_floor"])

    def minimum_magnitude(self) -> float:
        return float(self._raw["verification"]["minimum_magnitude"])

    def allow_deterministic_fallback(self) -> bool:
        return bool(self._raw["fallback"]["allow_deterministic_fallback"])

    def to_dict(self) -> dict[str, Any]:
        return dict(self._raw)
