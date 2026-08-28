# STEP 6 VALIDATION — Causal Analysis and Evidence-Tier Engine

Every structured number in this document is copied directly from
`reports/step6_validation.json`, written by `scripts/step6_causal_validation.py`
from a real run against real November 2017 canonical data (the same
`KPIEngine`/`SemanticRegistry` Steps 3B–3D use) and real Step 4 evidence
citations. Nothing here is fabricated or hand-edited into the JSON.

Reproduce:

```bash
.venv/bin/python -m pytest tests/test_eligibility.py tests/test_method_selector.py \
    tests/test_did.py tests/test_diagnostics.py tests/test_causal_gate.py \
    tests/test_provenance.py tests/test_abstention.py -q
.venv/bin/python scripts/step6_causal_validation.py
```

---

## 1. Architecture

```
CausalHypothesis
      |
      v
eligibility.check_eligibility()      -- 12 checks, always run, always in order
      |
      v
method_selector.select_method()      -- deterministic, explainable, no LLM
      |
      v
dispatch: PVM | DIFFERENCE_IN_DIFFERENCES | INTERRUPTED_TIME_SERIES
        | CAUSAL_IMPACT | DESCRIPTIVE_ASSOCIATION | EXPERIMENTAL_RESULT | NONE
      |
      v
language_gate.enforce_language_gate()  -- every free-text field
      |
      v
engine._extend_graph()  -- evidence.graph integration (optional)
```

No file under `src/causal/` imports an LLM client anywhere — mechanically
verified by an AST scan across every module in the package
(`tests/test_provenance.py::test_no_module_in_causal_package_imports_llm_client`).
Full rationale: `docs/CAUSAL_ARCHITECTURE.md`.

## 2. Reuse, never duplicate

- PVM: `drivers.engine.decompose()` — Step 3D, unmodified.
- KPI values: `kpi.engine.KPIEngine.compute()`/`compare_periods()` — Step 3B, unmodified.
- Evidence citations: `evidence.structured_adapter.driver_decomposition_result_to_evidence_bundle()` — Step 4, unmodified.
- Causal-language guard: `agents.models.UNSUPPORTED_CAUSAL_PATTERN`/`assert_no_unsupported_causal_language` — Step 5, unmodified.

## 3. The one additive touch to a completed step

`evidence.models.GRAPH_NODE_TYPES` gained 4 members
(`CAUSAL_ANALYSIS`, `CAUSAL_RESULT`, `ASSUMPTION`, `DIAGNOSTIC`) and
`evidence.models.RelationshipType` gained 6 members (`TESTED_BY`,
`REJECTED_BY`, `HAS_ASSUMPTION`, `HAS_DIAGNOSTIC`, `UPGRADED_TO`,
`DOWNGRADED_TO`) — purely additive, every pre-existing member's value
unchanged
(`tests/test_provenance.py::test_evidence_models_extensions_are_additive_only`).
`agents.models.ALLOWED_HEDGED_PHRASES` (documentation-only, never
pattern-enforced) gained `"mathematically explains"`.

## 4. Three tier enums, never conflated

`evidence.models.EvidenceTier` (per-evidence-item quality),
`agents.models.AnalyticalMethod` (Step 5's hypothesis-support rigor label),
and the new `causal.models.CausalTier` (what one causal method run can
defensibly support after eligibility + diagnostics) are three distinct
enums. Full mapping table: `docs/CAUSAL_ARCHITECTURE.md` §2.

## 5. The 12 eligibility checks

`treatment_exists`, `outcome_exists`, `treatment_precedes_outcome`,
`sufficient_pre_period`, `sufficient_post_period`, `treatment_variation`,
`control_variation`, `sample_size`, `missingness`, `confounders`,
`consistent_grain`, `consistent_kpi_definition` — always all 12, always in
this fixed order (`tests/test_eligibility.py::
test_all_12_checks_run_in_fixed_order_and_always_return_12_results`).
Roll-up rule and hard/soft-fail table: `docs/CAUSAL_GOVERNANCE.md` §1.

## 6. Method selection

Deterministic, fixed-order decision table (7 methods:
`DESCRIPTIVE_ASSOCIATION`, `PVM`, `DIFFERENCE_IN_DIFFERENCES`,
`INTERRUPTED_TIME_SERIES`, `CAUSAL_IMPACT`, `EXPERIMENTAL_RESULT`, `NONE`) —
full table with exact conditions and rejection templates in
`docs/CAUSAL_METHOD_SELECTION.md`. `why_other_methods_rejected` always names
all 6 non-selected methods. Determinism verified directly
(`tests/test_method_selector.py::test_method_selection_is_deterministic_given_identical_inputs`).

## 7. November 2017 four-hypothesis results (real run)

`required_value_checks.all_checks_pass: true`. All 4 hypotheses:

| Hypothesis | Eligibility verdict | Method | Tier | Status | `causal_claim_allowed` |
|---|---|---|---|---|---|
| C1 order-volume | PARTIALLY_ELIGIBLE | PVM | T2_ARITHMETIC | ARITHMETIC_ONLY | **false** |
| C2 category-growth | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | DESCRIPTIVE_ONLY | **false** |
| C3 delivery/review | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | DESCRIPTIVE_ONLY | **false** |
| C4 geographic | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | DESCRIPTIVE_ONLY | **false** |

`required_value_checks.no_hypothesis_reaches_causal_claim_allowed_true: true`,
`required_value_checks.no_hypothesis_reaches_t3_or_t4: true`.

**C1 order-volume** — real PVM values, exactly matching `STEP3D_VALIDATION.md`
(reused `drivers.engine.decompose()` unmodified): `volume_effect =
417227.65`, `price_effect = 4674.63`, `mix_effect = -75850.34`. Cites **48
real evidence_ids** from Step 4's `driver_decomposition_result_to_evidence_bundle`
(driver + segment + concurrent-KPI evidence, e.g. `ev_driver_54a8543fbf210bd2`).
`evidence_tier` is hard-coded `T2_ARITHMETIC` with no code path able to
produce anything else. Eligibility is `PARTIALLY_ELIGIBLE` only because the
`confounders` check soft-flags the documented November 2017 Black Friday
volume surge — never a hard block.

**C2 category-growth** and **C4 geographic** both fail eligibility on
`treatment_precedes_outcome` (and `sufficient_pre_period`, since their
treatment window is defined to start at the governed window's own start) —
category/state membership is a pre-existing group characteristic with no
assignment timing, so temporal order cannot be established. This is the
mechanism working exactly as intended, not a bug.

**C3 delivery/review** is the one hypothesis with a genuinely well-formed
temporal order (October `on_time_delivery_rate` precedes November
`avg_review_score` — `treatment_precedes_outcome` **passes**), but fails
eligibility on `control_variation` (no clean treatment/control group split
for a continuous delivery-rate KPI) and carries a soft `confounders` flag
(`black_friday_2017_11`) — the November 2017 volume surge confounds any
attempt to attribute a review-score movement to delivery timing alone.
Real reported confounders: `["black_friday_2017_11"]`.

## 8. Evidence graph integration

Real build (`evidence_graph_summary` in the JSON): the 4-hypothesis run adds
**14 nodes / 12 edges** to a fresh graph, node types `{ASSUMPTION,
CAUSAL_ANALYSIS, CAUSAL_RESULT, KPI}`. `TESTED_BY`/`HAS_ASSUMPTION` edges
are present on every result;`DOWNGRADED_TO` fires whenever a method's
aspirational tier (e.g. DiD/ITS reaching for T3) differs from what it
actually achieved.

## 9. Synthetic method demonstrations (code-path proof, not an Olist finding)

To show the DiD/ITS machinery itself is correct and *can* reach a genuine
causal tier — never claimed as an Olist result:

| Method | Constructed scenario | Tier reached | `causal_claim_allowed` |
|---|---|---|---|
| Difference-in-Differences | Parallel pre-trends (identical slope), then a real post-treatment gap | T3_QUASI_EXPERIMENTAL | **true** |
| Interrupted Time Series | 15 pre + 5 post periods, a real level-shift + slope-change, small reproducible noise | T3_QUASI_EXPERIMENTAL | **true** |

Both are labeled in the report with an explicit
`"Synthetic constructed natural experiment -- NOT an Olist finding."` note.

## 10. Test results

**72/72 Step 6 tests pass** across all 7 required files:

| File | Tests |
|---|---|
| `test_eligibility.py` | 14 |
| `test_method_selector.py` | 10 |
| `test_did.py` | 5 |
| `test_diagnostics.py` | 11 |
| `test_causal_gate.py` | 17 |
| `test_provenance.py` | 7 |
| `test_abstention.py` | 8 |

Full repository suite: **758 tests pass, 0 regressions** against the
pre-existing 686-test Step 1–5 suite (`.venv/bin/python -m pytest tests/ -q`
→ `758 passed`).

## 11. Known limitations

- `did.py`'s parallel-trends diagnostic needs a real multi-period pre-trend
  series to do more than fail by default; `engine._build_did_inputs` only
  assembles a single pre/post pair from canonical data today (documented,
  not hidden — `docs/CAUSAL_ARCHITECTURE.md` §5). This is why C2/C4's actual
  routing never reaches the DiD code path on real data anyway (eligibility
  blocks them first) — the gap only matters for a future hypothesis that
  clears eligibility for DiD.
- `causal_impact.py` has no installed Bayesian structural time-series
  package to call into — every real run takes the `METHOD_UNAVAILABLE`
  branch, by design (no new dependency added).
- No adaptive re-invocation: each hypothesis is analyzed exactly once, same
  posture as Step 5's agent modules.
- `causal_hypothesis_from_step5()` is a thin, best-effort bridge, not
  exercised against a real Step 5 run in this validation — the real
  captured `reports/step5_validation.json` has all 3 ANALYST hypotheses
  `ABSTAINED`/`INSUFFICIENT_DATA` with `evidence_ids=[]`, nothing usable to
  bridge from (`STEP5_VALIDATION.md` §14).

---

## STOP CONDITION MET

No recommendations, narratives, feedback-learning mechanism, or frontend
exist anywhere in `src/causal/`. Every quantitative value any
`CausalResult` carries traces to a real Step 3B/3D/4 engine call (PVM
reconciliation, KPI comparisons, evidence bundle citations) — never
recomputed or fabricated. `causal_claim_allowed` is `False` on every one of
the 4 real November 2017 hypotheses, and no code path anywhere in
`src/causal/` can set it `True` without a genuinely passing eligibility
verdict AND genuinely passing method diagnostics (fuzz-tested over the full
input space in `tests/test_abstention.py`). The real November 2017
demonstration in this document is exactly what a governed causal-analysis
layer is supposed to do when the underlying data offers no natural
experiment: it reports T1/T2 evidence honestly, names its confounders, and
withholds every causal claim — rather than manufacturing a
confident-sounding conclusion the data cannot support.

**Step 6 is complete.** The eligibility checker, deterministic method
selector, PVM/DiD/ITS/CausalImpact method wrappers, confounder registry,
causal-language gate, evidence-graph integration, and abstention-outcome
policy are all built, tested (72/72 Step 6 tests, 758 full-repository tests,
0 regressions), and demonstrated end-to-end against real Step 3B–4 engines
and real November 2017 canonical data. Recommendations, narratives, feedback
learning, and a frontend have not been started.
