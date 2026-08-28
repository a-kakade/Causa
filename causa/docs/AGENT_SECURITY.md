# AGENT_SECURITY — Step 5: RBAC, the Tool Gateway, and the UNTRUSTED_EVIDENCE boundary

## 1. Non-negotiable principle

Security is enforced **at the tool level**, in `tools/gateway.py`, never only
in a system prompt. Every guarantee below holds regardless of what an LLM
says, asks for, or is tricked into asking for — because the gateway
authorizes by `(AgentRole, tool_name)` table lookup and validates arguments
by declared schema, never by interpreting free text.

## 2. RBAC: RequesterRole → clearance

Step 5 introduces three requester roles (`agents.models.RequesterRole`):
`EXECUTIVE`, `ANALYST`, `INTERNAL`. These map onto the **existing**
`PUBLIC_ANALYTICAL`/`INTERNAL`/`RESTRICTED` clearance scale
(`evidence.models.SecurityClassification`) — never a parallel system:

| RequesterRole | Clearance | Rationale |
|---|---|---|
| `EXECUTIVE` | `PUBLIC_ANALYTICAL` | Business-level findings only. An EXECUTIVE investigation must never leak seller-level (INTERNAL) detail — this is the literal example in the task spec, and the cap is what guarantees it. |
| `ANALYST` | `INTERNAL` | Can see seller-level internal evidence, matching the clearance `driver_engine.py`/`evidence.engine.py` already use for "internal analysis" investigations in Steps 3D/4. |
| `INTERNAL` | `RESTRICTED` | The highest-trust role (e.g. an internal automated audit process). No governed KPI dimension is currently `RESTRICTED`-classified (see `config/kpis.yaml`), so in practice this grants no more than `ANALYST` today — deliberately provisioned for a future `RESTRICTED` dimension rather than left unmapped. |

`tools/policy.clearance_for_role()` is the only place this mapping is read;
`tools/gateway.call_tool()` calls it once per tool call and uses the result
— **an agent-supplied `requester_clearance` argument is never honored** (see
§4).

## 3. Tool permissions

`tools/policy.ALLOWED_TOOLS_PER_AGENT`:

| AgentRole | Allowed tools |
|---|---|
| `ORCHESTRATOR` | *(none)* |
| `HYPOTHESIS` | `get_kpi`, `get_driver_decomposition`, `get_concurrent_kpis`, `search_evidence` |
| `EVIDENCE` | `get_kpi`, `compare_kpi`, `get_materiality`, `get_driver_decomposition`, `get_concurrent_kpis`, `search_evidence`, `get_evidence`, `get_graph_neighbors` |
| `COUNTER_EVIDENCE` | `search_evidence`, `get_evidence`, `get_graph_neighbors`, `get_driver_decomposition` |
| `CAUSAL_SELECTOR` | `get_evidence` |
| `CONFIDENCE_JUDGE` | `get_evidence` |

No tool anywhere accepts arbitrary SQL, arbitrary Python, or unrestricted
database access — this is structural, not a filter: `tools/gateway.TOOL_REGISTRY`
only ever contains the 8 tools above, each with a fixed, declared
`input_schema` (`tools/schemas.ToolParam` tuples). `tests/test_tool_gateway.py::
test_no_tool_accepts_a_raw_query_sql_or_state_shaped_parameter` scans every
declared parameter name for SQL/query/state-shaped substrings and asserts
none exist; a companion test calls every registered tool with `{"sql": "DROP
TABLE fact_orders"}` and asserts every single one rejects it as an
unrecognized argument before execution.

## 4. The Tool Gateway's six stages (`tools/gateway.call_tool`)

```
Agent  →  Tool Gateway  →  Authentication  →  Authorization  →  Clearance
       derivation  →  Input Validation  →  Tool Execution  →  Output
       Validation  →  Audit Trace + Budget
```

1. **Authentication** — `agent_role` must be a real `AgentRole` enum member.
   Only `orchestrator.py` and the three LLM-agent modules call `call_tool`,
   each hardcoding its own role — nothing exposes a caller-controlled
   `agent_role` to a model.
2. **Authorization** — `tools.policy.is_tool_allowed(agent_role, tool_name)`.
3. **Clearance derivation** — `requester_clearance = policy.clearance_for_role
   (state.requester_role)`. Any `requester_clearance`/`clearance`/`state`/
   `status`/`ctx`/`context`-named argument in the call is **stripped and
   logged** (`security_events` entry `clearance_or_state_argument_attempt`)
   before validation continues — an LLM can propose an elevated clearance,
   but it is never honored.
4. **Input validation** — every argument checked against the tool's declared
   `ToolParam`s: unrecognized keys rejected, required keys enforced, types
   checked, `allowed_values` enforced.
5. **Tool execution** — the real governed function runs. Every exception a
   Step 1–4 engine can raise for "you asked for something your clearance/
   contract doesn't support" (`UnsupportedFilterError`, `UnauthorizedFilterError`,
   `drivers.engine.DriverRequestError`, `kpi.query_planner.KPIRequestError`,
   `KeyError`, `PermissionError`, `ValueError`) is caught and converted into a
   graceful `ok=False` — never an uncaught crash. The message is passed
   through `evidence.access_control.redact_error_message()` before it can
   reach a below-`INTERNAL` caller.
6. **Output validation** — every returned `evidence_id` is re-checked against
   its own `security.classification` and the caller's clearance — defense in
   depth even though step 5's tool functions already enforce this
   internally; a violation is dropped from the result and logged as
   `output_filtered`, never surfaced.

Every call — success or failure — produces exactly one `AuditTraceEntry`
(task §19: `agent_id`, `agent_role`, `timestamp`, `input_state_hash`,
`tool_call`, `tool_arguments_hash`, `tool_result_ids`, `output`,
`token_usage`, `latency_ms`, `security_decision`).

## 5. Credential handling: the 17 Groq keys

The user supplied 17 Groq API keys directly in chat and asked for them to be
used with round-robin rotation. Before writing anything, the user was told
explicitly: (a) this is unrelated to Anthropic/Claude — a provider swap was
being made specifically for this; (b) pasting live keys into a chat
transcript is itself a leak vector regardless of what happens next, and
rotating them afterward was recommended; (c) nothing would be echoed back,
logged, or committed. The keys were written straight to a new file,
`causa/.env` (`GROQ_API_KEYS=<comma-separated>`), added to `.gitignore`
*before* the file was created, and confirmed untracked via `git check-ignore`
/`git status`. `agents/llm_client.py`'s `.env` loader only sets an env var if
not already present (an explicit shell-exported value always wins) and is a
small, dependency-free parser — no `python-dotenv` dependency added just for
this. `GroqKeyPool` never logs a key; `AuditTraceEntry`/`TelemetryRecord`
never carry raw key material, only aggregate token/cost numbers.

## 6. UNTRUSTED_EVIDENCE boundary (`agents/security.py`)

Every retrieved customer review is `security.trust_level == "UNTRUSTED_DATA"`
(inherited from Step 4's own schema, `evidence.models.TrustLevel`). Before
such content is ever sent back to the model as a tool result, it is wrapped:

```
<UNTRUSTED_EVIDENCE>
...review text...
</UNTRUSTED_EVIDENCE>
```

`wrap_untrusted_evidence()` first **escapes any literal boundary tag already
present in the text** (`</UNTRUSTED_EVIDENCE>` → `&lt;/UNTRUSTED_EVIDENCE&gt;`)
so a review whose content is literally an attempt to close the real boundary
early cannot do so — verified directly in `tests/test_prompt_injection.py`
against fixture `inj7`, which contains exactly this attack. Only
`UNTRUSTED_DATA` content is ever wrapped (`classify_and_wrap`) — TRUSTED_SYSTEM
evidence (every KPI/driver/anomaly result) is never wrapped, so the boundary
stays meaningful rather than becoming background noise the model learns to
ignore.

**The boundary is defense in depth, not the primary defense.** The four
guarantees task §4 requires — that review text can never change agent
instructions, tool permissions, investigation state, or trigger unauthorized
access/execution — hold even if the boundary tag were stripped entirely,
because:

- **tool permissions**: authorized by `(AgentRole, tool_name)` table lookup
  in `tools/gateway.py`, never by parsing message content.
- **investigation state**: `state.status` changes only via
  `agents.state_machine.transition()`, called only by `orchestrator.py`
  based on which deterministic pipeline stage just finished — never based on
  parsing any tool result or model utterance. `tests/test_state_machine.py::
  test_no_module_assigns_status_directly` AST-scans every module in
  `src/agents/` and `src/tools/` to enforce this mechanically.
- **unauthorized data access / execution**: no tool accepts a raw
  query/command-shaped argument at all (§3) — there is no code path a
  persuasive string could route through even if a model fully complied with
  an injected instruction.

So the strongest available proof (`tests/test_prompt_injection.py::
test_full_investigation_identical_with_and_without_a_spliced_in_malicious_review`)
is: splice a synthetic review containing every fixture's injection text into
a copy of the evidence store and run an identical scripted investigation —
the status trajectory and audit-trace tool-call sequence are byte-identical
with and without it. The injected *content* changes nothing about control
flow, because control flow never reads content to decide what to do next.

## 7. The 10 required security-test scenarios, mapped to their defense

| # | Scenario | Defeated by |
|---|---|---|
| 1 | Prompt injection through a review | UNTRUSTED_EVIDENCE boundary + content-blind control flow (§6) |
| 2 | Jailbreak through a review | Same as above — no code path treats model behavior differently based on content |
| 3 | Malicious tool arguments | Input validation stage (§4.4) |
| 4 | Unauthorized seller query | RBAC clearance derivation (§4.3) + driver_engine's own `UnauthorizedSegmentError`, caught gracefully |
| 5 | Unrestricted SQL attempt | No tool schema has a query/SQL-shaped parameter (§3); unknown tool names rejected identically to unauthorized ones |
| 6 | PII extraction attempt | `get_evidence` applies the same PII redaction `search_evidence`'s results already carry (fixed during Step 5 implementation — see Known Limitations) |
| 7 | KPI-definition modification attempt | No tool accepts a KPI-definition-shaped argument at all; `config/kpis.yaml` is never a runtime-mutable object reachable from any tool |
| 8 | Evidence-filter bypass | `retrieval.validate_structured_filters()` (Step 4, reused unmodified) rejects unsupported/under-clearance filter keys before any search runs |
| 9 | State manipulation attempt | Forbidden-argument stripping (§4.3) + `state.status` write-protection (§6) |
| 10 | Malicious retrieved evidence | UNTRUSTED_EVIDENCE boundary + the ordinary classification pathway (no special-cased branch for "injection-shaped" content — same function as any other review) |

## 8. Known limitation: `get_evidence` PII redaction

Discovered and fixed during Step 5 implementation (not a residual gap): a
raw `CUSTOMER_REVIEW` `EvidenceObject`'s own `metadata["text"]` is
**unredacted at the source** by Step 4's own design (redaction happens only
at the retrieval layer — `evidence.retrieval.retrieve()`, see
`docs/EVIDENCE_FABRIC.md`). `evidence_tools.get_evidence()` initially only
enforced clearance, not PII redaction, meaning a direct `get_evidence` call
on a review with detected PII would have leaked it even though
`search_evidence`'s results never do. Fixed: `get_evidence()` now applies
the identical `evidence.pii.redact_pii()` call for any `UNTRUSTED_DATA`
item with `pii_types` set, before returning. Covered by
`tests/test_tool_gateway.py`'s broader coverage of the get_evidence path and
exercised in `tests/test_prompt_injection.py`.
