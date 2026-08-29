"""
store.py — the one explicit, local investigation store this prototype uses.
No database anywhere in this repo (confirmed across Steps 1-9: Parquet for
canonical data, YAML config, one-shot JSON reports, feedback's own
append-only JSONL). This mirrors that precedent: an in-memory dict, mirrored
to one JSON file per investigation under causa/data/investigations/
(gitignored, regenerable) so a server restart doesn't lose an in-progress
demo. Investigation records are NOT append-only history like Step 9's
feedback store -- each investigation's derived Step 6/7/8 results are cached
in place, which is fine because an investigation's own InvestigationState is
never mutated after the orchestrator returns it.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
INVESTIGATIONS_DIR = REPO_ROOT / "data" / "investigations"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class InvestigationRecord:
    investigation_id: str
    requester_role: str
    kpi_id: str
    period_current: str
    period_previous: str
    source: str                       # "replay" | "fake_llm" | "live_llm"
    state: Any                        # agents.models.InvestigationState
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    # Lazily-computed, cached derived results (§2c of the plan) --
    # hypothesis_id / persona -> serialized dict (never re-derived once cached).
    causal_results: dict[str, dict] = field(default_factory=dict)
    decision_result: Optional[dict] = None
    story: dict[str, dict] = field(default_factory=dict)

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id, "requester_role": self.requester_role,
            "kpi_id": self.kpi_id, "period_current": self.period_current, "period_previous": self.period_previous,
            "source": self.source, "status": self.state.status.value, "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class InvestigationStore:
    def __init__(self, directory: Path = INVESTIGATIONS_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, InvestigationRecord] = {}
        self._lock = threading.Lock()

    def create(self, record: InvestigationRecord) -> InvestigationRecord:
        with self._lock:
            self._records[record.investigation_id] = record
            self._persist(record)
        return record

    def get(self, investigation_id: str) -> Optional[InvestigationRecord]:
        return self._records.get(investigation_id)

    def list(self, role_filter: Optional[str] = None) -> list[InvestigationRecord]:
        records = list(self._records.values())
        if role_filter:
            records = [r for r in records if r.requester_role == role_filter]
        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def latest_for_role(self, role: str) -> Optional[InvestigationRecord]:
        matches = self.list(role_filter=role)
        return matches[0] if matches else None

    def update_causal(self, investigation_id: str, hypothesis_id: str, result_dict: dict) -> None:
        with self._lock:
            record = self._records[investigation_id]
            record.causal_results[hypothesis_id] = result_dict
            record.updated_at = _now_iso()
            self._persist(record)

    def update_decision(self, investigation_id: str, result_dict: dict) -> None:
        with self._lock:
            record = self._records[investigation_id]
            record.decision_result = result_dict
            record.updated_at = _now_iso()
            self._persist(record)

    def update_story(self, investigation_id: str, persona: str, story_dict: dict) -> None:
        with self._lock:
            record = self._records[investigation_id]
            record.story[persona] = story_dict
            record.updated_at = _now_iso()
            self._persist(record)

    def _persist(self, record: InvestigationRecord) -> None:
        path = self.directory / f"{record.investigation_id}.json"
        payload = {
            "investigation_id": record.investigation_id, "requester_role": record.requester_role,
            "kpi_id": record.kpi_id, "period_current": record.period_current,
            "period_previous": record.period_previous, "source": record.source,
            "created_at": record.created_at, "updated_at": record.updated_at,
            "state": record.state.to_dict(), "causal_results": record.causal_results,
            "decision_result": record.decision_result, "story": record.story,
        }
        path.write_text(json.dumps(payload, indent=2, default=str))


_store: Optional[InvestigationStore] = None


def get_store() -> InvestigationStore:
    global _store
    if _store is None:
        _store = InvestigationStore()
    return _store
