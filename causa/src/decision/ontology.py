"""
ontology.py — Step 7: loaders for the two Decision & Action Intelligence
Engine config files.

Structurally identical to kpi/semantic_registry.py::SemanticRegistry: load,
validate, expose read-only accessors. Neither class here computes a single
business number -- config/decision_ontology.yaml defines what actions are
POSSIBLE, config/decision_scoring.yaml defines the WEIGHTS/TIERS/THRESHOLDS
later modules use to score them; the scores themselves are computed in
impact_estimator.py / confidence_engine.py / scoring.py, never here.

No LLM import anywhere in this file (task's own non-negotiable: business
logic and configuration stay outside prompts). Verified by
tests/test_decision_provenance.py's AST scan.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
ONTOLOGY_CONFIG_PATH = REPO_ROOT / "config" / "decision_ontology.yaml"
ONTOLOGY_SCHEMA_PATH = REPO_ROOT / "schemas" / "decision_ontology.schema.json"
SCORING_CONFIG_PATH = REPO_ROOT / "config" / "decision_scoring.yaml"

_VALID_TIERS = ("LOW", "MEDIUM", "HIGH")
_VALID_LINK_STRENGTHS = ("WEAK", "MODERATE", "STRONG")


class DecisionConfigError(Exception):
    """Raised when a decision config file fails validation. Never raised for
    a scoring/calculation error -- neither class in this module calculates
    anything."""


class DecisionOntology:
    def __init__(self, drivers: list[dict[str, Any]], schema: dict[str, Any], raw_config: dict[str, Any]):
        self._drivers: dict[str, dict[str, Any]] = {d["driver"]: d for d in drivers}
        self._schema = schema
        self._raw_config = raw_config

    # -- loading -------------------------------------------------------------

    @classmethod
    def load(cls, config_path: Path = ONTOLOGY_CONFIG_PATH, schema_path: Path = ONTOLOGY_SCHEMA_PATH) -> "DecisionOntology":
        with open(schema_path) as f:
            schema = json.load(f)
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        drivers = raw_config.get("drivers", [])
        return cls(drivers=drivers, schema=schema, raw_config=raw_config)

    # -- validation ------------------------------------------------------------

    def validate(self) -> None:
        """Schema validation plus the cross-contract invariants a JSON Schema
        alone cannot express: every action_id is globally unique, and every
        tier/link-strength value used is one this ontology's own vocabulary
        declares. Raises DecisionConfigError with every violation found, not
        just the first."""
        errors: list[str] = []

        if not self._drivers:
            raise DecisionConfigError("No drivers loaded from config/decision_ontology.yaml -- ontology is empty.")

        try:
            jsonschema.validate(instance=self._raw_config, schema=self._schema)
        except jsonschema.ValidationError as e:
            errors.append(f"schema violation: {e.message} (path: {list(e.absolute_path)})")

        seen_action_ids: set[str] = set()
        for driver_entry in self._drivers.values():
            driver = driver_entry.get("driver", "<missing driver>")
            for lever in driver_entry.get("controllable_levers", []):
                for action_type in lever.get("action_types", []):
                    action_id = action_type.get("action_id", "<missing action_id>")
                    if action_id in seen_action_ids:
                        errors.append(f"[{driver}] duplicate action_id across ontology: {action_id!r}")
                    seen_action_ids.add(action_id)
                    if action_type.get("effort_tier") not in _VALID_TIERS:
                        errors.append(f"[{driver}/{action_id}] effort_tier must be one of {_VALID_TIERS}")
                    if action_type.get("controllability_tier") not in _VALID_TIERS:
                        errors.append(f"[{driver}/{action_id}] controllability_tier must be one of {_VALID_TIERS}")
                    if action_type.get("action_link_strength") not in _VALID_LINK_STRENGTHS:
                        errors.append(f"[{driver}/{action_id}] action_link_strength must be one of {_VALID_LINK_STRENGTHS}")

        if errors:
            raise DecisionConfigError(
                f"{len(errors)} decision ontology violation(s) found:\n  - " + "\n  - ".join(errors)
            )

    # -- read-only accessors ---------------------------------------------------

    def list_drivers(self) -> list[str]:
        return list(self._drivers.keys())

    def is_supported(self, driver: str) -> bool:
        return self.get_driver(driver) is not None

    def get_driver(self, driver: str) -> Optional[dict[str, Any]]:
        """None (never KeyError) for an unsupported driver -- "unsupported
        driver" is a first-class, expected outcome this ontology's own
        unsupported_driver_policy governs, not an error condition. Also
        checks each driver's declared aliases, so a caller naming a driver
        by its common synonym still resolves."""
        if driver in self._drivers:
            return self._drivers[driver]
        for entry in self._drivers.values():
            if driver in entry.get("aliases", []):
                return entry
        return None

    def levers_for(self, driver: str) -> list[dict[str, Any]]:
        entry = self.get_driver(driver)
        return list(entry.get("controllable_levers", [])) if entry else []

    def action_types_for(self, driver: str, lever: Optional[str] = None) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for lever_entry in self.levers_for(driver):
            if lever is not None and lever_entry.get("lever") != lever:
                continue
            for action_type in lever_entry.get("action_types", []):
                out.append({**action_type, "_lever": lever_entry.get("lever")})
        return out

    def unsupported_driver_policy(self) -> str:
        return self._raw_config.get("unsupported_driver_policy", "abstain")

    def to_dict(self) -> dict[str, Any]:
        return {"version": self._raw_config.get("version"), "drivers": list(self._drivers.values())}


class DecisionScoringConfig:
    def __init__(self, raw_config: dict[str, Any]):
        self._raw = raw_config

    @classmethod
    def load(cls, config_path: Path = SCORING_CONFIG_PATH) -> "DecisionScoringConfig":
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        instance = cls(raw_config)
        instance.validate()
        return instance

    def validate(self) -> None:
        errors: list[str] = []

        weights = self._raw.get("confidence_weights", {})
        expected_keys = {"driver_confidence", "data_quality", "historical_support", "action_link_strength"}
        if set(weights) != expected_keys:
            errors.append(f"confidence_weights must declare exactly {sorted(expected_keys)}, got {sorted(weights)}")
        total = sum(weights.values()) if weights else 0.0
        if weights and abs(total - 1.0) > 1e-6:
            errors.append(f"confidence_weights must sum to 1.0, got {total}")

        for tier_table_name in ("effort_tier_scores", "controllability_tier_scores"):
            table = self._raw.get(tier_table_name, {})
            if set(table) != set(_VALID_TIERS):
                errors.append(f"{tier_table_name} must declare exactly {list(_VALID_TIERS)}, got {sorted(table)}")
            values = [table[t] for t in _VALID_TIERS if t in table]
            if values != sorted(values):
                errors.append(f"{tier_table_name} must be monotonically increasing LOW < MEDIUM < HIGH, got {table}")

        link_table = self._raw.get("action_link_strength_scores", {})
        if set(link_table) != set(_VALID_LINK_STRENGTHS):
            errors.append(f"action_link_strength_scores must declare exactly {list(_VALID_LINK_STRENGTHS)}, got {sorted(link_table)}")

        floor = self._raw.get("prioritization", {}).get("divide_by_zero_floor")
        if not isinstance(floor, (int, float)) or floor <= 0:
            errors.append("prioritization.divide_by_zero_floor must be a positive number")

        if errors:
            raise DecisionConfigError(
                f"{len(errors)} decision scoring config violation(s) found:\n  - " + "\n  - ".join(errors)
            )

    # -- read-only accessors ---------------------------------------------------

    @property
    def confidence_weights(self) -> dict[str, float]:
        return dict(self._raw["confidence_weights"])

    @property
    def action_link_strength_scores(self) -> dict[str, float]:
        return dict(self._raw["action_link_strength_scores"])

    @property
    def effort_tier_scores(self) -> dict[str, float]:
        return dict(self._raw["effort_tier_scores"])

    @property
    def controllability_tier_scores(self) -> dict[str, float]:
        return dict(self._raw["controllability_tier_scores"])

    @property
    def data_quality_scores(self) -> dict[str, float]:
        return dict(self._raw["data_quality_scores"])

    def prioritization_formula(self) -> str:
        return self._raw["prioritization"]["formula"]

    def divide_by_zero_floor(self) -> float:
        return float(self._raw["prioritization"]["divide_by_zero_floor"])

    @property
    def constraint_thresholds(self) -> dict[str, Any]:
        return dict(self._raw.get("constraint_thresholds", {}))

    def default_monitoring_window(self) -> str:
        return self._raw.get("default_monitoring_window", "8_weeks")

    def to_dict(self) -> dict[str, Any]:
        return dict(self._raw)
