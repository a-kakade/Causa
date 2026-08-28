"""
store.py — Step 9: append-only, file-backed persistence for feedback records.

This repository has no database anywhere (confirmed across Steps 1-8:
Parquet for canonical data, YAML for governed config, plain dataclasses
in-memory for Step 7/8 runtime objects -- see kpi/cache.py for the closest
existing precedent, itself in-memory only). Step 9 is the first step that
genuinely needs durable persistence (feedback history must survive past a
single process run), so this module introduces one: JSON-Lines files under
a data directory, one file per record type, written with open(..., "a")
ONLY -- never rewritten, never truncated, never edited in place.

"Never delete or mutate historical feedback as part of normal operation"
(spec section 10) is enforced structurally here, not just by convention:
FeedbackStore has no method that opens a file in "w" mode after its first
line, and status changes are themselves stored as new, appended event
records (append_feedback_status_event / append_case_status_event) rather
than as in-place field updates -- current status is always computed by
folding the event log, so the full history is preserved on disk even though
callers see one current Feedback/EvaluationCase.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from feedback.models import (
    BusinessContext,
    ConflictRecord,
    Correction,
    EvaluationCase,
    Feedback,
    FeedbackStatus,
    RegressionTest,
    ReviewStatus,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FEEDBACK_DIR = REPO_ROOT / "data" / "feedback"


class FeedbackStore:
    """One JSONL file per record type under `directory`. Every write is an
    append; every read materializes the full current file. Safe to
    construct repeatedly against the same directory (e.g. once per demo
    stage) -- files are created lazily on first write."""

    def __init__(self, directory: Path = DEFAULT_FEEDBACK_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    # -- generic append/read helpers ---------------------------------------

    def _path(self, name: str) -> Path:
        return self.directory / f"{name}.jsonl"

    def _append(self, name: str, record: dict) -> None:
        with open(self._path(name), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _read_all(self, name: str) -> list[dict]:
        path = self._path(name)
        if not path.exists():
            return []
        records = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    # -- Feedback -----------------------------------------------------------

    def save_feedback(self, feedback: Feedback) -> Feedback:
        self._append("feedback", feedback.to_dict())
        return feedback

    def get_feedback(self, feedback_id: str) -> Optional[Feedback]:
        for record in self.list_feedback():
            if record.feedback_id == feedback_id:
                return record
        return None

    def list_feedback(self, **filters) -> list[Feedback]:
        """Reconstructs the CURRENT Feedback for every feedback_id ever
        appended, by folding: the base record plus any later status-event
        records with the same feedback_id. filters (e.g. status=...,
        review_status=..., story_id=...) are applied to the folded result."""
        base_by_id: dict[str, dict] = {}
        for raw in self._read_all("feedback"):
            base_by_id[raw["feedback_id"]] = dict(raw)
        for event in self._read_all("feedback_status_events"):
            fid = event["feedback_id"]
            if fid in base_by_id:
                if "status" in event:
                    base_by_id[fid]["status"] = event["status"]
                if "review_status" in event:
                    base_by_id[fid]["review_status"] = event["review_status"]

        results = [Feedback.from_dict(d) for d in base_by_id.values()]
        for key, value in filters.items():
            results = [r for r in results if getattr(r, key) == value]
        return results

    def append_feedback_status_event(
        self, feedback_id: str, status: Optional[FeedbackStatus] = None,
        review_status: Optional[ReviewStatus] = None, reviewer: Optional[str] = None,
        rationale: Optional[str] = None, created_at: str = "",
    ) -> None:
        """The only way FeedbackStore changes a Feedback's status -- appends
        a new event, never edits the original feedback.jsonl line."""
        event = {"feedback_id": feedback_id, "reviewer": reviewer, "rationale": rationale, "created_at": created_at}
        if status is not None:
            event["status"] = status.value
        if review_status is not None:
            event["review_status"] = review_status.value
        self._append("feedback_status_events", event)

    # -- Correction -----------------------------------------------------------

    def save_correction(self, correction: Correction) -> Correction:
        self._append("corrections", correction.to_dict())
        return correction

    def list_corrections(self, **filters) -> list[Correction]:
        results = [Correction.from_dict(d) for d in self._read_all("corrections")]
        for key, value in filters.items():
            results = [r for r in results if getattr(r, key) == value]
        return results

    def get_correction_for_feedback(self, feedback_id: str) -> Optional[Correction]:
        matches = self.list_corrections(feedback_id=feedback_id)
        return matches[-1] if matches else None

    # -- BusinessContext --------------------------------------------------

    def save_business_context(self, context: BusinessContext) -> BusinessContext:
        self._append("business_context", context.to_dict())
        return context

    def list_business_context(self, **filters) -> list[BusinessContext]:
        results = [BusinessContext.from_dict(d) for d in self._read_all("business_context")]
        for key, value in filters.items():
            results = [r for r in results if getattr(r, key) == value]
        return results

    # -- EvaluationCase -----------------------------------------------------

    def save_evaluation_case(self, case: EvaluationCase) -> EvaluationCase:
        self._append("evaluation_cases", case.to_dict())
        return case

    def list_evaluation_cases(self, **filters) -> list[EvaluationCase]:
        base_by_id: dict[str, dict] = {}
        for raw in self._read_all("evaluation_cases"):
            base_by_id[raw["case_id"]] = dict(raw)
        for event in self._read_all("evaluation_case_status_events"):
            cid = event["case_id"]
            if cid in base_by_id and "status" in event:
                base_by_id[cid]["status"] = event["status"]

        results = [EvaluationCase.from_dict(d) for d in base_by_id.values()]
        for key, value in filters.items():
            results = [r for r in results if getattr(r, key) == value]
        return results

    def append_case_status_event(self, case_id: str, status: ReviewStatus, reviewer: Optional[str] = None,
                                  created_at: str = "") -> None:
        self._append("evaluation_case_status_events", {
            "case_id": case_id, "status": status.value, "reviewer": reviewer, "created_at": created_at,
        })

    def list_dataset_versions(self) -> list[str]:
        versions = sorted({c.dataset_version for c in self.list_evaluation_cases()})
        return versions

    # -- RegressionTest -----------------------------------------------------

    def save_regression_test(self, test: RegressionTest) -> RegressionTest:
        self._append("regression_tests", test.to_dict())
        return test

    def list_regression_tests(self, **filters) -> list[RegressionTest]:
        results = [RegressionTest.from_dict(d) for d in self._read_all("regression_tests")]
        for key, value in filters.items():
            results = [r for r in results if getattr(r, key) == value]
        return results

    # -- ConflictRecord -------------------------------------------------------

    def save_conflict(self, conflict: ConflictRecord) -> ConflictRecord:
        self._append("conflicts", conflict.to_dict())
        return conflict

    def list_conflicts(self, **filters) -> list[ConflictRecord]:
        results = [ConflictRecord.from_dict(d) for d in self._read_all("conflicts")]
        for key, value in filters.items():
            results = [r for r in results if getattr(r, key) == value]
        return results
