# MULTI_AGENT_ARCHITECTURE — Step 5: the Secure Multi-Agent Investigation Engine

## 0. The deterministic/LLM split, and why

Steps 1–4A are entirely deterministic — every KPI value, PVM decomposition,
anomaly verdict, and retrieval result comes from a real, reproducible engine,
and `llm_calls_made: 0` on every telemetry record (see `STEP4_VALIDATION.md`
§16). Step 5 adds genuinely interpretive work on top — formulating
hypotheses, deciding what evidence to request, interpreting what it means,
searching adversarially for counter-evidence — and for that work, three of
the six agents make real calls to an LLM (Groq, `openai/gpt-oss-20b` by
default — the user's own choice, for cost; see §0.1). The other three agents
never call an LLM at all:

| Agent | LLM-backed? | Why |
|---|---|---|
| Orchestrator | No | "The Orchestrator must NOT independently generate business conclusions" — a fixed, deterministic control flow through the state machine. |
| Hypothesis | **Yes** | "formulate hypotheses" is explicitly listed as something an agent may do. |
| Evidence | **Yes** | "decide what evidence to request … interpret evidence" — explicitly allowed. |
| Counter-Evidence | **Yes** | "identify alternative explanations" — explicitly allowed, and this role is inherently interpretive (adversarial search). |
| Causal Method Selector | No | "Never allow the LLM to declare causality." |
| Confidence Judge | No | "Implement this primarily as a deterministic policy engine." |

**LLM ≠ quantitative truth is enforced structurally, not by asking the model
nicely.** Every LLM-backed agent:

1. Can only propose tool calls from a **fixed, per-role allowlist**
   (`tools/policy.ALLOWED_TOOLS_PER_AGENT`), enforced by `tools/gateway.py`
   regardless of what the model asks for.
2. Can only cite **numbers that a real tool call actually returned this
   round** — checked by `agents.models.validate_numeric_claims()` against
   `build_allowed_numbers()`, built fresh from real evidence every time.
3. Can never phrase a conclusion as an established cause — checked by
   `agents.models.assert_no_unsupported_causal_language()`, enforced at
   dataclass-construction time for `Hypothesis`/`ClassifiedEvidence`/
   `MethodSelection`/`CounterEvidenceReport` fields.
4. Can never invent an `evidence_id` — every citation is checked against
   `ToolContext.evidence_store`; a nonexistent id is dropped and logged as
   `hallucinated_evidence_id`, never silently accepted.
5. Has its qualitative judgment (SUPPORTS/CONTRADICTS/CONTEXT/INSUFFICIENT,
   contradiction severity) subject to a **deterministic floor** that can only
   ever downgrade, never upgrade, what the model said — see
   `evidence_agent._apply_floor()` and
   `counter_evidence_agent.score_contradiction_severity()`.

None of this requires the model to behave well — it requires the *system
around* the model to never trust it for anything quantitative or causal, and
to check everything else against fixed rules before it becomes part of the
investigation record.

### 0.1 Provider: Groq, not Anthropic

Step 5 was originally scoped to call Claude directly (a scaffolded
`anthropic` dependency and `AnthropicLLMClient` design existed briefly).
Partway through implementation the user supplied 17 Groq API keys and asked
for Groq specifically, for cost (Groq's free tier). This was a **provider
swap, not an architecture change**: `agents/llm_client.py`'s `LLMClient`
protocol (`.create(system, messages, tools, max_tokens) -> LLMResponse`,
plus two small message-shape helpers) was already provider-agnostic, so
`GroqLLMClient` slotted in without touching `run_tool_loop()` or any agent
module. `GroqKeyPool` round-robins across all 17 keys per request (and
rotates again on a rate-limit/auth error), since that's the explicit reason
17 keys were supplied rather than one. `DEFAULT_MODEL` is a plain constant
(`openai/gpt-oss-20b`, overridable via a `GROQ_MODEL` env var) — chosen
because it was the model actually verified live, with real tool-calling
support, against the user's own 17 keys (the SDK-advertised default,
`llama-3.3-70b-versatile`, returned a 404 model-not-found for every one of
those keys when probed — see `docs/AGENT_SECURITY.md` §5). Groq's model
catalog changes faster than Anthropic's, so this is deliberately a
one-line/env-var change, not a hardcoded assumption baked into call sites.

The 17 keys live in a local, gitignored `.env` (never committed, never
logged, never printed) — see `docs/AGENT_SECURITY.md` §5 for the full
handling discussion.

### 0.2 Reproducibility: FakeLLMClient

Every test in `tests/test_hypothesis.py`, `test_evidence_agent.py`,
`test_counter_evidence.py`, `test_orchestrator.py`, and the bulk of
`test_prompt_injection.py` uses `agents.llm_client.FakeLLMClient` — a
scripted test double with **zero network calls**, so the suite is fast,
deterministic, and runs without credentials. `FakeLLMClient` can be
constructed from a fixed queue of responses or a callable that inspects the
running message history (used to build tests that request a *real* tool
call, read the *real* evidence_id that came back, and classify it — proving
the full pipeline, not just the guardrails in isolation). A small number of
tests are gated behind `agents.llm_client.has_groq_credentials()` and
`skipif`-skip when no credentials are reachable; the automated test suite
itself was still run entirely against `FakeLLMClient` throughout
development (fast, deterministic, no per-test API spend), even though this
environment turned out to have live network access to Groq — the November
2017 demonstration script (`scripts/step5_investigate_november_2017.py`)
is what actually exercises the real API end-to-end, see §0.1 and
`STEP5_VALIDATION.md` §14.

---

## 1. Architecture diagram

```
                          ┌─────────────────────────┐
                          │   Orchestrator (det.)    │
                          │  state machine + budgets │
                          └────────────┬─────────────┘
                                       │ delegates, in fixed order
        ┌──────────────────┬───────────┴───────────┬──────────────────┐
        ▼                  ▼                        ▼                  
┌───────────────┐  ┌───────────────┐  ┌────────────────────────┐
│ Hypothesis     │  │ Evidence       │  │ Counter-Evidence        │
│ Agent (LLM)    │  │ Agent (LLM)    │  │ Agent (LLM)              │
└───────┬────────┘  └───────┬────────┘  └───────────┬─────────────┘
        │  tool_use blocks  │                        │
        └──────────┬────────┴────────────┬───────────┘
                    ▼                     
        ┌─────────────────────────────────────────┐
        │           Tool Gateway (det.)             │
        │ Auth → Authz → Clearance → Input Val →     │
        │ Execute → Output Val → Audit + Budget       │
        └────────────────────┬──────────────────────┘
                              ▼
        ┌─────────────────────────────────────────┐
        │  analytics_tools.py / evidence_tools.py    │
        │  (thin, governed wrappers)                 │
        └────────────────────┬──────────────────────┘
                              ▼
        ┌─────────────────────────────────────────┐
        │   Step 1-4 engines (KPIEngine, driver_engine,│
        │   anomaly.engine, BM25Index, evidence graph) │
        └─────────────────────────────────────────┘

        ┌───────────────┐   ┌───────────────┐
        │ Causal Method  │   │ Confidence     │      Both deterministic —
        │ Selector (det.)│   │ Judge (det.)   │      read only already-
        └───────────────┘   └───────────────┘      guardrailed dataclasses
```

## 2. The manual tool-use loop (`agents/llm_client.run_tool_loop`)

Each LLM-backed agent call is one `run_tool_loop()` invocation:

1. Send the system prompt (`agents/prompts.py`) + a user message describing
   the task, and the tool schemas this agent role is authorized for
   (`agents.llm_client.tools_for_agent_role`, built from the *exact same*
   `tools/gateway.TOOL_REGISTRY` + `tools/policy.ALLOWED_TOOLS_PER_AGENT`
   the gateway itself enforces — so the tool list shown to the model can
   never drift from what will actually be allowed) plus one local
   `submit_*` tool for returning its structured result.
2. If the model requests a `submit_*` call: validate its JSON, return it —
   this never touches `tools/gateway.py` (it carries no data access, only
   the model's own conclusion, guardrailed by the calling agent module
   before it can enter `InvestigationState`).
3. If the model requests any OTHER tool: route it through
   `tools.gateway.call_tool()`, wrap any `UNTRUSTED_DATA` content in the
   result (`agents.security.format_tool_result_for_llm`), append the result,
   loop.
4. If the model stops without submitting, or the `agent_calls` budget is
   exhausted, or the LLM is unreachable: return `None` — the calling agent
   module treats this as "nothing usable this round," never a crash (see
   §4 below on budgets).

## 3. "Enough evidence collected" — no adaptive loop (documented scope boundary)

This prototype's Evidence Agent tool plan is model-driven per hypothesis
(the model decides what to call, within its allowlist, inside one bounded
`run_tool_loop`), but the Orchestrator itself never adaptively decides "call
the Evidence Agent again because confidence is still low" — each of the six
agent modules runs exactly once per investigation (Evidence/Counter-Evidence
run once *per hypothesis*, inside their own module). "Enough evidence" is
operationally: the bounded tool-use loop for that hypothesis completed
(model submitted, or exhausted its iteration/budget cap). A more adaptive
architecture — re-invoking Evidence/Counter-Evidence with a targeted
follow-up question when the Confidence Judge finds a hypothesis's evidence
thin — is a natural extension this design leaves room for (the state
machine's `CONFIDENCE_EVALUATION → NEEDS_CLARIFICATION` transition is
already the seam) but was not built, to keep the pipeline's control flow a
single, auditable pass.

## 4. Known inefficiency: the double context build

`tools/context.build_tool_context()` calls
`evidence.engine.build_november_2017_evidence_package()` (for structured
evidence + the graph) **and** `evidence.engine.build_review_index()` (for
the review corpus + `FlatCosineIndex`) separately, over the same October–
November 2017 window — an extra ~1 pass over ~12K review rows (dominated by
`langdetect`, similar cost to what Step 4's own `build_november_2017_evidence_package`
already pays once). Documented rather than hidden: a future optimization
would have `build_november_2017_evidence_package` return the review corpus
and index it already built, rather than Step 5 re-deriving them.

## 5. Cost/token telemetry

`agents/telemetry.py` builds one `TelemetryRecord` per LLM call (real
`model` id, real `input_tokens`/`output_tokens` from the provider's `usage`
field, an estimated cost from `GROQ_PRICING_PER_MILLION_TOKENS` — approximate,
not billing-accurate, see that module's docstring) and one per deterministic
agent pass (`model="deterministic_rule_engine_v1"`, 0 tokens, 0 cost — this
is literally true for those three agents, not a placeholder).
