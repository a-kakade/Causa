# Feedback & Learning Loop Architecture (Step 9)

```
Analyst / User
      |
      v
capture.submit_feedback()                -- validation + construction only, no storage
      |
      v
classifier.classify_feedback()           -- deterministic rules; optional LLM assist, always validated
      |
      v
store.FeedbackStore.save_feedback()      -- append-only JSONL, status=UNREVIEWED/PENDING
      |
      v
correction.store_correction()            -- original + corrected, BOTH preserved
correction.capture_business_context()    -- context the pipeline could not see, stored separately
      |
      v
review.review_feedback()                 -- PENDING -> REVIEWED -> APPROVED_FOR_EVALUATION | REJECTED
review.contest_feedback()                -- competing hypotheses -> CONTESTED, never arbitrated
      |
      v (only APPROVED_FOR_EVALUATION)
evaluation_case.create_evaluation_case() -- what the system SHOULD have said, versioned (v1, v2, ...)
      |
      v
evaluation_case.approve_evaluation_case()
      |
      v (only APPROVED_FOR_EVALUATION)
regression.promote_to_regression_test()  -- runnable regression check
      |
      v
evaluator.run_offline_evaluation()       -- reuses story.claim_verifier / language_rules / numeric_verifier
evaluator.compare_baseline_candidate()   -- per-metric delta + regressions, human decides whether to deploy
```

Non-negotiable principle (this step's own words): **human feedback becomes
evaluation data and controlled improvement, never automatic model training.**
No file under `src/feedback/` mutates a `story.models.KPIStory` /
`NarrativeClaim` or a `decision.models.ActionRecommendation` in place,
retrains a model, changes a prompt/config value on its own, or auto-deploys
anything. Every function in this package only ever produces a new,
additively-stored record; a human decides at two explicit gates
(`review_feedback` and `approve_evaluation_case`) whether that record may
ever influence future evaluation, and `run_offline_evaluation` /
`compare_baseline_candidate` only ever *inform* a human deploy decision —
they never make one.

## 1. Reuse, never duplicate

| Reused from | What Step 9 calls | Never |
|---|---|---|
| Step 8 (`story.models`) | `ClaimType`, `Persona`, `NarrativeClaim`, `EvidencePackage` | invents a parallel claim-strength or persona taxonomy |
| Step 8 (`story.claim_verifier`) | `verify_claim()` — the SAME function that gates real `KPIStory` generation | writes a second causal/numeric verifier |
| Step 8 (`story.language_rules` / `agents.models`) | `contains_unsupported_causal_language()` | writes a third causal-language regex |
| Step 8 (`story.numeric_verifier`) | numeric claim matching, via `claim_verifier` | re-derives numeric comparison logic |
| Step 7 (`decision.models`) | `ActionRecommendation.recommendation_id`, `RecommendationTier` values in `expected_recommendation` dicts | modifies `constraint_engine.py`/`ranking.py`/ontology config |
| Step 8 (`story/config.py`, `story/persona.py`) | the `load()/validate()/`read-only-accessor config-loader convention | invents a different config-loading convention |
| Step 5 (`agents.llm_client`) | `LLMUnavailable`, the `llm_client=None` optional-LLM pattern | a second, parallel LLM provider integration |

## 2. Claim identity — a derived key, not a new field on Step 8

`story.models.NarrativeClaim` has no standalone `claim_id`: a claim is
identified by its position within a `KPIStory`'s `sections`. Rather than add
a field to a "completed" step's core model, Step 9 defines one pure
function:

```python
claim_key(story_id, section_index, claim_index) -> f"{story_id}:{section_index}:{claim_index}"
```

`Feedback.affected_claim_keys` stores these strings. Resolving one back to
a real `NarrativeClaim` is a one-line lookup
(`story.sections[i].statements[j]`) any caller can do — `feedback/models.py`
performs no such resolution itself, keeping the two packages loosely
coupled (Step 9 never imports `story.engine`/`story.generator`).
`affected_evidence_ids` and `affected_recommendation_id` reuse
`EvidenceItem.evidence_id` / `ActionRecommendation.recommendation_id`
verbatim — real IDs Steps 4–8 already mint, never reinvented.

## 3. Two independent status axes

| Axis | Enum | Question it answers |
|---|---|---|
| Trust | `FeedbackStatus` (`UNREVIEWED/ACCEPTED/REJECTED/CONTESTED`) | Is this feedback itself believed? |
| Promotion | `ReviewStatus` (`PENDING/REVIEWED/APPROVED_FOR_EVALUATION/REJECTED`) | Has this feedback (or the `EvaluationCase` built from it) been cleared to influence future evaluation? |

These are deliberately not conflated. A `CONTESTED` correction (two
analysts disagree — spec §21/§22) can still be preserved for future
research without ever reaching `APPROVED_FOR_EVALUATION`. Conversely,
nothing in this package can reach `APPROVED_FOR_EVALUATION` except through
`review.review_feedback()` being called by an explicit, named `reviewer` —
there is no code path from raw submission to evaluation data that skips
human review (spec §18, enforced by `evaluation_case.create_evaluation_case`
raising `EvaluationCaseError` otherwise).

## 4. Append-only storage — history is never mutated

This repository has no database anywhere (Parquet for canonical data, YAML
for config, in-memory dataclasses for Step 7/8 runtime objects). Step 9 is
the first step needing durable persistence, so `store.FeedbackStore`
introduces one JSON-Lines file per record type under `data/feedback/`,
written with `open(..., "a")` only. A status change
(`FeedbackStatus`/`ReviewStatus`) is itself a new **appended event record**,
never an edit to the original line — `FeedbackStore.list_feedback()` folds
the event log to compute the current, materialized status a caller sees,
so the full history survives on disk even though the API looks like normal
mutable objects.

## 5. Offline evaluation — computed, never fabricated

`evaluator.evaluate_case()` checks only the dimensions an `EvaluationCase`
actually declares an expectation for (`forbidden_claims`, `expected_claims`,
claim-level verification via the real `story.claim_verifier.verify_claim`,
`expected_recommendation`, `expected_driver`, `expected_confidence_range`).
A dimension with no declared expectation is skipped, never scored as a
pass. `run_offline_evaluation()` rolls per-case results into metrics
(`numeric_accuracy`, `evidence_grounding`, `causal_correctness`,
`driver_accuracy`, `recommendation_accuracy`, `confidence_accuracy`,
`unsupported_claim_rate`) computed only from cases that exercised that
check — spec §16's "do not fabricate metrics" is structural, not a
convention. `compare_baseline_candidate()` is a pure diff: it flags
per-metric regressions/improvements (respecting that
`unsupported_claim_rate` is lower-is-better, inverted from every other
metric) and never chooses to deploy anything itself.

## 6. Regression tests — only from approved cases

`regression.promote_to_regression_test()` raises `RegressionError` unless
the source `EvaluationCase.status == APPROVED_FOR_EVALUATION` (spec §17:
"Do not automatically add every piece of feedback blindly"). A
`RegressionTest`'s pass/fail check reuses `evaluator.evaluate_case()`
directly, so a regression failure and an offline-evaluation-metric failure
can never silently disagree — they are the same code path.

## 7. Integration points

- **Step 7 (`decision`)**: a `RECOMMENDATION` feedback's `EvaluationCase`
  carries `input_context["business_context"]` in the exact shape
  `decision.constraint_engine.evaluate_constraints()` already consumes
  (e.g. `{"operational_capacity_available": False}`), and
  `expected_recommendation={"tier": "BLOCKED"}` checks the candidate's
  `RecommendationTier` — never modifies `constraint_engine.py`, `ranking.py`,
  or `config/decision_scoring.yaml`/`decision_ontology.yaml`.
- **Step 8 (`story`)**: a `STORY_CLAIM` feedback references a claim via
  `claim_key()`; its `EvaluationCase.forbidden_claims`/`expected_claims`
  are checked against candidate output using the same
  `story.claim_verifier`/`language_rules` gate that governs real `KPIStory`
  generation — the exact enforcement of spec §35's closing example: "the
  causal error does not recur."

## 8. What Step 9 will never do (spec §20/§31)

No file in `src/feedback/` imports a training/fine-tuning library
(`torch`/`tensorflow`/`sklearn`/`transformers`/...) or calls anything
resembling `fit()`/`train()`/`deploy()` — verified mechanically by an
AST-scan test (`tests/test_feedback_safety.py`, the same technique
`tests/test_orchestrator.py` uses to prove Step 5's Orchestrator never
imports an LLM client directly). Feedback submission is proven, by test, to
never mutate a live `NarrativeClaim`/`EvidenceItem`/`ActionRecommendation`
object it references. The only optional LLM touchpoint
(`classifier.classify_feedback`) is imported lazily inside a function body
— exactly like `story/generator.py` — and its output is validated against
`FeedbackCategory` before ever being trusted, falling back to the
deterministic rule layer on `LLMUnavailable` or malformed output.
