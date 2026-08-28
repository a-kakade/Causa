# STEP 7 VALIDATION — Decision & Action Intelligence Engine

Every structured number in this document is copied directly from
`reports/step7_validation.json`, written by `scripts/step7_decision_engine_demo.py`
from a real run of the governed decision pipeline against two hand-authored
`DriverSignal` inputs (delivery_delay per the task's own exact demo values;
aov_decline to prove ontology extensibility). Nothing here is fabricated or
hand-edited into the JSON.

Reproduce:

```bash
python -m pytest tests/test_decision_ontology.py tests/test_candidate_generator.py \
    tests/test_constraint_engine.py tests/test_impact_estimator.py \
    tests/test_confidence_engine.py tests/test_scoring.py tests/test_ranking.py \
    tests/test_monitoring.py tests/test_decision_bridge.py tests/test_decision_explanation.py \
    tests/test_decision_end_to_end.py tests/test_decision_provenance.py -q
python scripts/step7_decision_engine_demo.py
```

---

## 1. Architecture

```
DriverSignal (hand-authored, or bridged from Step 5/6 via decision.bridge)
      |
      v
ontology.DecisionOntology.load()          -- config/decision_ontology.yaml, validated
      |
      v
candidate_generator.generate_candidates()  -- deterministic templates; optional LLM phrasing only
      |
      v
[per candidate] impact_estimator.estimate_impact()      -- effect x population x confidence
      |
      v
[per candidate] constraint_engine.evaluate_constraints() -- budget/capacity/inventory/geography/decision_rights
      |
      v
[per candidate] confidence_engine.compute_confidence()   -- weighted sum, config-driven weights
      |
      v
[per candidate] scoring.compute_controllability/effort/priority()
      |
      v
ranking.run_decision_pipeline()  -- sorts, splits top/alternatives/conditional/blocked, builds ranking_explanation
      |
      v
[per executable] monitoring.build_monitoring_plan()
      |
      v
(optional) explanation.narrate()  -- LLM verbalization ONLY, guardrailed; deterministic fallback always available
      |
      v
DecisionResult
```

No module in `src/decision/` imports an LLM client except `candidate_generator.py`
(optional phrasing) and `explanation.py` (optional narrative) — mechanically
verified by an AST scan across every module in the package
(`tests/test_decision_provenance.py::test_no_module_in_decision_package_imports_llm_client_except_two_allowed`).
The entire pipeline runs deterministically end-to-end with `llm_client=None`
for every test and this demo run. Full rationale: `docs/DECISION_ARCHITECTURE.md`.

## 2. Reuse, never duplicate

- Causal-language guard: `agents.models.assert_no_unsupported_causal_language`/`UNSUPPORTED_CAUSAL_PATTERN` — Step 5, unmodified, applied to `ActionRecommendation.possible_action`/`rationale`.
- Numeric guardrail: `agents.models.build_allowed_numbers()`/`validate_numeric_claims()` — Step 5, unmodified, reused by both `candidate_generator._llm_rephrase()` and `explanation.narrate()`'s optional LLM paths.
- LLM provider seam: `agents.llm_client.LLMClient`/`FakeLLMClient` — Step 5, unmodified. Every LLM-touching test uses `FakeLLMClient` ("mock the LLM, never the business logic").
- Config-loader convention: `kpi.semantic_registry.SemanticRegistry` — Step 3A's load/validate/read-only-accessor pattern, replicated structurally by `decision.ontology.DecisionOntology`/`DecisionScoringConfig`.
- Evidence graph vocabulary: `evidence.models`'s pre-reserved `ACTION`/`ACTION_RESULT` node types and `RECOMMENDS`/`HAS_CONFIDENCE` edge types — Step 4, unmodified, exactly the vocabulary this step is the first to populate.

## 3. The `action_justified_by_evidence` gate

`ActionRecommendation.action_justified_by_evidence` is this package's analog
of `causal.models.CausalResult.causal_claim_allowed` — a hardcoded boolean
field, never a soft convention. It is `True` only when the originating
`DriverSignal.source == "STEP6_CAUSAL_RESULT"` **and** the bridged
`CausalResult.causal_claim_allowed` was itself `True`
(`decision.bridge.driver_signal_from_causal_result` echoes this field
directly; `candidate_generator.generate_candidates` sets it on every
candidate it builds). A recommendation backed only by a T1/T2
descriptive/arithmetic finding — or, as in both demo scenarios below, a
hand-authored `DriverSignal` with `source="MANUAL"` — is not thereby
invalid; it simply cannot claim causal justification, exactly the
distinction Step 6 draws for `CausalResult` itself. Both demo scenarios
report `action_justified_by_evidence: false` for this reason
(`tests/test_decision_end_to_end.py::test_action_justified_by_evidence_false_for_manual_driver_signal`).

## 4. The business ontology

`config/decision_ontology.yaml` declares 2 drivers, 4 controllable levers
under delivery_delay and 3 under aov_decline, 5 and 4 action_types
respectively (9 `action_id`s total, all globally unique —
`tests/test_decision_ontology.py::test_all_action_ids_globally_unique`).
Adding a new driver is a pure YAML addition — no code change required
(`unsupported_driver_policy: "abstain"` means an unmapped driver returns
zero candidates and records the reason in `DecisionResult.pipeline_trace`,
never a generic fallback action —
`tests/test_ranking.py::test_unsupported_driver_returns_empty_result_not_generic_fallback`).

## 5. Delivery Delay demo (real run, task's own exact input values)

Input `DriverSignal`: `observed_change_pct=-0.08`, `addressable_population=12500`,
`historical_estimated_effect=0.06`, `driver_confidence=0.78`,
`business_context={"budget_available": true, "operational_capacity_available": true}`.

**5 candidate actions generated, evaluated, and ranked** —
`required_value_checks.multiple_candidates_generated_delivery_delay: true`.

| Tier | recommendation_id | priority_score |
|---|---|---|
| TOP | `rec_delivery_delay_prioritize_high_value_customers` | **1679.5350** |
| ALTERNATIVE | `rec_delivery_delay_expedite_high_risk_shipments` | 719.199 |
| CONDITIONAL | `rec_delivery_delay_tighten_seller_dispatch_sla` | blocked by `decision_rights` (WARNING — no `authorized_owner_roles` supplied) |
| CONDITIONAL | `rec_delivery_delay_move_inventory_to_regional_warehouses` | blocked by `inventory`, `geography` (WARNING — neither supplied) |
| CONDITIONAL | `rec_delivery_delay_reroute_to_faster_carrier` | blocked by `geography` (WARNING — not supplied) |

**Top recommendation, in full**:
- Possible action: *"Prioritize high-value customer shipments for on_time_delivery_rate (2017-11)"* — a concrete, quantified action, never the literal string "improve logistics" (`required_value_checks.delivery_delay.actual.not_a_generic_string: true`).
- Controllable lever: `shipment_prioritization`. Owner: `Operations Manager`.
- Expected impact: `estimated_effect=0.06`, `addressable_population=12500`, `confidence=0.78` →
  `calculated_impact = 0.06 * 12500 * 0.78 = 585.0` — the exact task formula, computed, never fabricated.
- Confidence breakdown (weighted sum, `config/decision_scoring.yaml` weights): `driver_confidence=0.78` (w=0.35) + `data_quality=0.1` (w=0.25, no `data_quality` label supplied → `UNKNOWN` floor) + `historical_support=1.0` (w=0.25, real `HISTORICAL_ESTIMATE` source) + `action_link_strength=0.6` (w=0.15, `MODERATE` tier) = **`confidence_score=0.638`**.
- Controllability: `0.9` (`HIGH` tier). Effort: `0.2` (`LOW` tier).
- Priority: `impact(585.0) * confidence(0.638) * controllability(0.9) / effort(0.2)` = **`1679.535`**.
- Constraints: `operational_capacity` → `PASS`.
- Monitor: `on_time_delivery_rate` (target: increase by ~0.06 within 8 weeks, warning threshold 0.03).

## 6. AOV Decline demo (proves ontology extensibility)

Input `DriverSignal`: `observed_change_pct=-0.05`, `addressable_population=85000`,
`historical_estimated_effect=12.5` (currency units), `driver_confidence=0.72`,
`business_context={"budget_available": true, "inventory_units_available": 5000,
"authorized_owner_roles": ["Pricing Manager", "Commercial Manager", "Product Manager"]}`.

**4 candidate actions generated** (`required_value_checks.multiple_candidates_generated_aov_decline: true`).
Top recommendation: *"Adjust pricing on selected SKUs within aov (2017-11)"* —
owner `Pricing Manager`, `priority_score=2278935.0`, both `budget` and
`decision_rights` constraints `PASS` (this scenario deliberately supplies
`authorized_owner_roles`, unlike the delivery_delay scenario, showing both
the WARNING-on-missing and PASS-on-supplied paths of the same constraint
checker in one demo run).

## 7. What this does NOT do (honest scope)

- **No live budget/inventory/capacity system integration.** `business_context`
  is always an explicit caller-supplied dict (`decision.models.DriverSignal.business_context`)
  — this package never queries a real ERP/inventory system. A missing key is
  always a `WARNING`, never a silent `PASS`.
- **No swappable prioritization formula interpreter.** `scoring.compute_priority()`
  hardcodes the single Python expression `impact * confidence * controllability / effort`;
  `config/decision_scoring.yaml`'s `prioritization.formula` string is echoed
  into `ScoreBreakdown.priority_formula` for audit purposes only. Supporting
  an arbitrary config-defined formula is documented future work — it would
  need a real expression parser to avoid an `eval()` security smell, which is
  over-engineering for this MVP.
- **No API server or frontend**, by explicit user decision during planning:
  no other step (1–6) in this repository has one, and the task's own
  "production-lean, not over-engineered" instruction favors staying
  consistent with that. The engine is Python-callable
  (`decision.ranking.run_decision_pipeline()`) plus this demo script,
  matching every prior step exactly.
- **No CausalImpact-style / live Step 5-6 pipeline run in this demo.**
  `decision.bridge.py`'s two converters (`driver_signal_from_causal_result`,
  `driver_signal_from_hypothesis_result`) are unit-tested against synthetic
  `CausalResult`/`HypothesisResult` objects (`tests/test_decision_bridge.py`)
  but not exercised against a live November 2017 Step 5/6 run in this demo —
  both required demo scenarios use hand-authored, `source="MANUAL"`
  `DriverSignal`s per the task's own exact specified values, matching how
  `scripts/step6_causal_validation.py` also hand-authors its required
  hypotheses rather than depending on Step 5's live (and sometimes
  `ABSTAIN`ed) output.

## 8. Test results

113/113 Step 7 tests pass across all 12 new test files. Full repository
regression check: baseline (Steps 1–6, excluding Step 7) shows 453 passed
before Step 7 was added; adding Step 7's 113 tests brings the total to 566
passed with **zero new failures** — every pre-existing failure/error in this
environment (`data/processed/*.parquet` not built here) is identical with or
without Step 7 present.
