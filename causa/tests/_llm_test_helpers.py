"""Shared test-only helpers for scripting agents.llm_client.FakeLLMClient
responses across the Step 5 LLM-backed-agent test files. Not one of the 12
required test files -- an internal utility module, same role as
tests/conftest.py's fixtures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.llm_client import LLMResponse  # noqa: E402


def tool_call_response(call_id: str, name: str, arguments: dict, input_tokens: int = 100,
                        output_tokens: int = 50) -> LLMResponse:
    return LLMResponse(
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": arguments}],
        stop_reason="tool_use", input_tokens=input_tokens, output_tokens=output_tokens,
        model="llama-3.3-70b-versatile",
        raw_message={"role": "assistant", "content": None,
                     "tool_calls": [{"id": call_id, "type": "function",
                                     "function": {"name": name, "arguments": json.dumps(arguments)}}]},
    )


def text_only_response(text: str, input_tokens: int = 50, output_tokens: int = 20) -> LLMResponse:
    return LLMResponse(
        content=[{"type": "text", "text": text}], stop_reason="end_turn", input_tokens=input_tokens,
        output_tokens=output_tokens, model="llama-3.3-70b-versatile",
        raw_message={"role": "assistant", "content": text},
    )


class ScriptedRoutingClient:
    """Routes .create() calls to per-agent scripts based on a marker string
    that appears in that agent's system prompt (agents/prompts.py's system
    prompts each name their own role, e.g. "Hypothesis Agent"). Each script
    is a callable(messages) -> LLMResponse, exactly like FakeLLMClient's
    callable form -- this class exists only to let one investigation run
    exercise three DIFFERENT scripts (one per LLM-backed agent) without the
    Orchestrator needing to know anything about which script is active."""

    def __init__(self, scripts_by_marker: dict):
        self._scripts = scripts_by_marker
        self.calls = []

    def build_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def build_tool_result_messages(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": i, "content": c} for i, c in results]

    def create(self, *, system: str, messages: list, tools: list, max_tokens: int = 4096) -> LLMResponse:
        self.calls.append({"system": system, "messages": list(messages)})
        for marker, script in self._scripts.items():
            if marker in system:
                return script(messages)
        raise RuntimeError(f"No script registered for system prompt containing any of {list(self._scripts)}")


def last_tool_result_content(messages: list) -> str:
    """Returns the content string of the most recent {"role": "tool", ...}
    message, or "" if the last message isn't one -- used by test scripts
    that need to react to what a real tool call actually returned."""
    last = messages[-1]
    return last.get("content", "") if last.get("role") == "tool" else ""


def extract_evidence_ids(tool_result_content: str) -> list:
    """Pulls every evidence_id-shaped string (this repo's "ev_..." or
    "ev_evresult_..." content-hash convention) out of a tool_result JSON
    string, without needing to know that result's exact schema."""
    import re
    return re.findall(r'"(ev_[a-zA-Z0-9_]+)"', tool_result_content)
