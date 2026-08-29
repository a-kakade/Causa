"""
serializers.py — the only place a dataclass/Pydantic object built by src/ is
turned into a JSON-safe dict. Every function here either calls the object's
own .to_dict()/.model_dump() (never hand-picks a subset that could drift from
the real object) or, for the few objects whose to_dict() intentionally
excludes something the API additionally needs (e.g. security-sensitive
evidence redaction), documents exactly why.
"""

from __future__ import annotations

from typing import Any


def evidence_object_dict(obj: Any) -> dict:
    return obj.model_dump(mode="json")


def evidence_result_dict(obj: Any) -> dict:
    return obj.model_dump(mode="json")


def kpi_result_dict(obj: Any) -> dict:
    return obj.to_dict()


def comparison_result_dict(obj: Any) -> dict:
    return obj.to_dict()


def anomaly_result_dict(obj: Any) -> dict:
    return obj.to_dict()


def driver_decomposition_dict(obj: Any) -> dict:
    return obj.to_dict()


def investigation_state_dict(obj: Any) -> dict:
    return obj.to_dict()


def causal_result_dict(obj: Any) -> dict:
    return obj.to_dict()


def decision_result_dict(obj: Any) -> dict:
    return obj.to_dict()


def kpi_story_dict(obj: Any) -> dict:
    return obj.to_dict()


def feedback_dict(obj: Any) -> dict:
    return obj.to_dict()


# strict allowlist -- never forward raw LLM prompt/response content even if
# a future field is added to AuditTraceEntry/TelemetryRecord upstream.
_AUDIT_FIELDS = (
    "agent_id", "agent_role", "timestamp", "input_state_hash", "tool_call", "tool_arguments_hash",
    "tool_result_ids", "output", "token_usage", "latency_ms", "security_decision",
)


def audit_entry_dict(obj: Any) -> dict:
    d = obj.to_dict()
    return {k: d.get(k) for k in _AUDIT_FIELDS}


_TELEMETRY_FIELDS = (
    "agent_role", "model", "input_tokens", "output_tokens", "total_tokens", "estimated_cost",
    "tool_calls", "retrieval_calls", "agent_latency_ms", "total_latency_ms",
)


def telemetry_record_dict(obj: Any) -> dict:
    d = obj.to_dict()
    return {k: d.get(k) for k in _TELEMETRY_FIELDS}
