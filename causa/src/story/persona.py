"""
persona.py — Step 8: loader + selection engine for config/personas.yaml.

Structurally identical in loading posture to kpi/semantic_registry.py::
SemanticRegistry / decision/ontology.py::DecisionOntology: load, validate,
expose read-only accessors. select_and_order() is the one function whose
output differs per persona and drives every downstream selection/ordering
decision -- deterministic, no LLM involved anywhere in this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from story.models import EvidenceItem, EvidencePackage, Persona

REPO_ROOT = Path(__file__).resolve().parents[2]
PERSONAS_CONFIG_PATH = REPO_ROOT / "config" / "personas.yaml"

_REQUIRED_PERSONAS = {"executive", "finance", "operations", "marketing"}
_VALID_DETAIL_LEVELS = ("LOW", "MEDIUM", "HIGH")


class PersonaConfigError(Exception):
    """Raised when config/personas.yaml fails validation. Never raised for
    a selection/ordering error -- validate() performs no selection."""


class PersonaEngine:
    def __init__(self, personas: dict[str, dict[str, Any]], raw_config: dict[str, Any]):
        self._personas = personas
        self._raw_config = raw_config

    @classmethod
    def load(cls, config_path: Path = PERSONAS_CONFIG_PATH) -> "PersonaEngine":
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        personas = raw_config.get("personas", {})
        return cls(personas=personas, raw_config=raw_config)

    def validate(self) -> None:
        errors: list[str] = []

        missing = _REQUIRED_PERSONAS - set(self._personas)
        if missing:
            errors.append(f"missing required persona(s): {sorted(missing)}")

        for name, entry in self._personas.items():
            if not entry.get("focus_areas"):
                errors.append(f"[{name}] focus_areas must be non-empty")
            if not entry.get("preferred_metrics"):
                errors.append(f"[{name}] preferred_metrics must be non-empty")
            if entry.get("detail_level") not in _VALID_DETAIL_LEVELS:
                errors.append(f"[{name}] detail_level must be one of {_VALID_DETAIL_LEVELS}")
            if not isinstance(entry.get("max_statements_per_section"), int) or entry.get("max_statements_per_section") <= 0:
                errors.append(f"[{name}] max_statements_per_section must be a positive integer")
            if not entry.get("section_order"):
                errors.append(f"[{name}] section_order must be non-empty")

        if errors:
            raise PersonaConfigError(
                f"{len(errors)} persona config violation(s) found:\n  - " + "\n  - ".join(errors)
            )

    # -- read-only accessors ---------------------------------------------------

    def list_personas(self) -> list[str]:
        return list(self._personas.keys())

    def get(self, persona: Persona) -> dict[str, Any]:
        key = persona.value.lower()
        if key not in self._personas:
            raise KeyError(f"Unknown persona {persona!r}. Known: {self.list_personas()}")
        return self._personas[key]

    # -- selection/ordering (the one function that differs per persona) --------

    def select_and_order(self, persona: Persona, package: EvidencePackage) -> list[EvidenceItem]:
        """Filters OUT excluded_evidence_types (a hard block), then sorts the
        remaining items:
          1. metric in preferred_metrics first (stable)
          2. evidence_type in preferred_evidence_types first (stable)
          3. original package order (stable sort preserves this as the tie-break)
        Deterministic, no LLM. This is the function tests/test_persona_engine.py
        asserts differing orderings against for each of the 4 personas."""
        config = self.get(persona)
        excluded = set(config.get("excluded_evidence_types", []))
        preferred_metrics = list(config.get("preferred_metrics", []))
        preferred_evidence_types = list(config.get("preferred_evidence_types", []))

        eligible = [item for item in package.items if item.evidence_type not in excluded]

        def _sort_key(item: EvidenceItem) -> tuple[int, int]:
            metric_rank = 0 if item.metric in preferred_metrics else 1
            type_rank = 0 if item.evidence_type in preferred_evidence_types else 1
            return (metric_rank, type_rank)

        # Python's sort is stable -- items with equal _sort_key retain their
        # original package.items relative order (tie-break #3 above).
        return sorted(eligible, key=_sort_key)

    def to_dict(self) -> dict[str, Any]:
        return {"version": self._raw_config.get("version"), "personas": dict(self._personas)}
