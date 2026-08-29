"""Step 5 plumbing: agents/llm_client.py's Groq retry/backoff policy and the
run_tool_loop recovery path for a model-proposed-disallowed-tool rejection.

Covers two related fixes made in the same session:
  1. GroqLLMClient.create() no longer blindly sleeps 1.5s before every key
     rotation, and distinguishes retryable (rate-limit/capacity/transient)
     Groq errors from non-retryable (malformed request) ones instead of
     burning the whole key pool on a request that will fail identically on
     every key.
  2. run_tool_loop recovers from Groq's "model proposed a tool outside the
     `tools` list it was sent" 400 (previously a hard LLMUnavailable that
     discarded the whole agent round) by feeding the rejection back to the
     model as a correctable mistake, the same way a governed
     tools/gateway.call_tool() DENIAL already is.

No real network calls: constructs real `groq` exception instances (against
a real httpx.Request/Response so their shape matches production) and a
minimal fake HTTP client to drive GroqLLMClient.create() without touching
the network, plus FakeLLMClient/a tiny scripted stand-in for the
run_tool_loop-level test.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "tests"))

import groq  # noqa: E402

from _llm_test_helpers import tool_call_response  # noqa: E402
from agents import hypothesis_agent  # noqa: E402
from agents.llm_client import (  # noqa: E402
    GroqKeyPool, GroqLLMClient, LLMUnavailable, ToolCallRejected, _as_tool_call_rejection,
)
from agents.models import InvestigationState, RequesterRole  # noqa: E402


def _status_error(status_code: int, body: dict) -> groq.APIStatusError:
    request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
    response = httpx.Response(status_code=status_code, request=request, json=body)
    cls = {401: groq.AuthenticationError, 403: groq.PermissionDeniedError, 404: groq.NotFoundError,
           429: groq.RateLimitError, 400: groq.BadRequestError}.get(status_code, groq.APIStatusError)
    return cls(message=str(body), response=response, body=body)


_TOOL_USE_FAILED_BODY = {
    "error": {
        "message": "Tool call validation failed: attempted to call tool 'get_evidence' "
                   "which was not in request.tools",
        "type": "invalid_request_error", "code": "tool_use_failed",
        "failed_generation": '{"name": "get_evidence", "arguments": {"evidence_ids": ["ev_1"]}}',
    }
}


# ---------------------------------------------------------------------------
# _as_tool_call_rejection -- pure parsing, no network
# ---------------------------------------------------------------------------

def test_tool_use_failed_body_is_recognized_and_parsed():
    exc = _status_error(400, _TOOL_USE_FAILED_BODY)
    rejected = _as_tool_call_rejection(exc)
    assert isinstance(rejected, ToolCallRejected)
    assert rejected.tool_name == "get_evidence"


def test_unrelated_400_is_not_mistaken_for_a_tool_rejection():
    exc = _status_error(400, {"error": {"message": "missing required field 'model'",
                                         "type": "invalid_request_error", "code": "invalid_request"}})
    assert _as_tool_call_rejection(exc) is None


def test_non_dict_body_is_handled_without_raising():
    exc = _status_error(400, {})
    assert _as_tool_call_rejection(exc) is None


# ---------------------------------------------------------------------------
# GroqLLMClient.create() -- retry/fail-fast policy, no real network
# ---------------------------------------------------------------------------

class _ScriptedGroqClient:
    """Stand-in for a per-key `groq.Groq(...)` client: .chat.completions.create()
    replays one entry off a queue (raise the exception, or return the value)."""
    def __init__(self, outcomes: list):
        self._outcomes = outcomes
        self.calls = 0

        class _Completions:
            def create(_self, **kwargs):
                self.calls += 1
                outcome = self._outcomes.pop(0)
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


def _patched_client(monkeypatch, per_key_outcomes: dict):
    """per_key_outcomes: {key: [outcome, outcome, ...]} -- next_key() cycles
    through per_key_outcomes' keys in order, and each key's own client pops
    its own queue, so callers can assert exactly which key handled which
    attempt."""
    pool = GroqKeyPool(list(per_key_outcomes.keys()))
    client = GroqLLMClient(key_pool=pool)
    fakes = {key: _ScriptedGroqClient(outcomes) for key, outcomes in per_key_outcomes.items()}
    monkeypatch.setattr(client, "_client_for", lambda key: fakes[key])
    return client, fakes


def test_rate_limited_key_rotates_to_next_key_and_succeeds(monkeypatch):
    ok_response = tool_call_response("c1", "submit_hypotheses", {"hypotheses": []})
    # GroqLLMClient.create() expects the raw provider response shape (an
    # object with .choices[0].message / .usage / .model), not our own
    # normalized LLMResponse -- build a minimal stand-in.
    class _Msg:
        content = None
        tool_calls = []

    class _Choice:
        message = _Msg()
        finish_reason = "stop"

    class _Usage:
        prompt_tokens = 10
        completion_tokens = 5

    class _Raw:
        choices = [_Choice()]
        usage = _Usage()
        model = "openai/gpt-oss-20b"

    client, fakes = _patched_client(monkeypatch, {
        "key-a": [_status_error(429, {"error": {"message": "rate limited"}})],
        "key-b": [_Raw()],
    })
    result = client.create(system="sys", messages=[], tools=[])
    assert result.model == "openai/gpt-oss-20b"
    assert fakes["key-a"].calls == 1 and fakes["key-b"].calls == 1


def test_non_retryable_status_fails_fast_without_exhausting_the_pool(monkeypatch):
    unrelated_400 = _status_error(400, {"error": {"message": "bad schema", "code": "invalid_request"}})
    client, fakes = _patched_client(monkeypatch, {
        "key-a": [unrelated_400],
        "key-b": [unrelated_400],   # never reached -- assert below
    })
    with pytest.raises(LLMUnavailable):
        client.create(system="sys", messages=[], tools=[])
    assert fakes["key-a"].calls == 1
    assert fakes["key-b"].calls == 0   # fail-fast: didn't burn the rest of the pool


def test_tool_use_failed_status_raises_tool_call_rejected_not_llm_unavailable(monkeypatch):
    client, fakes = _patched_client(monkeypatch, {"key-a": [_status_error(400, _TOOL_USE_FAILED_BODY)]})
    with pytest.raises(ToolCallRejected) as excinfo:
        client.create(system="sys", messages=[], tools=[])
    assert excinfo.value.tool_name == "get_evidence"
    assert fakes["key-a"].calls == 1   # also fails fast -- it's a request-shape problem, not a key problem


# ---------------------------------------------------------------------------
# run_tool_loop recovery -- the model proposes a disallowed tool, gets
# corrected, and still produces a usable result within its own iterations.
# ---------------------------------------------------------------------------

class _RejectThenSucceedClient:
    """A minimal LLMClient: raises ToolCallRejected on its first .create()
    call (simulating the model reaching for get_evidence), then delegates
    every subsequent call to a wrapped, normally-scripted FakeLLMClient."""
    def __init__(self, fake):
        self._fake = fake
        self.calls = 0

    def build_user_message(self, text):
        return self._fake.build_user_message(text)

    def build_tool_result_messages(self, results):
        return self._fake.build_tool_result_messages(results)

    def create(self, *, system, messages, tools, max_tokens=4096):
        self.calls += 1
        if self.calls == 1:
            raise ToolCallRejected("get_evidence", '{"name": "get_evidence", "arguments": {}}')
        return self._fake.create(system=system, messages=messages, tools=tools, max_tokens=max_tokens)


_H_VOLUME = {"driver": "volume", "dimension": "orders", "mechanism": "order-count expansion",
             "statement": "Revenue growth may be associated with an increase in order volume.",
             "expected_evidence": ["DRIVER_CONTRIBUTION:volume"], "falsification_evidence": []}


def test_disallowed_tool_rejection_is_recovered_not_a_dead_end(agent_ctx):
    from agents.llm_client import FakeLLMClient
    state = InvestigationState(investigation_id="rej1", requester_role=RequesterRole.ANALYST,
                                kpi_id="revenue", period="2017-11")
    state.movement = {"absolute": 346051.94, "percentage": 52.1}

    inner = FakeLLMClient([tool_call_response("c1", "submit_hypotheses", {"hypotheses": [_H_VOLUME]})])
    client = _RejectThenSucceedClient(inner)

    hypothesis_agent.generate_hypotheses(state, client, agent_ctx)

    # The round wasn't discarded: the model's second attempt still produced
    # a real hypothesis, despite the first attempt being rejected.
    assert len(state.hypotheses) == 1
    assert client.calls == 2   # one rejected attempt, one successful retry
    assert any(e["type"] == "tool_call_rejected" and e["tool_name"] == "get_evidence"
               for e in state.security_events)
    # The rejection consumed an agent_calls unit (it was a real round-trip
    # attempt), same as any other agent call.
    assert state.budgets.used_agent_calls == 2
