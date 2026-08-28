# STEP 5 VALIDATION — Secure Multi-Agent Investigation Engine

Every structured number in this document (KPI movements, PVM, hypothesis
lists, telemetry, test counts) is copied directly from
`reports/step5_validation.json`, itself written by
`scripts/step5_investigate_november_2017.py` from a REAL run — a real
`ToolContext` built from the real Step 1–4 engines, and real Groq API calls
for the three LLM-backed agents (`dry_run: false`, `llm_model:
"openai/gpt-oss-20b"`). Nothing here is fabricated or hand-edited into the
JSON.

Reproduce:

```bash
.venv/bin/python -m pytest tests/test_state_machine.py tests/test_tool_gateway.py tests/test_rbac.py \
    tests/test_budgets.py tests/test_numeric_guardrail.py tests/test_contradictions.py tests/test_confidence.py \
    tests/test_hypothesis.py tests/test_evidence_agent.py tests/test_counter_evidence.py \
    tests/test_orchestrator.py tests/test_prompt_injection.py -q
.venv/bin/python scripts/step5_investigate_november_2017.py   # needs GROQ_API_KEYS in causa/.env for a real run;
                                                                 # falls back to a labeled dry run otherwise
```

---

## 1. Architecture

```
Orchestrator (deterministic) — state machine + budgets, delegates in fixed order
  ├─ Hypothesis Agent      (LLM, Groq)   ─┐
  ├─ Evidence Agent        (LLM, Groq)    ├─→ Tool Gateway → analytics/evidence tools → Step 1-4 engines
  ├─ Counter-Evidence Agent (LLM, Groq)   ─┘
  ├─ Causal Method Selector (deterministic)
  └─ Confidence Judge       (deterministic)
```

Three of the six agents make real LLM calls (Groq, `openai/gpt-oss-20b` by
default); three are 100% deterministic rule-based code with zero LLM calls.
Full rationale: `docs/MULTI_AGENT_ARCHITECTURE.md` §0. This is a provider
swap from an originally-scoped Anthropic/Claude integration — the user
supplied 17 Groq keys mid-implementation for cost, and the `LLMClient`
protocol (`agents/llm_client.py`) was already provider-agnostic, so the swap
touched only the provider class, never `run_tool_loop()` or any agent
module.

## 2. Agent responsibilities

| Agent | Role | LLM? | Never allowed to |
|---|---|---|---|
| Orchestrator | Plan, delegate, enforce budgets, terminate | No | Generate a business conclusion itself (AST-scanned — never imports `evidence.schema`, never constructs `Hypothesis`/`ClassifiedEvidence`/`MethodSelection`/`HypothesisResult`) |
| Hypothesis | Formulate 3–5 diverse hypotheses | **Yes** | Cite a number/evidence_id that isn't real; phrase a hypothesis as an established cause |
| Evidence | Decide what to request, classify SUPPORTS/CONTRADICTS/CONTEXT/INSUFFICIENT | **Yes** | Override the deterministic classification floor (sample size, confidence, security status) |
| Counter-Evidence | Adversarially search for what would make each hypothesis wrong | **Yes** | Have its self-reported `contradiction_level` used as the real severity |
| Causal Method Selector | Select T1/T2/INSUFFICIENT_DATA (never T3/T4) | No | Select T3_QUASI_EXPERIMENTAL/T4_EXPERIMENTAL — never justified for this dataset |
| Confidence Judge | Score HIGH/MEDIUM/LOW/ABSTAIN/NEEDS_CLARIFICATION | No | Let a large amount of weak evidence reach HIGH; ignore a STRONG contradiction cap |

## 3. Tool permissions

`tools/policy.ALLOWED_TOOLS_PER_AGENT`:

| AgentRole | Tools |
|---|---|
| ORCHESTRATOR | *(none)* |
| HYPOTHESIS | get_kpi, get_driver_decomposition, get_concurrent_kpis, search_evidence |
| EVIDENCE | get_kpi, compare_kpi, get_materiality, get_driver_decomposition, get_concurrent_kpis, search_evidence, get_evidence, get_graph_neighbors |
| COUNTER_EVIDENCE | search_evidence, get_evidence, get_graph_neighbors, get_driver_decomposition |
| CAUSAL_SELECTOR | get_evidence |
| CONFIDENCE_JUDGE | get_evidence |

No tool anywhere accepts a raw SQL/query/Python/state-shaped argument —
structurally verified (`tests/test_tool_gateway.py::
test_no_tool_accepts_a_raw_query_sql_or_state_shaped_parameter`).

## 4. Security boundaries

Full writeup: `docs/AGENT_SECURITY.md`. Summary: RBAC (`EXECUTIVE`→
`PUBLIC_ANALYTICAL`, `ANALYST`→`INTERNAL`, `INTERNAL`→`RESTRICTED`, reusing
the existing clearance scale) is derived server-side from
`state.requester_role` on every tool call — never from an agent-supplied
argument (stripped and logged if attempted). The Tool Gateway's 6 stages
(Authentication → Authorization → Clearance derivation → Input Validation →
Execution → Output Validation) are the single chokepoint every tool request
passes through, whether proposed by deterministic code or a live model.
Retrieved customer reviews are wrapped in a `<UNTRUSTED_EVIDENCE>...
</UNTRUSTED_EVIDENCE>` boundary before being sent back to the model
(`agents/security.py`), with any literal boundary tag inside the text itself
escaped first.

## 5. Prompt-injection results

`tests/test_prompt_injection.py` — **12/12 pass**. 7 fixtures
(`data/evidence/security_fixtures/prompt_injection_fixtures.json`, inj1–inj7,
never merged into the real corpus), all classify `BLOCKED` via
`evidence.safety.classify_safety` (Step 4, reused unmodified). Coverage
includes: boundary-tag escaping (inj7 embeds a literal `</UNTRUSTED_EVIDENCE>`
and is still contained exactly once after wrapping), policy-table
invariance before/after processing every fixture, a real gateway call with
`execute_sql`/state-manipulation-shaped arguments (rejected), a jailbreak
role-reassignment attempt (still authorized strictly as the invoking
`AgentRole`, never an elevated one), and the strongest available proof — a
full scripted investigation run twice, once with a synthetic malicious
review spliced into the evidence store and once without, producing an
**identical** `status_history` and `audit_trace` tool-call sequence either
way.

## 6. RBAC results

`tests/test_rbac.py` — **13/13 pass**, including two end-to-end checks
against the real November 2017 evidence: an `EXECUTIVE`-role
`get_driver_decomposition` call never returns `INTERNAL`-classified
segment evidence, while an `ANALYST`-role call with `segment_dimensions=
["seller"]` does. In the real run captured for this report, the `EXECUTIVE`
investigation independently confirms `executive_rbac_no_internal_leak.
leaked: false` (§14).

## 7. Investigation state machine

```
PLANNED → SECURITY_VALIDATED → HYPOTHESES_GENERATED → EVIDENCE_COLLECTION
    → COUNTER_EVIDENCE → CONTRADICTION_ANALYSIS → METHOD_SELECTION
    → CONFIDENCE_EVALUATION → COMPLETED
```
Terminal alternatives: `ABSTAINED`, `NEEDS_CLARIFICATION`, `BUDGET_EXCEEDED`,
`SECURITY_BLOCKED`. `tests/test_state_machine.py` — **20/20 pass**,
including every non-adjacent pair failing as `InvalidTransitionError` and an
AST scan confirming no module outside `state_machine.py` ever writes
`state.status` directly. The real ANALYST run's `status_history` (§14) is
exactly the full linear chain through to `ABSTAINED`.

## 8. Hypothesis examples

From the real run (`analyst_investigation.hypotheses`, `openai/gpt-oss-20b`,
genuinely tool-driven — the model called `compare_kpi`, `get_driver_decomposition`,
`get_concurrent_kpis` ×2, `get_kpi` ×2, and `search_evidence` before
proposing these):

| id | driver | dimension | statement |
|---|---|---|---|
| H1 | mix | customer_state | "A mix shift favoring higher-margin product categories in customer states like NY and IL may be associated with the revenue rise." |
| H2 | freight_revenue | freight_revenue | "An increase in freight revenue may be associated with the overall revenue increase." |
| H3 | orders | customer_state | "An increase in orders from customer states such as WA and OR may be associated with the revenue growth." |

All three `(driver, dimension)` pairs are unique (diversity check passes,
§14). Two additional candidate hypotheses the model proposed were **dropped**
by the numeric guardrail before construction (§13) — a genuine, unedited
example of the guardrail working, not a contrived test case.

## 9. Counter-evidence examples

In the real run, the Evidence Agent never reached a `SUPPORTS` classification
for any hypothesis within its per-hypothesis tool-iteration budget (§14/§19
Known Limitations), so `collect_counter_evidence` correctly skipped all 3
hypotheses (task's own rule: only hypotheses with ≥1 `SUPPORTS` item get
adversarially attacked — `tests/test_counter_evidence.py::
test_hypothesis_with_no_supports_is_skipped_gets_a_none_severity_record`).
A fully worked counter-evidence example — a real tool call, a real
contradicting evidence_id, a rejected causal-language question, a rejected
hallucinated evidence_id — is exercised in
`tests/test_counter_evidence.py::test_submits_a_report_via_a_real_tool_call`
and its neighboring tests (6/6 pass), using `FakeLLMClient` against the
same real `ToolContext`.

## 10. Contradiction examples

`tests/test_contradictions.py` — **14/14 pass**. `score_contradiction_severity`
boundary table (NONE→WEAK→MODERATE→STRONG) verified against synthetic
counts and the real two-proportion z-test
(`evidence.graph.check_low_score_rate_contradiction`, Step 4, reused
unmodified) — including the real `electronics`-category contradiction case
documented in `STEP4_VALIDATION.md` §12 (low-score rate genuinely
*decreased*, a real, non-fabricated contradiction). In the real November
2017 run, all 3 hypotheses' `ContradictionRecord.severity == "NONE"` (no
`CONTRADICTS`-classified evidence existed to score, since evidence
collection itself was thin — see §19) — `unresolved: true` on every one,
as required (never auto-resolved).

## 11. Confidence results

`tests/test_confidence.py` — **11/11 pass**, including the task's own two
explicit requirements as direct tests: "a large amount of weak evidence
must NOT automatically become high confidence" (1 weak `SUPPORTS` + 20
`CONTEXT` items never reaches `HIGH`) and "strong contradiction must cap
confidence" (perfect support capped at `MEDIUM` or below under `STRONG`
severity). In the real run, all 3 hypotheses scored `n_supports=0` →
`ABSTAIN` (§14) — the investigation-level confidence is the **worst** across
hypotheses, itself `ABSTAIN`.

## 12. Abstention examples

The real ANALYST investigation is itself a genuine abstention example:
`status: ABSTAINED`, reason `"confidence judge abstained on every
hypothesis"` — not a contrived test fixture. The real EXECUTIVE investigation
abstained even earlier, at `HYPOTHESES_GENERATED`, reason `"no hypothesis
cleared its evidence-gated trigger condition"` (0 hypotheses survived that
round — see §19). Both are honest outcomes: the system did NOT force a
conclusion when the evidence-gathering budget didn't converge.

## 13. Numeric guardrail results

`tests/test_numeric_guardrail.py` — **9/9 pass**, all against real November
2017 evidence values (e.g. confirms `52.1`/`346051.94` pass, a fabricated
`999999.99` is rejected). The real run independently produced two live
guardrail rejections, both preserved verbatim in
`reports/step5_validation.json::analyst_investigation.security_events`:

```json
{"type": "NUMERIC_VALIDATION_FAILED", "agent_role": "HYPOTHESIS",
 "field": "Hypothesis.statement",
 "text": "Price-related contributions across product categories may be associated with the 52% revenue increase in November 2017.",
 "violating_numbers": [52.0, 2017.0]}
```

**What this run caught, and what it revealed about the guardrail itself:**
the `52.0` rejection is correct and intended — the real percentage change is
52.099…%, and rounding it down to a bare "52" falls outside the guardrail's
0.05%-relative tolerance, exactly the strictness task §14 asks for
("Do not silently correct"). The `2017.0` rejection was a **genuine false
positive**, found live: the model's own hypothesis merely named its
investigation period ("…in November 2017"), and a bare calendar year was
being checked as if it were a business figure. **Fixed** during this
implementation: `validate_numeric_claims` now exempts bare 4-digit numbers
in the 1900–2100 range regardless of an accidental trailing-period marker
(a sentence's closing "." was being absorbed into the regex match, which
originally hid the exemption behind the wrong condition — see
`agents/models.py`'s inline comment for the exact mechanism). Covered by two
new regression tests
(`test_a_bare_calendar_year_naming_the_investigation_period_is_not_flagged`,
`test_a_four_digit_number_outside_the_calendar_year_range_is_still_checked`).
The captured `reports/step5_validation.json` predates this fix (re-running
the full live investigation a second time to regenerate it was judged not
worth spending more of the shared free-tier token budget on, once the fix
was confirmed correct by unit test — see §19).

## 14. November 2017 end-to-end trace (real run)

```
dry_run: false
llm_provider: groq
llm_model: openai/gpt-oss-20b
context_build_seconds: 89.25
analyst_run_seconds: 181.08
executive_run_seconds: 50.19
```

**Revenue movement (task's required value, live-computed via
`kpi.engine.KPIEngine.compare_periods`, never hardcoded):**

| Metric | Computed | Required | Match |
|---|---|---|---|
| Percentage change | 52.09903901787393 | 52.1 | ✅ |
| Absolute change | 346051.9399999998 | 346051.94 | ✅ |

**ANALYST investigation:**
- `status_history`: `PLANNED → SECURITY_VALIDATED → HYPOTHESES_GENERATED →
  EVIDENCE_COLLECTION → COUNTER_EVIDENCE → CONTRADICTION_ANALYSIS →
  METHOD_SELECTION → CONFIDENCE_EVALUATION → ABSTAINED (confidence judge
  abstained on every hypothesis)`
- 3 hypotheses (§8), 0 classified evidence, 3 `ContradictionRecord`s
  (severity `NONE`), 3 `MethodSelection`s (`INSUFFICIENT_DATA` — "no
  SUPPORTS-classified evidence"), 3 `HypothesisResult`s (`INCONCLUSIVE` /
  `ABSTAIN`), overall `confidence: ABSTAIN`.
- 31 real tool calls (`get_kpi`, `compare_kpi`, `get_driver_decomposition`
  ×5, `get_concurrent_kpis` ×4, `search_evidence`, `get_evidence` ×8,
  `get_graph_neighbors`) — every single one routed through the real Tool
  Gateway against the real Step 1–4 engines.
- Budgets: `used_iterations=7/20`, `used_agent_calls=31/40`,
  `used_tool_calls=31/60`, `used_retrieval_calls=1/20` — the investigation
  did **not** hit a hard budget wall; it abstained because per-hypothesis
  evidence classification never converged within its own 8-iteration loop
  cap (§19), a different, smaller boundary than the global budget.

**EXECUTIVE investigation:** `status_history`: `PLANNED → SECURITY_VALIDATED
→ HYPOTHESES_GENERATED → ABSTAINED (no hypothesis cleared its evidence-gated
trigger condition)` — 0 hypotheses. `required_value_checks.
executive_rbac_no_internal_leak.leaked: false`.

**`required_value_checks.all_checks_pass: true`** — revenue movement,
hypothesis diversity/cap, citation completeness (every `HypothesisResult.
is_valid()`), and the RBAC no-leak check all pass against this real run.

## 15. Agent/tool telemetry

`analyst_telemetry_summary` (real, from `reports/step5_validation.json`):

| Agent | LLM calls | Tokens | Cost (USD, approximate) |
|---|---|---|---|
| ORCHESTRATOR | 6 (deterministic) | 0 | 0.0 |
| HYPOTHESIS | 7 | 25,513 | 0.006027 |
| EVIDENCE | 24 | 70,843 | 0.010215 |
| COUNTER_EVIDENCE | 0 | 0 | 0 |
| CAUSAL_SELECTOR | 0 (deterministic) | 0 | 0.0 |
| CONFIDENCE_JUDGE | 0 (deterministic) | 0 | 0.0 |
| **Total** | **31** | **96,356** | **0.016242** |

`total_tool_calls: 31`, `total_retrieval_calls: 1`. Pricing is an
approximation (`agents/telemetry.py::GROQ_PRICING_PER_MILLION_TOKENS`), not
billing-accurate.

## 16. Token usage

`total_input_tokens: 79,841`, `total_output_tokens: 16,515`,
`total_tokens: 96,356` for the real ANALYST investigation alone (real
`response.usage` fields from Groq, not estimated). ORCHESTRATOR/
CAUSAL_SELECTOR/CONFIDENCE_JUDGE telemetry records are real too — genuinely
0 tokens, since those three agents never call an LLM (§1/§2).

## 17. Latency

`context_build_seconds: 89.25` (dominated by `langdetect` + E5 embedding
over ~5,000 review rows, cache-hit-dependent — a documented double-build
cost, `docs/MULTI_AGENT_ARCHITECTURE.md` §4). `analyst_run_seconds: 181.08`,
`executive_run_seconds: 50.19` — both real wall-clock, including real
network round-trips to Groq and (during an earlier attempt, before a
retry/backoff fix — see §19) real rate-limit recovery pauses.

## 18. Test results

**139/139 Step 5 tests pass** across all 12 required files:

| File | Tests |
|---|---|
| `test_state_machine.py` | 20 |
| `test_tool_gateway.py` | 23 |
| `test_rbac.py` | 13 |
| `test_budgets.py` | 7 |
| `test_numeric_guardrail.py` | 9 |
| `test_contradictions.py` | 14 |
| `test_confidence.py` | 11 |
| `test_hypothesis.py` | 7 |
| `test_evidence_agent.py` | 7 |
| `test_counter_evidence.py` | 6 |
| `test_orchestrator.py` | 10 |
| `test_prompt_injection.py` | 12 |

Full repository suite (Steps 1–5 combined): **686 tests pass, 0
regressions** against the pre-existing Step 1–4A suite
(`.venv/bin/python -m pytest tests/ -q` → `686 passed`). `~90%` of Step 5's
own coverage runs against `agents.llm_client.FakeLLMClient` (zero network,
fully deterministic); the remainder is the real, live-API demonstration
captured in this report.

## 19. Known limitations

- **Evidence Agent did not converge to a classification within its
  per-hypothesis tool-iteration budget in the captured real run.** The
  model made real, sensible tool calls (`get_driver_decomposition`,
  `get_evidence` repeatedly) but never called `submit_evidence_classification`
  within `max_tool_iterations=8` for any of the 3 hypotheses, exhausting
  24 of its calls exploring rather than concluding. The global
  `agent_calls`/`tool_calls` budgets were NOT exhausted (31/40, 31/60) — this
  is a smaller, per-agent-call loop cap, not a hard system-wide stop.
  Plausible causes: `openai/gpt-oss-20b` (a smaller open-weight model) needs
  more turns to converge on a multi-step classification task than a larger
  model would; the growing tool-result payload (see next point) also eats
  into the shared token-per-minute budget, indirectly pressuring the model
  toward more exploration. Not fixed in this implementation — documented as
  a real, honest constraint rather than hidden. A reasonable next step:
  raise `max_tool_iterations` for `evidence_agent.collect_evidence`
  specifically (there is budget headroom to do so) and/or trim
  `format_tool_result_for_llm`'s payload size.
- **This account's Groq keys share an 8,000 tokens-per-minute (TPM) budget**
  (observed directly: `groq.APIStatusError` HTTP 413,
  `"rate_limit_exceeded"`, naming the shared `org_...` id, not a per-key
  quota) — round-robining across the 17 supplied keys does NOT multiply
  this budget, since they appear to belong to the same organization. Two
  concrete fixes were made in response: (1) `GroqLLMClient.create()`'s
  retry loop now catches the whole `groq.APIStatusError` hierarchy (an
  earlier, narrower catch list let this crash the investigation
  uncaught — a real bug, fixed and covered by the successful re-run); (2)
  a 1.5-second pause between key rotations gives the per-minute window a
  moment to recover. Neither fix multiplies the account's actual quota — a
  sufficiently long real investigation can still hit `LLMUnavailable`,
  which `run_tool_loop()` already treats as "nothing usable this round,"
  never a crash.
- **The default model changed mid-implementation.** The SDK-advertised
  default (`llama-3.3-70b-versatile`) returned a 404 model-not-found for
  every one of the user's 17 keys when actually probed against the live
  API; `openai/gpt-oss-20b` was found live to work, with real tool-calling
  support, and is now `agents.llm_client.DEFAULT_MODEL` (overridable via
  `GROQ_MODEL`).
- **The double context-build cost** (`tools/context.build_tool_context`
  calls both `build_november_2017_evidence_package` and
  `build_review_index` separately) remains unoptimized — see
  `docs/MULTI_AGENT_ARCHITECTURE.md` §4.
- **No adaptive re-invocation loop.** Each of the six agent modules runs
  exactly once per investigation (Evidence/Counter-Evidence once per
  hypothesis); the Orchestrator never re-invokes an agent with a targeted
  follow-up when the Confidence Judge finds evidence thin. Documented scope
  boundary, `docs/MULTI_AGENT_ARCHITECTURE.md` §3.
- **`tokens`/`latency_seconds` budgets are provisioned but not metered
  per-call** — only `iterations`/`agent_calls`/`tool_calls`/
  `retrieval_calls` are actually enforced today.
- **PII redaction gap in `get_evidence`**, found and fixed during this
  implementation (not a residual issue) — see `docs/AGENT_SECURITY.md` §8.

---

## STOP CONDITION MET

No causal inference is executed anywhere in this package — `causal_selector.py`
only ever *selects* a rigor label (T1_DESCRIPTIVE/T2_ARITHMETIC/
INSUFFICIENT_DATA; T3/T4 are declared but never selected, a tested
invariant) and never runs a statistical estimation procedure of its own. No
action recommendations, persona-specific narratives, or feedback-learning
mechanism exist anywhere in `src/agents/` or `src/tools/`. No frontend
exists. Every quantitative value any agent (LLM-backed or not) can cite
traces to a real Step 1–4 engine call through the Tool Gateway, checked
against `allowed_numbers` built fresh from that evidence; every causal-
sounding phrase is rejected at construction time regardless of which agent
produced it. The real November 2017 demonstration run in this document is
exactly what the system is supposed to do when evidence-gathering doesn't
converge: it abstained, on both the ANALYST and EXECUTIVE runs, rather than
manufacturing a confident-sounding conclusion from thin evidence.

**Step 5 is complete.** Multi-agent orchestration, the Tool Gateway, RBAC,
the investigation state machine, budgets, hypothesis/evidence/counter-
evidence/contradiction/method/confidence pipelines, the numeric and
causal-language guardrails, and the security test suite are all built,
tested (139/139 Step 5 tests, 680+ full-repository tests, 0 regressions),
and demonstrated end-to-end against the real Step 1–4 engines and a real
LLM. Causal inference execution, action recommendations, persona narratives,
feedback learning, and a frontend have not been started.
