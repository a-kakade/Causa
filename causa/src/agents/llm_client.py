"""
llm_client.py — Step 5: the LLM provider seam (Groq) + the shared manual
tool-use loop every LLM-backed agent (Hypothesis, Evidence, Counter-Evidence)
runs through.

Not one of the file names literally listed in the task spec, but a necessary
plumbing module for the same reason tools/context.py is: the provider
integration and the agentic loop are identical across all 3 LLM-backed
agents, so they live once here rather than being copy-pasted three times.

Provider: Groq (the user's explicit choice, for cost -- see
docs/MULTI_AGENT_ARCHITECTURE.md §0). The `LLMClient` protocol is
provider-agnostic by design (only `.create()` + two small message-shape
helpers) so swapping providers later is a new class here, not a rewrite of
run_tool_loop or any agent module.

Every tool call an LLM proposes is routed through tools/gateway.call_tool()
-- this module NEVER calls a governed tool function directly. This is what
makes "the LLM decided to request X" and "X actually happened" two separate,
independently-enforced things (task §2/§4).
"""

from __future__ import annotations

import itertools
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from agents.models import AgentRole, InvestigationState, now_iso
from agents.telemetry import record_llm_call
from tools import gateway
from tools.context import ToolContext
from tools.schemas import ToolDefinition

REPO_ROOT = Path(__file__).resolve().parents[2]
# "llama-3.3-70b-versatile" (Groq's own SDK-advertised default at the time
# this was written) turned out to be unavailable/decommissioned for the
# user's supplied keys when actually probed against the live API --
# "openai/gpt-oss-20b" was verified live (see STEP5_VALIDATION.md §14/§17)
# to work with real tool-calling on these keys. Overridable via GROQ_MODEL
# without touching code, precisely because this catalog moves fast.
DEFAULT_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")


# ---------------------------------------------------------------------------
# .env loader — dependency-free (no python-dotenv), matches this repo's
# minimal-dependency ethos (see src/evidence/bm25_retriever.py's own "zero
# new dependencies" posture). Only sets a var if not already present in the
# environment, so an explicit shell-exported value always wins.
# ---------------------------------------------------------------------------

def _load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv()


def has_groq_credentials() -> bool:
    return bool(os.environ.get("GROQ_API_KEYS", "").strip())


class LLMUnavailable(Exception):
    """Raised when no LLM call could be completed (no credentials, every key
    in the pool rate-limited/rejected, network unreachable, ...). Callers
    (agents/llm_client.py::run_tool_loop) catch this and treat it as "this
    agent produced nothing usable this round" -- NEVER a crash of the whole
    investigation (task §9: budgets/graceful degradation, not indefinite
    retry or a hard failure)."""


# ---------------------------------------------------------------------------
# Provider-agnostic response shape
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    content: list             # normalized blocks: {"type":"text","text":...} / {"type":"tool_use","id","name","input"}
    stop_reason: str          # normalized: "end_turn" | "tool_use" | "max_tokens" | other raw value
    input_tokens: int
    output_tokens: int
    model: str
    raw_message: dict = field(default_factory=dict)   # provider-native assistant message, fed back verbatim


class LLMClient(Protocol):
    def create(self, *, system: str, messages: list, tools: list, max_tokens: int = 4096) -> LLMResponse: ...
    def build_user_message(self, text: str) -> dict: ...
    def build_tool_result_messages(self, results: list) -> list: ...


# ---------------------------------------------------------------------------
# Groq key pool — round-robins across GROQ_API_KEYS (17 keys supplied by the
# user for exactly this reason: spreading load across free-tier per-key
# rate limits).
# ---------------------------------------------------------------------------

class GroqKeyPool:
    def __init__(self, keys: Optional[list] = None):
        raw = keys if keys is not None else os.environ.get("GROQ_API_KEYS", "")
        self._keys = [k.strip() for k in (raw if isinstance(raw, list) else raw.split(",")) if k.strip()]
        self._cycle = itertools.cycle(self._keys) if self._keys else None

    def __len__(self) -> int:
        return len(self._keys)

    def next_key(self) -> str:
        if self._cycle is None:
            raise LLMUnavailable("No GROQ_API_KEYS configured.")
        return next(self._cycle)


# ---------------------------------------------------------------------------
# Tool-schema conversion — the ONE place tools/schemas.ToolDefinition (and a
# local "submit_*" tool) becomes Groq's OpenAI-style nested JSON schema.
# ---------------------------------------------------------------------------

_JSON_TYPE = {
    "str": "string", "int": "integer", "float": "number", "bool": "boolean",
    "list[str]": "array", "dict[str,str]": "object",
}


def tool_definition_to_schema(tool_def: ToolDefinition) -> dict:
    properties, required = {}, []
    for p in tool_def.input_schema:
        prop = {"type": _JSON_TYPE.get(p.type, "string")}
        if p.type == "list[str]":
            prop["items"] = {"type": "string"}
        if p.allowed_values is not None:
            prop["enum"] = list(p.allowed_values)
        properties[p.name] = prop
        if p.required:
            required.append(p.name)
    return {
        "type": "function",
        "function": {
            "name": tool_def.tool_name, "description": tool_def.description,
            "parameters": {"type": "object", "properties": properties, "required": required,
                            "additionalProperties": False},
        },
    }


def submit_tool_schema(name: str, description: str, json_schema: dict) -> dict:
    """Builds a Groq-shaped tool definition for an agent's "submit_result"
    tool -- this tool is NEVER routed through tools/gateway.call_tool(); it
    carries no data access, only the model's own structured conclusion,
    which the calling agent module still runs through the numeric/causal
    guardrails before it can enter InvestigationState (agents/models.py)."""
    return {"type": "function", "function": {"name": name, "description": description, "parameters": json_schema}}


def tools_for_agent_role(agent_role: AgentRole) -> list:
    """Every governed tool this agent role is authorized to call, in Groq
    schema form -- built from the EXACT SAME tools/policy.ALLOWED_TOOLS_PER_AGENT
    + tools/gateway.TOOL_REGISTRY the gateway itself enforces, so the tool
    list shown to the model can never drift from what the gateway will
    actually allow."""
    return [tool_definition_to_schema(td) for name, td in gateway.TOOL_REGISTRY.items()
            if agent_role in td.allowed_agents]


# ---------------------------------------------------------------------------
# Groq client (real)
# ---------------------------------------------------------------------------

def _normalize_finish_reason(finish_reason: str) -> str:
    return {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}.get(finish_reason, finish_reason)


class GroqLLMClient:
    def __init__(self, model: str = DEFAULT_MODEL, key_pool: Optional[GroqKeyPool] = None):
        self.model = model
        self.key_pool = key_pool or GroqKeyPool()
        self._clients_by_key: dict = {}

    def _client_for(self, key: str):
        import groq
        if key not in self._clients_by_key:
            self._clients_by_key[key] = groq.Groq(api_key=key)
        return self._clients_by_key[key]

    def build_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def build_tool_result_messages(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": tool_use_id, "content": content} for tool_use_id, content in results]

    def create(self, *, system: str, messages: list, tools: list, max_tokens: int = 4096) -> LLMResponse:
        import groq

        if len(self.key_pool) == 0:
            raise LLMUnavailable("No GROQ_API_KEYS configured -- cannot make a real LLM call.")

        full_messages = [{"role": "system", "content": system}] + list(messages)
        # Groq's API rejects an explicit tool_choice=null (400: "Only allowed
        # string values for 'tool_choice' are [none, auto, required]") --
        # the SDK's own Omit/NOT_GIVEN sentinel must be used by simply
        # OMITTING the kwarg, not by passing None, when there are no tools
        # for this call (e.g. the has_groq_credentials() reachability probe).
        request_kwargs: dict = {"model": self.model, "messages": full_messages, "max_tokens": max_tokens}
        if tools:
            request_kwargs["tools"] = tools
            # "required" (not "auto"): every turn in this loop must either
            # request a governed tool or call the agent's own submit_* tool
            # -- the loop's only valid exits are a submit_* call or
            # exhausting max_tool_iterations (agents/llm_client.run_tool_loop).
            # With "auto", a smaller/open model observed here would sometimes
            # just emit a plain-text summary near the end of its budget
            # instead of calling submit_*, silently discarding all the real
            # tool-gathered evidence (run_tool_loop correctly treats that as
            # "nothing usable" rather than crashing, but it wastes the whole
            # round-trip budget) -- "required" removes that escape hatch.
            request_kwargs["tool_choice"] = "required"

        last_exc: Optional[Exception] = None
        for _ in range(len(self.key_pool)):
            key = self.key_pool.next_key()
            try:
                response = self._client_for(key).chat.completions.create(**request_kwargs)
                return _normalize_groq_response(response)
            except (groq.APIStatusError, groq.APIConnectionError, groq.APITimeoutError) as exc:
                # groq.APIStatusError is the base class for RateLimitError/
                # AuthenticationError/NotFoundError/BadRequestError/
                # InternalServerError/etc. -- caught broadly rather than
                # enumerating subclasses because live-probing this user's
                # own 17 keys found the free tier's tokens-per-minute limit
                # (8000 TPM per key) surfaces as a plain APIStatusError with
                # HTTP 413, not the more specific RateLimitError a narrower
                # catch would have missed (see STEP5_VALIDATION.md §14/§17
                # for the exact error observed). Rotating to the next key on
                # ANY status error is the right response here: a different
                # key may have fresh TPM budget, different model access, or
                # be valid where this one was rejected outright. A short
                # pause before the next attempt gives a per-minute token
                # budget (observed: 8000 TPM on this account) a moment to
                # recover rather than immediately re-hammering it.
                last_exc = exc
                time.sleep(1.5)
                continue
        raise LLMUnavailable(f"Every key in the pool ({len(self.key_pool)}) failed. Last error: {last_exc}")


def _normalize_groq_response(response: Any) -> LLMResponse:
    choice = response.choices[0]
    message = choice.message
    content_blocks = []
    if message.content:
        content_blocks.append({"type": "text", "text": message.content})

    raw_message = {"role": "assistant", "content": message.content}
    if message.tool_calls:
        raw_message["tool_calls"] = []
        for tc in message.tool_calls:
            raw_message["tool_calls"].append(
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
            )
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}   # malformed args -> empty dict; the Tool Gateway's input validation then
                            # rejects any missing required field rather than this module guessing.
            content_blocks.append({"type": "tool_use", "id": tc.id, "name": tc.function.name, "input": args})

    usage = response.usage
    return LLMResponse(
        content=content_blocks, stop_reason=_normalize_finish_reason(choice.finish_reason),
        input_tokens=usage.prompt_tokens if usage else 0, output_tokens=usage.completion_tokens if usage else 0,
        model=response.model, raw_message=raw_message,
    )


# ---------------------------------------------------------------------------
# Fake client — the test double used by ~90% of Step 5's test coverage.
# No network. Deterministic. Scripted via an ordered queue of LLMResponse,
# or a callable(messages) -> LLMResponse for tests that need to react to
# what was sent (e.g. verifying tool_result content).
# ---------------------------------------------------------------------------

class FakeLLMClient:
    def __init__(self, script: Any):
        """`script` is either a list[LLMResponse] (replayed in order, raising
        RuntimeError if exhausted) or a callable(messages: list) -> LLMResponse."""
        self._script = script
        self._index = 0
        self.calls: list = []   # every (system, messages, tools) this fake was called with, for assertions

    def build_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def build_tool_result_messages(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": tool_use_id, "content": content} for tool_use_id, content in results]

    def create(self, *, system: str, messages: list, tools: list, max_tokens: int = 4096) -> LLMResponse:
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if callable(self._script) and not isinstance(self._script, list):
            return self._script(messages)
        if self._index >= len(self._script):
            raise RuntimeError(f"FakeLLMClient script exhausted after {self._index} call(s).")
        response = self._script[self._index]
        self._index += 1
        return response


# ---------------------------------------------------------------------------
# The shared manual agentic loop
# ---------------------------------------------------------------------------

def run_tool_loop(state: InvestigationState, agent_role: AgentRole, llm_client: LLMClient, ctx: ToolContext, *,
                   system: str, user_content: str, tool_schemas: list, submit_tool_name: str,
                   max_tool_iterations: int = 6) -> Optional[dict]:
    """Runs the manual tool-use loop for one LLM-backed agent call. Returns
    the `input` dict of the `submit_tool_name` tool call once the model
    makes it, or None if the model never does (budget exhausted, LLM
    unavailable, or the model stopped without submitting) -- callers MUST
    treat None as "this round produced nothing usable", never a crash."""
    messages = [llm_client.build_user_message(user_content)]

    for _ in range(max_tool_iterations):
        # Deliberately NOT caught here: exhausting the agent_calls budget
        # (how many LLM round-trips this investigation may make at all) is
        # an Orchestrator-level "never continue indefinitely" stop (task
        # §9), not a per-agent degrade-gracefully case -- it propagates up
        # through the calling agent module to orchestrator.py's _stage
        # wrapper, which transitions the whole investigation to
        # BUDGET_EXCEEDED. Contrast with a single TOOL call's budget
        # (tools/gateway.call_tool's own tool_calls/retrieval_calls
        # increment), which fails only that one call and lets the agent
        # adapt (e.g. submit with whatever evidence it already has).
        state.budgets.increment("agent_calls")

        t0 = time.perf_counter()
        try:
            response = llm_client.create(system=system, messages=messages, tools=tool_schemas, max_tokens=4096)
        except LLMUnavailable as exc:
            state.security_events.append({
                "type": "llm_unavailable", "agent_role": agent_role.value, "error": str(exc), "timestamp": now_iso(),
            })
            return None
        latency_ms = (time.perf_counter() - t0) * 1000
        record_llm_call(state, agent_role, response, latency_ms)
        messages.append(response.raw_message)

        tool_use_blocks = [b for b in response.content if b["type"] == "tool_use"]
        submit_block = next((b for b in tool_use_blocks if b["name"] == submit_tool_name), None)
        if submit_block is not None:
            return submit_block["input"]
        if not tool_use_blocks:
            return None   # end_turn without submitting -- nothing usable this round

        results = []
        for block in tool_use_blocks:
            from agents.security import format_tool_result_for_llm
            call_result = gateway.call_tool(state, agent_role, block["name"], block["input"], ctx)
            content_str = format_tool_result_for_llm(block["name"], call_result.ok, call_result.result,
                                                      call_result.error)
            results.append((block["id"], content_str))
        messages.extend(llm_client.build_tool_result_messages(results))

    return None
