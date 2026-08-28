# STEP 9 VALIDATION — Human Feedback & Learning Loop

Every structured number in this document is copied directly from
`reports/step9_validation.json`, written by
`scripts/step9_feedback_learning_demo.py` from a real run of the governed
feedback pipeline against the 5 required deterministic fixtures (Correct /
Wrong Driver / Wrong Recommendation / Wrong Confidence / Missing Driver).
Nothing here is fabricated or hand-edited into the JSON.

Reproduce:

```bash
python -m pytest tests/test_feedback_capture.py tests/test_feedback_classifier.py \
    tests/test_feedback_correction.py tests/test_feedback_review.py tests/test_feedback_conflict.py \
    tests/test_feedback_evaluation_case.py tests/test_feedback_regression.py \
    tests/test_feedback_offline_evaluation.py tests/test_feedback_store.py \
    tests/test_feedback_step7_integration.py tests/test_feedback_step8_integration.py \
    tests/test_feedback_safety.py tests/test_feedback_end_to_end.py tests/test_feedback_config.py -q
python scripts/step9_feedback_learning_demo.py
```

---

## 1. Architecture

```
Feedback -> Classification -> Correction/BusinessContext -> [human review] ->
EvaluationCase (versioned) -> [human approval] -> RegressionTest / Offline Evaluation
```

Full diagram and reuse rationale: `docs/FEEDBACK_ARCHITECTURE.md`.

**Non-negotiable principle**: human feedback becomes evaluation data and
controlled improvement, never automatic model training. No file under
`src/feedback/` mutates a `KPIStory`/`NarrativeClaim`/`ActionRecommendation`
in place, retrains a model, changes a prompt/config value unilaterally, or
auto-deploys anything — proven by test, not just asserted in prose (§8
below).

## 2. Reuse, never duplicate

- Claim verification: `story.claim_verifier.verify_claim` — Step 8,
  unmodified, called directly by `feedback.evaluator.evaluate_case`.
- Causal-language guard: `story.language_rules`/`agents.models.
  contains_unsupported_causal_language` — Steps 5/8, unmodified.
- Numeric verification: `story.numeric_verifier` — Step 8, unmodified,
  reached transitively through `verify_claim`.
- Claim/evidence/persona vocabulary: `story.models.ClaimType`/`Persona` —
  Step 8, imported directly, never redefined.
- Recommendation/constraint shape: `decision.models.RecommendationTier`,
  `decision.constraint_engine.evaluate_constraints`'s `business_context`
  dict contract — Step 7, unmodified.
- LLM provider seam: `agents.llm_client.LLMUnavailable`, the
  `llm_client=None` optional-LLM pattern — Step 5, unmodified.
- Config-loader convention: `story.config.StorytellingConfig`'s
  load/validate/read-only-accessor pattern, replicated structurally by
  `feedback.config.FeedbackConfig`.

## 3. Claim identity without touching Step 8

`story.models.NarrativeClaim` has no standalone `claim_id`.
`feedback.models.claim_key(story_id, section_index, claim_index)` is a
pure, derived reference string (`"STORY_NOV2017:1:0"`) any caller resolves
back to a real claim (`story.sections[i].statements[j]`) — Step 8's model
is untouched. `tests/test_feedback_step8_integration.py` proves the
round-trip and proves feedback submission never mutates the story object it
references.

## 4. Real demo run — all 5 required fixtures

`required_value_checks.all_checks_pass: true`:

| Check | Result |
|---|---|
| `five_feedback_cases_submitted` | ✅ true |
| `corrections_stored_for_4_non_correct_cases` | ✅ true |
| `business_context_captured` | ✅ true |
| `evaluation_cases_created_for_4_corrections` | ✅ true |
| `regression_tests_created_for_4_cases` | ✅ true |
| `case2_regression_catches_causal_language_regression` | ✅ true |
| `dataset_level_regression_detected` | ✅ true |
| `no_case_evaluation_metrics_fabricated` | ✅ true |

`feedback_summary`: 5 feedback records, 4 corrections, 3 business contexts,
4 evaluation cases, 4 regression tests — one per non-CORRECT fixture,
exactly as designed (CORRECT feedback needs no correction/eval case).

**Case 1 — Correct**: `rating=CORRECT`, classified to zero categories, no
correction/evaluation case created — confirms the loop does not manufacture
work from feedback that needs none.

**Case 2 — Wrong Driver** (the spec's own worked example, end-to-end):
AI claim *"Delivery deterioration coincided with lower review scores."*
(ASSOCIATION, already correctly hedged) → analyst: *"No — November had a
major holiday campaign that changed review composition."* → classified
`NARRATIVE` → correction stored (`WRONG_DRIVER`, original preserved
verbatim) → business context captured (`HOLIDAY`) → reviewed and approved
→ evaluation case created (`forbidden_claims=["delivery caused review
decline", ...]`) → promoted to a regression test → a **deliberately
regressed candidate** that reintroduces *"Delivery deterioration caused
lower reviews."* is caught: `reg_report_bad.failed == 1`, reason
`"forbidden claim pattern matched: 'delivery caused review decline' in
produced text 'Delivery deterioration caused lower reviews.'"` — proving
the loop is actually enforceable, not just recorded.

**Case 3 — Wrong Recommendation** (Step 7 integration): AI recommends
*"Expedite high-risk shipments."* (tier=TOP) → analyst: *"Carrier capacity
is currently exhausted."* → classified `RECOMMENDATION` → evaluation case's
`input_context["business_context"] = {"operational_capacity_available":
False}` feeds `decision.constraint_engine.evaluate_constraints()`
unmodified, correctly computing `BLOCKED` (`tests/test_feedback_step7_integration.py::
test_evaluation_case_input_context_drives_real_constraint_engine`) → a
candidate still ranking `TOP` under that constraint fails offline
evaluation (`passed=0`); a candidate correctly reporting `BLOCKED` passes
(`passed=1`).

**Case 4 — Wrong Confidence**: AI confidence `0.92` → analyst: *"Evidence is
weak; confidence should be lower."* → classified `CONFIDENCE`,`EVIDENCE` →
evaluation case `expected_confidence_range=(0.0, 0.5)` → an over-confident
candidate (`0.92`) fails, an appropriately-hedged candidate (`0.4`) passes.

**Case 5 — Missing Driver**: AI: *"AOV decline is explained by product
mix."* → analyst: *"Pricing change was another important driver."* →
classified `DRIVER` → evaluation case `expected_claims=["pricing
change"]` → a candidate that still omits pricing fails; a fixed candidate
mentioning both drivers passes.

## 5. Dataset-level offline evaluation — baseline vs. regressed candidate

All 4 `APPROVED_FOR_EVALUATION` cases evaluated together:

| Metric | Baseline | Regressed candidate | Delta |
|---|---|---|---|
| `numeric_accuracy` | 1.0 | 0.0 | -1.0 |
| `causal_correctness` | 1.0 | 0.0 | -1.0 |
| `recommendation_accuracy` | 1.0 | 0.0 | -1.0 |
| `confidence_accuracy` | 1.0 | 0.0 | -1.0 |

`comparison.regressions = ["causal_correctness", "confidence_accuracy",
"numeric_accuracy", "recommendation_accuracy"]`, `improvements = []` — the
comparison correctly flags all 4 metrics as regressed and **does not
deploy anything**; `evaluator.compare_baseline_candidate` only ever
produces this report, a human decides what to do with it (spec §19/§20).

## 6. Conflicting feedback

`tests/test_feedback_conflict.py` proves two analysts disagreeing (e.g.
*"Promotion caused the AOV decline."* vs. *"Competitor pricing caused the
AOV decline."*) both land on `FeedbackStatus.CONTESTED` — symmetric, no
silent winner — with a `ConflictRecord` preserving both hypotheses for
future research.

## 7. Human review gates — nothing bypasses them

- `evaluation_case.create_evaluation_case()` raises `EvaluationCaseError`
  unless the source `Feedback.review_status == APPROVED_FOR_EVALUATION`
  (`tests/test_feedback_review.py::test_pending_feedback_cannot_become_evaluation_case`).
- `review.review_feedback()` cannot skip `REVIEWED` straight to
  `APPROVED_FOR_EVALUATION`, and a terminal status
  (`APPROVED_FOR_EVALUATION`/`REJECTED`) can never be reversed — only a
  fresh `Feedback` submission supersedes it, preserving history.
- `regression.promote_to_regression_test()` raises `RegressionError` unless
  the source `EvaluationCase.status == APPROVED_FOR_EVALUATION`.

## 8. Safety / integrity — proven by test, not just asserted

`tests/test_feedback_safety.py`:

- Feedback submission never mutates a live `EvidenceItem.value`,
  `NarrativeClaim.validation_status`/`.text`, or `ActionRecommendation.tier`/
  `.priority_score` it references (identity/equality checked before and
  after).
- An AST-scan across every file in `src/feedback/` (same technique
  `tests/test_orchestrator.py` uses for Step 5's Orchestrator) proves: no
  import of a training/fine-tuning library (`torch`/`tensorflow`/`sklearn`/
  `transformers`/...); no call to a function named anything resembling
  `fit`/`train`/`fine_tune`/`deploy`/`publish_model`; `agents.llm_client` is
  only ever imported inside a function body (never at module scope), so
  `llm_client=None` always works with zero import cost, exactly like
  `story/generator.py`.
- Newly submitted feedback always starts `review_status=PENDING` — there is
  no constructor path that starts pre-approved.

## 9. What this does NOT do (honest scope)

- **No live LLM call in the primary demo**, matching Steps 7/8's own
  precedent: the demo and every test run with `llm_client=None`. The
  optional LLM classifier path is unit-tested against a fake client with
  valid-output, malformed-output, invalid-category, and
  `LLMUnavailable`-raising scenarios (`tests/test_feedback_classifier.py`),
  but a live Groq run is a manual follow-up.
- **No live Step 7/8 pipeline wiring in this demo's `candidate_runner`
  functions** — they are hand-built `CandidateOutput(...)` stand-ins,
  matching Step 7/8's own "hand-authored demo objects" precedent. The
  `evaluator.run_offline_evaluation`/`regression.run_regression_tests`
  interfaces are real and already reuse `story.claim_verifier` directly, so
  wiring a live `story.engine.generate_kpi_story()` call in as a
  `candidate_runner` is a follow-on integration, not a redesign.
- **`min_approvals_required` is documented, not enforced.**
  `config/feedback.yaml`'s review-workflow policy value exists for
  governance visibility; enforcing "N distinct reviewers" requires a
  multi-user session concept this repository does not have yet.
- **No frontend/API** — Python-callable functions only, matching every
  prior step's own precedent for a repository with no UI/API layer yet.

## 10. Test results

93/93 Step 9 tests pass across 14 new test files. Full repository
regression check: baseline after Step 8 was 976 passing; adding Step 9's 93
tests brings the total to **1069 passing with zero new failures**.
