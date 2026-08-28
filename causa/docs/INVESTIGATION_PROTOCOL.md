# INVESTIGATION_PROTOCOL — Step 5

## 1. State machine

```
PLANNED
  ↓
SECURITY_VALIDATED
  ↓
HYPOTHESES_GENERATED
  ↓
EVIDENCE_COLLECTION
  ↓
COUNTER_EVIDENCE
  ↓
CONTRADICTION_ANALYSIS
  ↓
METHOD_SELECTION
  ↓
CONFIDENCE_EVALUATION
  ↓
COMPLETED
```

Terminal alternatives: `ABSTAINED`, `NEEDS_CLARIFICATION`, `BUDGET_EXCEEDED`,
`SECURITY_BLOCKED`. `ABSTAINED`/`BUDGET_EXCEEDED`/`SECURITY_BLOCKED` are
reachable from every non-terminal state; `NEEDS_CLARIFICATION` only from
`PLANNED` (an unresolvable `kpi_id`/`requester_role`) and
`CONFIDENCE_EVALUATION` (the Confidence Judge itself can output
`NEEDS_CLARIFICATION`). Every transition goes through
`agents.state_machine.transition()`, which consults a fixed
`ALLOWED_TRANSITIONS` table and raises `InvalidTransitionError` otherwise —
"invalid transitions must fail" is a runtime guarantee, not a convention
(`tests/test_state_machine.py` exercises every adjacent and non-adjacent
pair). No module outside `state_machine.py` ever writes `state.status`
directly (AST-scanned).

## 2. Budgets

`agents.models.Budgets`: `max_iterations`, `max_agent_calls`, `max_tool_calls`,
`max_retrieval_calls`, `max_tokens`, `max_latency_seconds`, each with its own
`used_*` counter. `Budgets.increment(name)` raises `BudgetExceeded` when the
limit is already reached.

Two different consequences, by design (see `docs/MULTI_AGENT_ARCHITECTURE.md`
for the reasoning):

- **`agent_calls`** (an LLM round-trip) exhausting propagates out of
  `agents.llm_client.run_tool_loop()`, through the calling agent module,
  into `orchestrator.py`'s per-stage wrapper — which transitions the whole
  investigation to `BUDGET_EXCEEDED`. This is the "never continue
  indefinitely" stop task §9 asks for.
- **`tool_calls`/`retrieval_calls`** (one governed tool call) exhausting is
  caught inside `tools/gateway.call_tool()` and returned as a normal
  `ToolCallResult(ok=False)` — the calling agent (or model) can adapt (e.g.
  submit with whatever evidence it already has) rather than the whole
  investigation halting over one denied call.

`iterations` is charged once per pipeline stage by `orchestrator._stage()`.
`tokens`/`latency_seconds` are provisioned but not currently metered per-call
(a documented limitation, see `STEP5_VALIDATION.md` §19).

## 3. The five pipelines

1. **Hypothesis generation** (`agents/hypothesis_agent.py`) — LLM-backed. The
   model gathers PVM/segment/concurrent-KPI/review evidence via its
   allowlisted tools, then submits 3–5 hypotheses, each with `driver`,
   `dimension`, `mechanism`, a hedged `statement`, `expected_evidence`, and
   `falsification_evidence`. Duplicate `(driver, dimension)` pairs are
   deduplicated after submission; causal-language or numeric-guardrail
   violations drop that one hypothesis, never the whole batch; results are
   capped at 5.
2. **Evidence collection** (`agents/evidence_agent.py`) — LLM-backed, once
   per hypothesis. The model requests additional evidence and classifies
   each item SUPPORTS/CONTRADICTS/CONTEXT/INSUFFICIENT. A deterministic
   floor (`_apply_floor`) can only ever downgrade that classification: low
   confidence, a sample size below 15 (reused from Step 4's own threshold),
   a `BLOCKED` security status, or `CONCURRENT_KPI` evidence type (always
   forced `CONTEXT`) override whatever the model said.
3. **Counter-evidence** (`agents/counter_evidence_agent.py`, LLM half) —
   LLM-backed, once per hypothesis that has at least one `SUPPORTS` item. The
   model actively searches for unaffected segments, opposite-direction
   segments, weak sample sizes, temporal mismatches, and evidence-quality
   problems, then submits a `CounterEvidenceReport`.
4. **Contradiction analysis** (`agents/counter_evidence_agent.py`,
   deterministic half) — pure re-derivation, no new tool calls.
   `score_contradiction_severity()` combines real `CONTRADICTS`-classified
   evidence counts with a real two-proportion z-test where one exists (Step
   4's `evidence.graph.check_low_score_rate_contradiction`, reused
   unmodified) into `NONE`/`WEAK`/`MODERATE`/`STRONG`. The model's own
   self-reported `contradiction_level` is recorded but never used for this
   score. Every `ContradictionRecord.unresolved` is always `True`.
5. **Method selection + confidence** (`agents/causal_selector.py`,
   `agents/confidence_judge.py`) — both 100% deterministic, no LLM call.
   `causal_selector` maps the evidence-tier mix of `SUPPORTS` items to
   `T1_DESCRIPTIVE`/`T2_ARITHMETIC`/`INSUFFICIENT_DATA` (never
   `T3_QUASI_EXPERIMENTAL`/`T4_EXPERIMENTAL` — this dataset offers no
   natural experiment) and downgrades one rank on `STRONG` contradiction.
   `confidence_judge` computes a weighted score (completeness, source
   reliability, freshness, historical sufficiency, minus contradiction and
   retrieval-insufficiency penalties) into `HIGH`/`MEDIUM`/`LOW`/`ABSTAIN`/
   `NEEDS_CLARIFICATION`, with hard caps (`STRONG` contradiction never
   reaches `HIGH`; zero `SUPPORTS` or `INSUFFICIENT_DATA` method always
   `ABSTAIN`s). The investigation-level confidence is the **worst** result
   across all hypotheses.

## 4. Distinguishing FACT / DECOMPOSITION / HYPOTHESIS / CAUSAL CLAIM (task §18)

| Kind | Example | Produced by |
|---|---|---|
| FACT | "Revenue increased by R$346,051.94." | `compare_kpi` → `KPI_MOVEMENT` evidence (Step 3B, T1_DESCRIPTIVE) |
| DECOMPOSITION | "Volume mathematically accounts for +R$417,227.65." | `get_driver_decomposition` → `DRIVER_CONTRIBUTION` evidence (Step 3D, T2_ARITHMETIC, `causal_claim=False` hardcoded) |
| HYPOTHESIS | "Delivery deterioration may be associated with declining review scores." | `hypothesis_agent.py`, hedged language enforced at construction |
| CAUSAL CLAIM | "Delivery deterioration caused the decline." | **Never produced.** `agents.models.assert_no_unsupported_causal_language()` rejects this at construction time for every agent-generated field, and `causal_selector.py` never selects a method tier that would license such a conclusion (T3/T4 are never selected — see §3.5). |

## 5. Worked November 2017 walkthrough

See `STEP5_VALIDATION.md` §14 for the actual end-to-end trace (real numbers,
real hypotheses, real confidence result) from
`scripts/step5_investigate_november_2017.py`.
