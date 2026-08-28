# STEP 8 VALIDATION — Persona-Aware KPI Storytelling

Every structured number in this document is copied directly from
`reports/step8_validation.json`, written by `scripts/step8_persona_storytelling_demo.py`
from a real run of the governed storytelling pipeline against one hand-authored
`EvidencePackage` (the task's own exact example numbers: Revenue +52.1%,
Orders +62.9%, AOV -6.75%, Volume +R$417K, Mix -R$75.9K, Delivery +27.9%,
Reviews -5.2%) plus one Step 7-shaped `ActionRecommendation`. Nothing here
is fabricated or hand-edited into the JSON.

Reproduce:

```bash
python -m pytest tests/test_story_models.py tests/test_persona_engine.py tests/test_evidence_package.py \
    tests/test_language_rules.py tests/test_numeric_verifier.py tests/test_claim_verifier.py \
    tests/test_narrative_planner.py tests/test_narrative_generator.py tests/test_story_retry.py \
    tests/test_story_step7_integration.py tests/test_story_end_to_end.py -q
python scripts/step8_persona_storytelling_demo.py
```

---

## 1. Architecture

```
EvidencePackage (hand-authored, or bridged from real EvidenceObject/CausalResult/ActionRecommendation)
      |
      v
persona.PersonaEngine.select_and_order()      -- config/personas.yaml, deterministic
      |
      v
planner.plan_narrative()                       -- LLM-backed + deterministic fallback; selects/orders evidence_ids ONLY
      |
      v
generator.generate_narrative()   <----+          -- LLM-backed + deterministic fallback; claim-level statements
      |                               |
      v                               | retry with feedback (up to max_generation_retries)
claim_verifier.verify_story_claims() -+
      |
      v (APPROVED)                    (exhausted)
      |                                    |
      v                                    v
   KPIStory                    fallback (if allowed) or StoryGenerationFailed
```

No module in `src/story/` imports an LLM client except `planner.py` and
`generator.py` — both accept `llm_client=None` and remain fully functional
and deterministic without one. Full rationale: `docs/STORYTELLING_ARCHITECTURE.md`.

**Non-negotiable principle**: LLM = storyteller, Code = source of truth,
Verifier = gatekeeper. Every number cited in a `KPIStory` is independently,
deterministically re-verified against the trusted `EvidencePackage` before
the story is ever returned — the LLM is never asked "are these numbers
correct?"; `claim_verifier.py`/`numeric_verifier.py` perform that check
themselves.

## 2. Reuse, never duplicate

- Causal-language guard: `agents.models.assert_no_unsupported_causal_language`/`UNSUPPORTED_CAUSAL_PATTERN`/`ALLOWED_HEDGED_PHRASES` — Step 5, unmodified, reused by `language_rules.py`.
- LLM provider seam: `agents.llm_client.GroqLLMClient`/`FakeLLMClient`/`LLMUnavailable`/`has_groq_credentials`/`DEFAULT_MODEL`/`GROQ_API_KEYS`/`GROQ_MODEL` — Step 5, unmodified. Every LLM-touching test uses `FakeLLMClient` ("mock the LLM, never the business logic").
- Evidence source objects: `evidence.schema.EvidenceObject`, `causal.models.CausalResult`, `decision.models.ActionRecommendation` — Steps 4/6/7, unmodified, wrapped (never re-derived) by `story/evidence_package.py`.
- Config-loader convention: `kpi.semantic_registry.SemanticRegistry`'s load/validate/read-only-accessor pattern, replicated structurally by `story.persona.PersonaEngine`/`story.config.StorytellingConfig`.

## 3. The `ClaimType` vs `EvidenceType`/`EvidenceTier` distinction

`story.models.ClaimType` (`FACT`/`ANALYTICAL_FINDING`/`ASSOCIATION`/`HYPOTHESIS`/`UNKNOWN`)
is a **new, deliberately separate axis** from two enums this repo already
has: `evidence.models.EvidenceType` (what *kind* of measurement — e.g.
`KPI_MOVEMENT` vs `DRIVER_CONTRIBUTION`) and `evidence.models.EvidenceTier`
(what *methodological rigor* produced it — T1 through T5). A T3_STATISTICAL
anomaly signal and a T1_DESCRIPTIVE KPI movement are both real Step 4
evidence, but a narrative sentence built from the former may only ever be
phrased as an `ASSOCIATION`, never a `FACT` — `ClaimType` captures that
narrative-language constraint, which neither existing enum has any
vocabulary for. `story/evidence_package.py::_infer_claim_type_for_evidence_object`/
`_infer_claim_type_for_causal_result` implement the fixed mapping table,
pinned by `tests/test_evidence_package.py`.

Notably, even a `CausalResult` with `status=CAUSAL_SUPPORTED` maps only to
`ANALYTICAL_FINDING`, never `FACT` — a validated causal finding is still
never licensed to be narrated as a bare, unqualified fact of causation.

## 4. Real demo run (all 4 personas, one shared evidence package)

`required_value_checks.all_checks_pass: true` — all 4 personas generated,
all 4 stories independently verified `APPROVED`, and personas produce
genuinely different section groupings/ordering from the identical
underlying evidence.

**Executive** (`verification: APPROVED, 9 claims checked, 0 rejected`):
- Headline: *"revenue increased 52.1% in 2017-11."*
- Key movement: revenue +52.1%, orders +62.9%.
- Main drivers: aov -6.75%, volume contributes R$417000.0.
- Business implication: mix -R$75900.0, delivery association with reviews.
- Recommended actions: *"Expedite high-risk shipments"* (Step 7's real `ActionRecommendation`, cited verbatim).
- Risks and uncertainty: review association, explicit insufficiency statement for the delivery→review causal question.

**Finance** (`verification: APPROVED, 9 claims checked, 0 rejected`):
- Prioritizes the revenue bridge (revenue, aov, volume, mix, orders) in one section, ahead of any operational detail.
- Never mentions "margin" anywhere in its story — no margin evidence exists in the package, and the deterministic template (and every LLM claim, independently re-verified) never invents one (`tests/test_story_end_to_end.py::test_finance_story_never_invents_margin_evidence`).

**Operations** (`verification: APPROVED, 9 claims checked, 0 rejected`):
- Leads with delivery/fulfillment evidence (`on_time_delivery_rate`, `avg_review_score`) ahead of revenue/orders — the opposite ordering priority from Executive/Finance.
- Includes the same Step 7 recommendation, since Operations Manager is its real owner.

**Marketing** (`verification: APPROVED, 9 claims checked, 0 rejected`):
- Leads with demand/orders (`orders`, `aov`) ahead of driver-decomposition detail.

Every one of the 4 stories cites the identical trusted numbers
(52.1, 62.9, -6.75, 417000.0, -75900.0, 27.9, -5.2, 585.0) — re-verified
directly in `tests/test_story_end_to_end.py::test_all_personas_preserve_the_same_trusted_numbers`
by re-extracting every number mentioned anywhere in each story and matching
it against the evidence package independently of the pipeline's own
internal verification pass.

## 5. Numeric verifier — the exact required examples, all passing

| Claim text | Trusted value | Result |
|---|---|---|
| `"Revenue increased 52.1%."`| 52.1% (EV001) | APPROVED |
| `"Revenue increased 52.10%."` | 52.1% (EV001) | APPROVED (formatting-normalized) |
| `"Revenue increased 57%."` | 52.1% (EV001) | REJECTED — reason cites the trusted `52.1` value |
| `"Volume contributed R$417K."` | 417000.0 BRL (EV004) | APPROVED (K-suffix expanded) |
| `"Profit increased 18%."` | *(no profit evidence exists)* | REJECTED — no matching evidence |
| `"Reviews declined 5.2%."` vs `"Orders increased 52%."` | distinct values | never confused (10x apart, unit-scoped matching) |

## 6. Causal/uncertainty language — the exact required examples, all passing

| Text | ClaimType | Result |
|---|---|---|
| `"Delivery deterioration coincided with lower review scores."` | ASSOCIATION | allowed |
| `"Delivery deterioration caused lower review scores."` | ASSOCIATION | rejected |
| `"Delivery delays may have contributed to the review decline."` | HYPOTHESIS | allowed |
| `"Volume explains R$417K of the increase."` | ANALYTICAL_FINDING | allowed |
| `"Volume growth caused the revenue increase."` | ANALYTICAL_FINDING | rejected (free causal wording, not a hedged phrase) |

## 7. Retry/regeneration

`tests/test_story_retry.py` proves the full loop against a real, scripted
first-attempt failure: a generator response citing `"Revenue increased
57%."` (wrong number) is rejected by verification, a feedback message
citing the exact trusted value is built and sent back to the model, and the
second attempt (returning the correct `52.1%`) succeeds — `generation_attempts == 2`.
Persistent failure (every scripted attempt wrong) either falls back to the
deterministic template (re-verified before being returned, `allow_deterministic_fallback=true`)
or raises `StoryGenerationFailed` (`allow_deterministic_fallback=false`) —
never a silently-presented unverified narrative either way.

## 8. What this does NOT do (honest scope)

- **No live LLM call in the primary demo**, by design (matching the
  confirmed decision, itself matching Step 7's own demo precedent): the
  demo and every test run with `llm_client=None`, exercising the
  deterministic template path end-to-end. The LLM boundary (`planner.py`/
  `generator.py`) is fully implemented and unit-tested against
  `agents.llm_client.FakeLLMClient` with all 5 required scripted scenarios
  (valid, wrong-number, unsupported-claim, wrong-causality, malformed
  JSON), but a live Groq run is a manual follow-up (set `GROQ_API_KEYS` and
  pass a real `GroqLLMClient` to `generate_kpi_story`), not part of this
  validation run.
- **No numeric-probability confidence.** `evidence.models.Confidence` is
  categorical (HIGH/MEDIUM/LOW/UNKNOWN); `causal.models.CausalResult`
  carries no confidence field at all; only `decision.models.ScoreBreakdown.confidence_score`
  is a real numeric 0-1 value. `EvidenceItem.confidence` propagates
  whichever representation its source actually carries — this package
  never invents a numeric probability where the source is categorical.
- **No live Step 4-7 pipeline wiring in this demo** — the demo package is
  hand-authored (real `EvidenceObject`/`ActionRecommendation` instances,
  built by hand rather than from a live canonical-data run), matching
  Step 7's own demo precedent exactly. `story/evidence_package.py`'s
  builder functions are real and unit-tested against these same real
  object types, so wiring to a live pipeline run is a follow-on
  integration, not a redesign.
- **No feedback-learning loop.** Step 8 covers persona-specific
  narratives only; `PROJECT_JOURNEY.md`'s own backlog separately lists
  feedback learning as unstarted, out of scope here.

## 9. Test results

105/105 Step 8 tests pass across all 11 new test files. Full repository
regression check: baseline after Step 7 was 871 passing; adding Step 8's
105 tests brings the total to 976 passing with zero new failures.
