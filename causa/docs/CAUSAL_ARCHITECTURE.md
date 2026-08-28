# Causal Architecture (Step 6)

```
CausalHypothesis
      |
      v
eligibility.check_eligibility()      -- 12 checks, always run, always in order
      |
      v
  CAUSAL_INELIGIBLE? --yes--> CausalResult(CAUSAL_REJECTED, T1, method=NONE)
      | no
      v
method_selector.select_method()      -- deterministic, explainable, no LLM
      |
      v
dispatch: PVM | DIFFERENCE_IN_DIFFERENCES | INTERRUPTED_TIME_SERIES
        | CAUSAL_IMPACT | DESCRIPTIVE_ASSOCIATION | EXPERIMENTAL_RESULT | NONE
      |
      v
language_gate.enforce_language_gate()  -- every free-text field, unconditionally
      |
      v
(optional) engine._extend_graph()      -- evidence.graph integration
      |
      v
CausalResult
```

Non-negotiable principle (task's own words): **LLM proposes hypotheses.
Deterministic/statistical systems test them. LLM cannot declare causality.**
No file under `src/causal/` imports an LLM client anywhere
(`tests/test_provenance.py::test_no_module_in_causal_package_imports_llm_client`
AST-scans every module in the package). `CausalHypothesis` objects are either
hand-authored (see `scripts/step6_causal_validation.py`) or produced by a
thin, best-effort bridge from a Step 5 `agents.models.Hypothesis`
(`causal.engine.causal_hypothesis_from_step5`) — Step 6 never runs its own
hypothesis-generating agent.

## 1. Reuse, never duplicate

| Reused from | What Step 6 calls | Never |
|---|---|---|
| Step 3D (`drivers.engine`) | `decompose()`, unmodified | recomputes PVM itself |
| Step 3B (`kpi.engine`) | `KPIEngine.compute()` / `compare_periods()` | bypasses `query_planner`'s governance |
| Step 4 (`evidence.structured_adapter`) | `driver_decomposition_result_to_evidence_bundle()` | fabricates an evidence_id |
| Step 4 (`evidence.graph`) | `add_edge()`, `add_kpi_node()` | builds a second, parallel graph library |
| Step 5 (`agents.models`) | `UNSUPPORTED_CAUSAL_PATTERN`, `assert_no_unsupported_causal_language` | defines a third causal-language regex |

## 2. Three tier enums — never conflated

| Enum | Owner | Question it answers | Populated values |
|---|---|---|---|
| `evidence.models.EvidenceTier` | Step 4 | How was **one evidence item** produced? | T1_DESCRIPTIVE, T2_ARITHMETIC, T3_STATISTICAL (T4/T5 reserved) |
| `agents.models.AnalyticalMethod` | Step 5 | What rigor label can the LLM-driven pipeline attach to a hypothesis' **support**, given only evidence tiers? | T1_DESCRIPTIVE, T2_ARITHMETIC, INSUFFICIENT_DATA (T3/T4 declared, never selected) |
| `causal.models.CausalTier` | Step 6 | What is the strongest tier a **specific hypothesis + specific method run** can defensibly support, after eligibility + diagnostics? | T1_DESCRIPTIVE, T2_ARITHMETIC, T3_QUASI_EXPERIMENTAL, T4_EXPERIMENTAL |

A DiD run can compute a T3-shaped estimate that is capped back down to T1
because parallel trends failed — a judgment neither of the other two enums
has any vocabulary for, which is why `CausalTier` is its own type rather than
a reuse of either.

## 3. `causal_hypothesis_from_step5` — an optional bridge, not a dependency

`engine.causal_hypothesis_from_step5(step5_hypothesis, investigation_state)`
maps a Step 5 `Hypothesis.driver`/`.dimension` onto a `CausalHypothesis`'s
treatment/outcome/period fields. It returns `None` (never raises) when the
mapping can't produce a structurally valid hypothesis. This is **not**
load-bearing for the November 2017 validation: the real captured
`reports/step5_validation.json` has the ANALYST run `ABSTAINED` with all
three hypotheses at `method=INSUFFICIENT_DATA`/`evidence_ids=[]`
(`STEP5_VALIDATION.md` §14) — there is nothing usable to bridge from today.
`scripts/step6_causal_validation.py` instead builds its four hypotheses
directly from real Step 3B/3D/4 evidence.

## 4. Module dependency graph

```
models.py  (no dependencies within src/causal/)
   |
   +-- eligibility.py   -> drivers.engine, kpi.engine/models/query_planner/semantic_registry
   +-- diagnostics.py   -> models.py only (numpy/math)
   +-- language_gate.py -> agents.models only
   |
   +-- method_selector.py -> causal_impact.py, models.py
   +-- did.py              -> diagnostics.py, models.py
   +-- interrupted_series.py -> diagnostics.py, models.py
   +-- causal_impact.py    -> diagnostics.py, models.py
   |
   +-- engine.py -> everything above, plus drivers.engine.decompose,
                    evidence.graph, evidence.models, evidence.structured_adapter
```

No circular imports: `diagnostics.py` owns the one function
(`compute_abstention_status`) every method wrapper needs, so `did.py` /
`interrupted_series.py` / `causal_impact.py` never import `engine.py`.

## 5. Known scope limits (honestly documented, not hidden)

- `did.py`'s parallel-trends diagnostic needs a real multi-period pre-trend
  series (`DiDInputs.pre_period_series`) to do more than fail by default —
  `engine._build_did_inputs` does not yet assemble one from canonical data
  (a single pre/post pair only), so any real DiD run through `engine.py`
  today reports the diagnostic as failed for lack of a trend to check, not
  because a real trend diverged. A future extension: build the same monthly
  panel `_build_its_inputs` already constructs, grouped by treatment/control
  value, and pass it through.
- `causal_impact.py` has no installed Bayesian structural time-series
  package to call into (`requirements.txt` carries none) — every real run
  takes the `METHOD_UNAVAILABLE` branch. See `docs/CAUSAL_METHOD_SELECTION.md`.
- No adaptive re-invocation: `run_causal_analysis` is called once per
  hypothesis, exactly like Step 5's agent modules.

## 6. November 2017 worked example (real data, `scripts/step6_causal_validation.py`)

| Hypothesis | Eligibility verdict | Method selected | Tier | `causal_claim_allowed` |
|---|---|---|---|---|
| C1 order-volume | PARTIALLY_ELIGIBLE (Black Friday confound, soft) | PVM | T2_ARITHMETIC | False |
| C2 category-growth | INELIGIBLE (`treatment_precedes_outcome`, `sufficient_pre_period`) | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | False |
| C3 delivery/review | INELIGIBLE (`control_variation`) | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | False |
| C4 geographic | INELIGIBLE (`treatment_precedes_outcome`, `sufficient_pre_period`) | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | False |

See `docs/CAUSAL_GOVERNANCE.md` §4 for why this table is a **success**, not a
shortfall.
