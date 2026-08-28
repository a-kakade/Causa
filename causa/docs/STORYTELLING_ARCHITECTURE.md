# Storytelling Architecture (Step 8)

```
EvidencePackage
      |
      v
persona.PersonaEngine.select_and_order()      -- config/personas.yaml, deterministic
      |
      v
planner.plan_narrative()                       -- LLM-backed + deterministic fallback; SELECTS evidence_ids ONLY, never creates new evidence
      |
      v
generator.generate_narrative()   <----+          -- LLM-backed + deterministic fallback; claim-level statements
      |                               |
      v                               | retry with feedback (up to config.max_generation_retries)
claim_verifier.verify_story_claims() -+
      |
      v (APPROVED)                    (exhausted retries)
      |                                    |
      v                                    v
   KPIStory                    fallback (if allowed) or StoryGenerationFailed
```

Non-negotiable principle (this step's own words): **LLM = storyteller, Code
= source of truth, Verifier = gatekeeper.** Never LLM = analyst + calculator
+ storyteller. No file under `src/story/` imports an LLM client except
`planner.py` and `generator.py`, and both remain fully functional and
deterministic with `llm_client=None`. Every number in a returned `KPIStory`
has been independently, deterministically matched against the trusted
`EvidencePackage` by `claim_verifier.py`/`numeric_verifier.py` — the LLM is
never asked to self-certify its own numbers.

## 1. Reuse, never duplicate

| Reused from | What Step 8 calls | Never |
|---|---|---|
| Step 5 (`agents.models`) | `assert_no_unsupported_causal_language`, `UNSUPPORTED_CAUSAL_PATTERN`, `ALLOWED_HEDGED_PHRASES` | defines a third causal-language regex |
| Step 5 (`agents.llm_client`) | `GroqLLMClient`, `FakeLLMClient`, `LLMUnavailable`, `has_groq_credentials`, `DEFAULT_MODEL`, `GROQ_API_KEYS`/`GROQ_MODEL` env vars | introduces a second, parallel LLM provider or env-var convention |
| Step 4 (`evidence.schema`) | `EvidenceObject` (wrapped, never re-derived) | recomputes a KPI/driver value itself |
| Step 6 (`causal.models`) | `CausalResult` (wrapped, never re-derived) | recomputes a causal estimate itself |
| Step 7 (`decision.models`) | `ActionRecommendation` (cited verbatim: owner, expected_impact, confidence) | alters a recommendation's numbers when narrating it |
| Step 3A (`kpi.semantic_registry`) | the load/validate/read-only-accessor pattern (`SemanticRegistry`) | invents a different config-loading convention |

## 2. `ClaimType` — a new, deliberately separate axis

| Enum | Owner | Question it answers |
|---|---|---|
| `evidence.models.EvidenceType` | Step 4 | What **kind** of measurement is this (KPI_OBSERVATION, DRIVER_CONTRIBUTION, ANOMALY_SIGNAL, ...)? |
| `evidence.models.EvidenceTier` | Step 4 | What **methodological rigor** produced it (T1_DESCRIPTIVE .. T5_EXPERIMENTAL)? |
| `story.models.ClaimType` | Step 8 | What **epistemic strength** may a NARRATIVE SENTENCE citing this evidence claim (FACT / ANALYTICAL_FINDING / ASSOCIATION / HYPOTHESIS / UNKNOWN)? |

A T3_STATISTICAL anomaly signal and a T1_DESCRIPTIVE KPI movement are both
real Step 4 evidence, but a sentence built from the former may only ever be
phrased as an `ASSOCIATION`, never a `FACT` — `ClaimType` captures that
constraint, which neither `EvidenceType` nor `EvidenceTier` has any
vocabulary for. Fixed mapping table (`story/evidence_package.py`):

| Source | Condition | ClaimType |
|---|---|---|
| `EvidenceObject` | `KPI_OBSERVATION`/`KPI_MOVEMENT`/`CUSTOMER_REVIEW` | `FACT` |
| `EvidenceObject` | `DRIVER_CONTRIBUTION`/`SEGMENT_CONTRIBUTION` (T2_ARITHMETIC) | `ANALYTICAL_FINDING` |
| `EvidenceObject` | `CONCURRENT_KPI`/`ANOMALY_SIGNAL`/`STATISTICAL_RESULT` | `ASSOCIATION` |
| `CausalResult` | `status=CAUSAL_SUPPORTED` or `ARITHMETIC_ONLY` | `ANALYTICAL_FINDING` (never `FACT` of causation) |
| `CausalResult` | `status=DESCRIPTIVE_ONLY` | `FACT` |
| `CausalResult` | `status=CAUSAL_INSUFFICIENT` | `HYPOTHESIS` |
| `CausalResult` | `status=CAUSAL_REJECTED` | `UNKNOWN` |
| `ActionRecommendation` | always | not epistemically typed — cited by `recommendation_id`, never narrated as a measurement claim |

Even a `CAUSAL_SUPPORTED` result maps only to `ANALYTICAL_FINDING`, never
`FACT` — a validated causal finding is still never licensed to be narrated
as a bare, unqualified statement of causation.

## 3. Claim-level grounding and verification pipeline

Every `NarrativeClaim` carries `text`, `claim_type`, `evidence_ids`,
`confidence` (propagated verbatim from cited evidence, categorical or
numeric, never invented), and `numeric_claims`. `claim_verifier.verify_claim()`
runs six checks in fixed order, short-circuiting on first failure:

1. **Evidence-ID existence** — every cited id (excluding a `rec_*`
   recommendation id, checked separately in #6) must exist in the package.
2. **Epistemic-type consistency** — `CLAIM_TYPE_RANK` is a total order
   (`FACT > ANALYTICAL_FINDING > ASSOCIATION > HYPOTHESIS > UNKNOWN`); a
   claim may hedge down from its cited evidence's strongest `ClaimType`,
   never claim stronger.
3. **Language-rule check** (`language_rules.violates_language_rule`) —
   reuses `agents.models.UNSUPPORTED_CAUSAL_PATTERN` as the deterministic
   blacklist; `ALLOWED_VERBS` is prompt/template guidance only, never a
   whitelist gate (too brittle against natural LLM phrasing variance).
4. **Numeric verification** (`numeric_verifier.verify_numeric_claims`) —
   every number extracted from the claim's text must match a real evidence
   item's value, unit-scoped (a percent claim never matches a BRL value).
5. **Unsupported-metric check** — a quantified (`FACT`/`ANALYTICAL_FINDING`)
   claim citing numeric evidence but stating no verifiable number of its
   own is rejected.
6. **Unsupported-recommendation check** — a cited `recommendation_id` must
   exist in the package's real Step 7 output.

A story is `APPROVED` only if **every** claim passes — one rejected claim
rejects the whole narrative (never partial acceptance).

## 4. Numeric verifier — extending, not duplicating, `agents.models`

`agents.models.validate_numeric_claims` (Step 5) checks a flat `set[float]`
of allowed numbers with no unit awareness and no thousand/million-suffix
handling. `story.numeric_verifier` extends that same pattern with two new
capabilities the task requires:

1. **K/M-suffix expansion**: `"R$417K"` → `417000.0`, unit `BRL`.
2. **Unit-scoped matching against a specific evidence_id**: `build_evidence_value_index()`
   builds `evidence_id -> (value, unit)`; a claim's extracted number is only
   ever compared against evidence of the *same* unit, and a rejection names
   the specific trusted value and its evidence_id (`"...does not match
   trusted evidence EV001, which reports 52.1%..."`), not just "some number
   didn't match."

Reused directly from `agents.models`'s own precedent: the calendar-year
exemption (a bare `2017` is a date reference, not a business number) and
the `minimum_magnitude` structural-label exemption (a bare small integer
like a date fragment or list index is not a business claim) — both fixed
the identical false positives `agents.models.validate_numeric_claims`
already documents having hit and fixed once before.

## 5. Configuration

| File | Owns | Loader |
|---|---|---|
| `config/personas.yaml` | Persona → focus areas → preferred metrics/evidence types → excluded types → section order → detail level (the 4 required personas' business vocabulary) | `story.persona.PersonaEngine` |
| `config/storytelling.yaml` | LLM model override/temperature/token limits, `max_generation_retries`, numeric tolerance/floor/minimum-magnitude, `allow_deterministic_fallback` | `story.config.StorytellingConfig` |

Adding a 5th persona is a pure YAML addition to `personas.yaml`; changing a
retry count or tolerance is a pure YAML addition to `storytelling.yaml` —
neither requires a code change.

## 6. Retry/regeneration

`story.engine.generate_kpi_story()` is the single entry point: plan once,
then loop generate → verify, up to `config.max_generation_retries` extra
attempts. On rejection, a feedback message is built citing the exact failed
claim and trusted value (`'FAILED CLAIM: "..." ERROR: ... REGENERATE using
the trusted value.'`) and appended to the next generation prompt. On
persistent failure, the engine either falls back to the deterministic
template (re-verified before being returned, and explicitly labeled
`GeneratedBy.DETERMINISTIC_TEMPLATE` — never presented as if it were the
failed LLM attempt) or raises `StoryGenerationFailed`, controlled by
`config.fallback.allow_deterministic_fallback` — never a silently-presented
unverified narrative either way.
