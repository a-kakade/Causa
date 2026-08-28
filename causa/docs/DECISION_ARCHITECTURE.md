# Decision Architecture (Step 7)

```
DriverSignal
      |
      v
ontology.DecisionOntology.load()             -- config/decision_ontology.yaml, validated
      |
      v
candidate_generator.generate_candidates()     -- deterministic templates; optional LLM phrasing only
      |
      v
[per candidate] impact_estimator.estimate_impact()       -- effect x population x confidence; "unknown" if data missing
      |
      v
[per candidate] constraint_engine.evaluate_constraints()  -- budget/capacity/inventory/geography/decision_rights
      |
      v
[per candidate] confidence_engine.compute_confidence()    -- weighted sum, config-driven weights
      |
      v
[per candidate] scoring.compute_controllability/effort/priority()
      |
      v
ranking.run_decision_pipeline()   -- assigns tier, sorts, builds ranking_explanation
      |
      v
[per executable] monitoring.build_monitoring_plan()
      |
      v
(optional) explanation.narrate()  -- LLM verbalization ONLY, guardrailed
      |
      v
DecisionResult
```

Non-negotiable principle (this step's own analog of Step 5/6's rule):
**structured engines compute numbers, confidence, priority, constraints, and
ownership. An LLM may only ever PHRASE a candidate action or VERBALIZE an
already-computed result — never decide what the numbers are.** No file under
`src/decision/` imports an LLM client except `candidate_generator.py`
(optional phrasing) and `explanation.py` (optional narrative)
(`tests/test_decision_provenance.py::test_no_module_in_decision_package_imports_llm_client_except_two_allowed`
AST-scans every module in the package). `DriverSignal` objects are either
hand-authored (see `scripts/step7_decision_engine_demo.py`) or produced by a
thin, best-effort bridge from a Step 6 `causal.models.CausalResult` or a
Step 5 `agents.models.HypothesisResult` (`decision.bridge.py`) — Step 7 never
runs its own driver-detecting agent; that is Steps 3D/5/6's job.

## 1. Reuse, never duplicate

| Reused from | What Step 7 calls | Never |
|---|---|---|
| Step 5 (`agents.models`) | `assert_no_unsupported_causal_language`, `UNSUPPORTED_CAUSAL_PATTERN` | defines a third causal-language regex |
| Step 5 (`agents.models`) | `build_allowed_numbers()`, `validate_numeric_claims()` | lets an LLM narrative cite an unverified number |
| Step 5 (`agents.llm_client`) | `LLMClient` protocol, `FakeLLMClient` | writes a new LLM provider seam or mocks business logic instead of the LLM |
| Step 6 (`causal.models`) | `CausalResult.causal_claim_allowed`, `CausalResult.estimate` | recomputes a causal estimate itself |
| Step 3A (`kpi.semantic_registry`) | the load/validate/read-only-accessor pattern (`SemanticRegistry`) | invents a different config-loading convention |
| Step 4 (`evidence.models`) | pre-reserved `ACTION`/`ACTION_RESULT` node types, `RECOMMENDS`/`HAS_CONFIDENCE` edge types | defines a parallel graph vocabulary |

## 2. `action_justified_by_evidence` vs. `causal_claim_allowed`

| Field | Owner | Question it answers |
|---|---|---|
| `causal.models.CausalResult.causal_claim_allowed` | Step 6 | Can **this specific hypothesis + method run** defensibly support a causal claim? |
| `decision.models.ActionRecommendation.action_justified_by_evidence` | Step 7 | Does **this recommendation's originating signal** trace back to a `CausalResult` that itself earned `causal_claim_allowed=True`? |

Both are hardcoded boolean fields, never a soft convention or an LLM's
self-report. `action_justified_by_evidence` is strictly derived —
`decision.bridge.driver_signal_from_causal_result` echoes the upstream
`CausalResult.causal_claim_allowed` onto `DriverSignal.causal_claim_allowed`,
and `candidate_generator.generate_candidates` sets the recommendation's field
to `True` only when `DriverSignal.source == "STEP6_CAUSAL_RESULT"` **and**
that echoed value is `True`. A hand-authored `DriverSignal` (`source="MANUAL"`)
— including both demo scenarios in `STEP7_VALIDATION.md` — always yields
`action_justified_by_evidence=False`. This is not a defect: a recommendation
backed only by a T1/T2 descriptive/arithmetic finding, or by no causal
analysis at all, is still a legitimate, well-scored recommendation — it
simply cannot claim causal justification for its expected impact.

## 3. Two guardrailed LLM boundaries

| Function | May generate | May NOT generate | Fallback on any failure |
|---|---|---|---|
| `candidate_generator._llm_rephrase()` | A natural-language phrasing of an already-templated action sentence | Any number not already present in the facts handed to it; any causal claim | The raw deterministic template string |
| `explanation.narrate()` | A prose narrative of an already-computed `DecisionResult` | Any number, confidence, priority, constraint, owner, or KPI target not already present in the `DecisionResult` | The deterministic template narrative (`_deterministic_narrative()`) |

Both functions accept `llm_client=None` and are fully exercised in that mode
by every test and the demo script — the pipeline's determinism guarantee
never depends on an LLM being reachable.

## 4. Never fabricate: the `is_estimable` / `"unknown"` discipline

`impact_estimator.estimate_impact()` sets `ExpectedImpact.is_estimable=False`
whenever `DriverSignal.historical_estimated_effect`,
`.addressable_population`, or `.driver_confidence` is `None` — the missing
field's *source* label is also explicitly set to `"UNKNOWN"`
(`decision.models.DataSource.UNKNOWN`), never silently defaulted to zero.
`scoring.compute_priority()` treats a `None`/not-estimable impact as `0.0`
for ranking purposes only — the candidate still appears, ranked low, with
`ranking_explanation` explicitly noting the missing data, rather than being
silently dropped or given a fabricated positive impact.
`monitoring.build_monitoring_plan()` follows the identical discipline:
`MonitoringTarget.target` stays the literal sentinel string `"unknown"`
unless a real baseline+effect combination is computable.

## 5. Configuration

| File | Owns | Loader |
|---|---|---|
| `config/decision_ontology.yaml` | Driver → category → lever → action_type → owners → constraints → monitoring KPIs (the business vocabulary) | `decision.ontology.DecisionOntology` |
| `config/decision_scoring.yaml` | Confidence weights, effort/controllability/action-link-strength tier tables, prioritization formula string + divide-by-zero floor, constraint thresholds, default monitoring window (the numeric machinery) | `decision.ontology.DecisionScoringConfig` |

Adding a new driver, lever, or action type is a pure YAML addition to
`decision_ontology.yaml` — no code change required, as long as its
`action_id` is globally unique and its tier/link-strength values are one of
the tiers `decision_scoring.yaml` declares. Changing a weight or threshold
in `decision_scoring.yaml` changes computed scores; it never changes what an
action *is* — that separation is deliberate (task's own instruction: keep
business logic outside prompts, keep scoring configurable, keep the vocabulary
config-driven).
