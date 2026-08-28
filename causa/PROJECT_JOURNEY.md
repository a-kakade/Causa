# Causa — Project Journey

A living log of the Causa build, step by step. Updated at the end of every step —
read this first if you're picking the project back up after a break. Each entry
links to that step's own validation document, which has the full detail; this
file is the map, not the territory.

**Standard held throughout:** every claim must trace back to the real raw Olist
data (`archive.zip` → `data/raw/olist/`), nothing fabricated or simulated. No step
has skipped ahead of what the prior step actually established.

---

## Where we are right now

**Session note (2026-08-29): frontend verified working; Step 5 pipeline
live-tested against a fresh Groq key.** A React/Vite frontend
(`frontend/`, sibling to `causa/` at the repo root) already exists on disk,
built against the design intent of showing every step's real backend
output — but it is **not yet committed to git** (shows untracked) and has
no live API wired up: `frontend/src/api/index.ts` currently points at
`demoAdapter`, which serves every page from static JSON fixtures in
`public/fixtures/`; `productionApi/index.ts` is an empty stub, since (per
the bullet below) the Python backend still exposes no HTTP surface.
Verified this session: dev server starts clean, all 9 nav pages
(Overview, Active Investigation, Evidence Explorer, Evidence Graph,
Recommendations, Impact & Feedback, Audit Logs, Security, Telemetry) render
their fixture data with zero console errors and working client-side
routing.

Separately, a new Groq API key was supplied, confirmed valid directly
against Groq's `/models` endpoint, and appended to the `GROQ_API_KEYS` pool
in `causa/.env` (now 18 keys, still gitignored). `scripts/
step5_investigate_november_2017.py` was re-run live end-to-end against it:
`dry_run: false` (real Groq calls, not the `FakeLLMClient` fallback),
139/139 Step 5 tests pass, all required numeric checks match, ~$0.024 of
real Groq usage across both the ANALYST and EXECUTIVE runs. The
investigation itself came back `ABSTAINED` this run (the Hypothesis
agent's tool-calling loop didn't submit a valid hypothesis set within its
iteration budget) — consistent with the same honest-abstention behavior
already documented in `STEP5_VALIDATION.md`, just with different
LLM-output variance than the previously-committed run (which abstained
too, but after generating 3 hypotheses first). This regenerated
`reports/step5_validation.json`, which the earlier committed version now
differs from.

**Step 9 complete (2026-08-28): the Human Feedback & Learning Loop.** The
system now learns from analysts without ever automatically fine-tuning or
retraining anything: `Feedback → Structured Classification → Stored
Correction/Business Context → Evaluation Dataset → Offline Evaluation →
Regression Tests`, never `Feedback → automatic model training`.
`src/feedback/` (9 files): a `Feedback` capture layer requiring no
authentication (user_id is always optional), a deterministic multi-category
classifier (`DATA/KPI_DEFINITION/DRIVER/EVIDENCE/CONFIDENCE/RECOMMENDATION/
NARRATIVE`, with an optional validated LLM-assist that always falls back to
the deterministic rules), a `Correction`/`BusinessContext` capture layer
that preserves the ORIGINAL AI claim alongside the human correction (never
overwrites it), a two-axis status model (`FeedbackStatus` for trust —
`UNREVIEWED/ACCEPTED/REJECTED/CONTESTED` — kept deliberately separate from
`ReviewStatus` for eval-promotion — `PENDING/REVIEWED/
APPROVED_FOR_EVALUATION/REJECTED`), append-only JSONL storage
(`data/feedback/`, this repo's first genuinely durable store — status
changes are appended events folded at read time, never in-place edits), a
versioned `EvaluationCase` dataset (`v1`, `v2`, ... — a changed expectation
mints a new version, never rewrites a prior one) capturing both `
expected_claims` and `forbidden_claims`, a review-gated promotion path
(`APPROVED_FOR_EVALUATION` only, set exclusively by an explicit
human-named reviewer) to runnable `RegressionTest`s, and an offline
evaluator that reuses Step 8's own `claim_verifier.verify_claim` /
`language_rules` / `numeric_verifier` unmodified rather than writing a
second verification pipeline.

**Claim identity without touching Step 8.** `story.models.NarrativeClaim`
has no standalone `claim_id` — Step 9 doesn't add one. Instead
`feedback.models.claim_key(story_id, section_index, claim_index)` is a pure,
derived reference string any caller can resolve back to a real claim
(`story.sections[i].statements[j]`) without Step 8 growing a new field.
Same posture for evidence/recommendation references: `EvidenceItem.
evidence_id` and `ActionRecommendation.recommendation_id` are cited
verbatim, never reinvented.

**Conflicting feedback is preserved, never arbitrated.** When two analysts
disagree (`review.contest_feedback()`), both `Feedback` records are marked
`CONTESTED` and a `ConflictRecord` stores both competing hypotheses side by
side — the system never silently picks a winner.

**Real demo run, all 5 required fixtures.** `scripts/step9_feedback_learning_demo.py`
walks CORRECT / wrong-driver / wrong-recommendation / wrong-confidence /
missing-driver feedback through all 9 pipeline stages. The wrong-driver
case is the spec's own worked example end-to-end: AI claims delivery
deterioration "coincided with" lower reviews (ASSOCIATION, already
correctly hedged) → analyst corrects the DRIVER to a November holiday
campaign → a regression test is created forbidding "delivery caused review
decline" → a deliberately-regressed candidate that reintroduces that exact
causal claim is caught and fails the regression test, proving the loop is
actually enforceable, not just recorded. The wrong-recommendation case
integrates Step 7 directly: an `EvaluationCase`'s `input_context` feeds
`decision.constraint_engine.evaluate_constraints()` unmodified
(`operational_capacity_available: False` → `BLOCKED`), and a candidate that
still ranks the recommendation `TOP` under that constraint fails offline
evaluation. A dataset-level baseline-vs-candidate comparison
(`evaluator.compare_baseline_candidate`) demonstrates the full "measure,
compare, human decides whether to deploy" loop — deployment is never
automatic. 93/93 Step 9 tests pass; zero regressions against Steps 1–8
(976 prior + 93 new = 1069 total).

An explicit AST-scan safety test (`tests/test_feedback_safety.py`, same
technique `tests/test_orchestrator.py` uses for Step 5's Orchestrator)
proves no file under `src/feedback/` imports a training/fine-tuning
library or calls anything resembling `fit()`/`train()`/`deploy()`; separate
tests prove feedback submission never mutates a live `NarrativeClaim`/
`EvidenceItem`/`ActionRecommendation` object it references.

Full detail: [STEP9_VALIDATION.md](STEP9_VALIDATION.md),
[docs/FEEDBACK_ARCHITECTURE.md](docs/FEEDBACK_ARCHITECTURE.md),
[reports/step9_validation.json](reports/step9_validation.json).

**Step 8 complete (2026-08-28): Persona-Aware KPI Storytelling.** The first
step where an LLM is a core component — but never the source of numerical
truth. `src/story/` (10 files): an `EvidencePackage` builder wrapping real
Step 4/6/7 objects (`EvidenceObject`, `CausalResult`, `ActionRecommendation`)
without recomputing any of their numbers, a new `ClaimType` epistemic axis
(FACT/ANALYTICAL_FINDING/ASSOCIATION/HYPOTHESIS/UNKNOWN) deliberately
distinct from Step 4's `EvidenceType`/`EvidenceTier`, a persona engine
(Executive/Finance/Operations/Marketing) with config-driven evidence
selection and ordering, a Narrative Planner and Evidence-Grounded Narrative
Generator (both LLM-backed via Step 5's `agents.llm_client`, both with a
fully deterministic fallback), and a claim-level verification pipeline
(evidence-ID validity, epistemic-type consistency, causal-language rules,
and a deterministic numeric verifier extending Step 5's guardrail with
currency K/M-suffix handling and unit-scoped evidence matching) that
independently re-checks every number before a story is ever returned — the
LLM is never asked "are these numbers correct?"

**Retry-with-feedback, never silent fallback on rejection.** A generated
narrative that fails verification triggers a regeneration attempt with an
explicit feedback message citing the exact failed claim and trusted value,
up to a configurable retry limit; persistent failure either falls back to
an explicitly-labeled deterministic template (itself re-verified) or raises
`StoryGenerationFailed`, per configuration — never a silently-presented
unverified narrative either way.

**Real demo run, all 4 required personas, one shared evidence package.**
Using the task's own exact example numbers (Revenue +52.1%, Orders +62.9%,
AOV -6.75%, Volume +R$417K, Mix -R$75.9K, Delivery +27.9%, Reviews -5.2%)
plus one Step 7 recommendation, all 4 personas generated independently
`APPROVED` stories with genuinely different section groupings/ordering
(Executive leads with business impact and actions; Finance leads with the
revenue bridge and explicitly never invents a margin figure it has no
evidence for; Operations leads with delivery/fulfillment; Marketing leads
with demand/orders) while every one of the 4 stories cites the identical
trusted numbers, independently re-verified. 105/105 Step 8 tests pass;
zero regressions against Steps 1–7.

Full detail: [STEP8_VALIDATION.md](STEP8_VALIDATION.md).

**Step 7 complete (2026-08-28): the Decision & Action Intelligence Engine.**
A governed, configuration-driven layer that answers "what should the
business do?" — never as an LLM freely generating advice like "improve
logistics," but as a structured pipeline: Driver → Controllable Lever →
Possible Action → Expected Impact → Owner → Constraints → Confidence →
Monitoring KPI. `src/decision/` (9 files): a business ontology loaded from
`config/decision_ontology.yaml` (2 drivers — delivery_delay, aov_decline —
extensible by pure YAML addition, no code change), a deterministic candidate
generator producing multiple template-based action alternatives per driver,
a constraint engine (budget/operational_capacity/inventory/geography/
decision_rights, each PASS/WARNING/BLOCKED), an impact estimator computing
`expected_impact = effect × addressable_population × confidence` and never
fabricating a missing input (marked `"unknown"` instead), a confidence
engine (weighted sum of driver_confidence/data_quality/historical_support/
action_link_strength, weights from `config/decision_scoring.yaml`),
controllability/effort/priority scoring (`priority = impact × confidence ×
controllability ÷ effort`, divide-by-zero guarded), a ranking pipeline
splitting recommendations into top/alternatives/conditional/blocked with an
explicit `ranking_explanation` citing real computed numbers, a monitoring-
plan builder, and an optional explanation layer whose LLM path (if wired in)
can only verbalize already-computed facts — never invent a number, checked
by the same numeric/causal-language guardrails Step 5 already established.

**Real demo run, both required scenarios.** Delivery delay (the task's own
exact input values: -8% observed change, 12,500 addressable shipments, +6pp
historical effect, 0.78 confidence) produced 5 candidate actions; top
recommendation "Prioritize high-value customer shipments," owned by
Operations Manager, `calculated_impact = 0.06 × 12,500 × 0.78 = 585.0`,
`priority_score = 1679.535` — a concrete, quantified action, never a generic
string. AOV decline (proving ontology extensibility) produced 4 candidates,
top recommendation "Adjust pricing on selected SKUs," owned by Pricing
Manager. 113/113 Step 7 tests pass; zero regressions against Steps 1–6.

Full detail: [STEP7_VALIDATION.md](STEP7_VALIDATION.md).

**Step 6 complete (2026-08-28): the Causal Analysis and Evidence-Tier
Engine.** A governed layer that answers "what's the strongest evidence tier
the data can defensibly support?" for a specific causal hypothesis — never
"is this causal?" for its own sake. `src/causal/` (9 files): a 12-check
eligibility gate (treatment/outcome exist, temporal order, sufficient
pre/post period, treatment/control variation, sample size, missingness,
confounders, consistent grain/KPI definition), a deterministic, no-LLM
method selector (PVM/DiD/ITS/CausalImpact/Descriptive/Experimental/None),
hand-rolled DiD (2×2 arithmetic + parallel-trends diagnostic) and
Interrupted-Time-Series (OLS segmented regression + autocorrelation +
concurrent-intervention checks) estimators, an optional CausalImpact probe
that never becomes a hard dependency, and a causal-language gate reusing
Step 5's existing regex rather than adding a third copy. PVM is Step 3D's
`decompose()` called unmodified, locked to `T2_ARITHMETIC` with no code path
able to call it causal.

**Real result on the 4 required November 2017 hypotheses: every one lands
at T1/T2 with `causal_claim_allowed=False`.** Order-volume routes to PVM
(exact Step 3D values reused). Category-growth and geographic both fail
eligibility outright — a product category or a customer's state is a
pre-existing group characteristic with no assignment timing, so
`treatment_precedes_outcome` hard-fails honestly. Delivery/review is the one
hypothesis with genuinely well-formed temporal order (October delivery
precedes November review) but has no clean treatment/control split and is
confounded by the same documented November 2017 Black Friday volume surge.
This is the task's own definition of success for a governed causal layer
applied to an observational dataset with no designed experiment — Step 5's
`causal_selector.py` reached the identical conclusion (never T3/T4 on this
data) by a completely different mechanism, which is itself a form of
cross-validation. The DiD/ITS code paths are independently proven correct
against synthetic constructed natural experiments, reaching a genuine
`T3_QUASI_EXPERIMENTAL`/`CAUSAL_SUPPORTED` result — so "Olist doesn't
support this" is a fact about the data, not a gap in the engine.

**One deliberate, additive touch to a "completed" step:**
`evidence.models.GRAPH_NODE_TYPES`/`RelationshipType` gained new members
(`CAUSAL_ANALYSIS`/`CAUSAL_RESULT`/`ASSUMPTION`/`DIAGNOSTIC` nodes;
`TESTED_BY`/`REJECTED_BY`/`HAS_ASSUMPTION`/`HAS_DIAGNOSTIC`/`UPGRADED_TO`/
`DOWNGRADED_TO` edges) so the causal engine can extend Step 4's evidence
graph — every pre-existing member's value is unchanged, verified by a
dedicated additive-only test.

72/72 Step 6 tests pass across all 7 required files. Full repository suite:
**758 tests pass, 0 regressions** against Steps 1–5.

Full detail: [STEP6_VALIDATION.md](STEP6_VALIDATION.md).

---

**Step 5 complete (2026-08-28): the Secure Multi-Agent Investigation Engine.**
Six agents investigate a KPI movement end-to-end — Orchestrator, Causal
Method Selector, and Confidence Judge are 100% deterministic (no LLM call
anywhere); Hypothesis, Evidence, and Counter-Evidence agents make real calls
to Groq (`openai/gpt-oss-20b`, provider-agnostic client) for the genuinely
interpretive work, with every tool call — from either side — routed through
one Tool Gateway chokepoint (Authentication → Authorization → Clearance
derivation → Input Validation → Execution → Output Validation → Audit).
Full detail: [STEP5_VALIDATION.md](STEP5_VALIDATION.md).

**LLM provider pivoted mid-implementation.** Originally scoped to call
Claude directly; the user supplied 17 Groq API keys partway through for
cost and asked for Groq specifically. This was a provider swap, not a
redesign — `agents/llm_client.py`'s `LLMClient` protocol was already
provider-agnostic. Two live-API surprises followed and were fixed: the
SDK's advertised default model (`llama-3.3-70b-versatile`) 404'd on every
one of the user's keys (switched to `openai/gpt-oss-20b`, verified live with
real tool-calling), and this account's 17 keys turned out to share one
8,000-tokens-per-minute quota at the organization level, not 17 independent
quotas (broadened exception handling + a rotation backoff, documented in
`STEP5_VALIDATION.md` §19 rather than hidden).

**Real end-to-end demonstration, not a mock.** The November 2017 revenue
investigation ran against the real Step 1–4 engines and a real Groq model:
the Hypothesis Agent made genuine tool calls (`compare_kpi`,
`get_driver_decomposition`, `get_concurrent_kpis`, `search_evidence`) and
proposed 3 diverse, evidence-grounded hypotheses; the numeric guardrail
caught and rejected a fabricated number live (and, separately, one genuine
false positive — a bare "2017" read as a business figure — found and fixed
during this run); the investigation then honestly `ABSTAINED` on both the
ANALYST and EXECUTIVE runs when evidence-gathering didn't converge within
budget, rather than manufacturing a confident answer from thin evidence.
Revenue movement matched the required 52.1% / R$346,051.94 exactly.

Building this also caught and fixed several real bugs beyond the LLM
plumbing: an uncaught `DriverRequestError`/`KPIRequestError` that could
crash the Tool Gateway, a PII-redaction gap in `get_evidence` (review text
was redacted at the retrieval layer but not when fetched directly by id), a
numeric-guardrail tolerance loose enough to let a fabricated number in the
same order of magnitude as a real one slip through, and a causal-language
regex that matched "caused by" but not bare "caused".

139/139 Step 5 tests pass (12 required test files; ~90% run against a fully
deterministic `FakeLLMClient`, no network, so the suite stays fast and
reproducible). Full repository suite: **686 tests pass, 0 regressions**
against Steps 1–4A.

**Step 4A complete, then corrected (2026-08-28).** Step 4 (Evidence Fabric) was
built and validated, but its retrieval evaluation revealed P@5≈0, P@10=0.017,
MRR=0.017 using multilingual-e5-small. Step 4A was a mandated deep-dive to
diagnose and fix that failure — without hiding or reclassifying it. That
diagnosis was itself revisited once a fresh HF token unblocked the remaining
Step 4A work (E5-base/large, cross-encoder reranking): comparing cached vs.
freshly re-encoded vectors exposed a real bug, not just an E5-small
limitation. Full writeup: `STEP4A_VALIDATION.md` §0.

**Actual root cause found 2026-08-28:** `EmbeddingCache.save()` persisted
orphaned vector rows left over from duplicate-text batches (427 of 5,019
reviews share identical short text, e.g. "Otimo produto"), while `_load()`
re-derives each key's array index positionally from the sorted keys list —
desyncing the key→vector mapping for most of the corpus on every disk
round-trip. `cache.get(key)` silently returned some *other* review's real
(but wrong) embedding instead of the requested one. Fixed in
`src/evidence/embeddings.py` (`put_many()`, `save()`); 2 new regression
tests added; the corrupted on-disk cache was rebuilt from scratch and
verified byte-identical to a fresh full-corpus re-encode.

**Step 4A findings (corrected):**
- Dense E5-small was never as broken as first measured: corrected MRR=0.333
  (was reported as 0.017 — the cache bug, not model weakness, explains most
  of that gap). BM25+expansion still wins overall, but by +17% MRR
  (0.389 vs. 0.333), not 19.6×.
- BM25 baseline implemented (MRR=0.389 with expansion, 0.9-1.0ms, <1MB memory)
  — still the recommended production retriever.
- Hybrid RRF implemented — still does NOT beat BM25-alone, even now that
  dense retrieval has genuine signal (a more robust finding than the
  original "noise dilutes signal" explanation, which assumed dense MRR=0).
- Query expansion adds +0.056 MRR with a governed bilingual synonym table.
- HF auth restored 2026-08-28: E5-base and E5-large were evaluated and both
  score *below* E5-small (MRR=0.190 vs. 0.333) — counter-intuitive, likely
  eval-set-size noise (6 queries), flagged as a hypothesis not a conclusion.
  Cross-encoder reranking (`amberoad/bert-multilingual-passage-reranking-msmarco`)
  ties E5-small's MRR at 450-500× the latency — not recommended either.
- RETRIEVAL_INSUFFICIENT sentinel implemented for the future Confidence Judge;
  its score floors were re-validated against the corrected numbers (no change
  needed).
- **Recommended production retriever: BM25 + query expansion (unchanged).**
- 547 tests pass (545 + 2 new regression tests), 0 regressions. Steps 2–3D
  untouched.

**(As of Step 4A: still no causal inference, LLM, agents, or frontend
anywhere — Step 5, above, added agents/LLM; Step 6, above that, added the
governed causal-analysis layer. Action recommendations, persona narratives,
feedback learning, and a frontend still don't exist.)**

---

## Timeline

| Step | What | Status | Key artifact |
|---|---|---|---|
| 1 | Raw data EDA + independent audit | ✅ Complete | [DATA_FOUNDATION_REPORT.md](DATA_FOUNDATION_REPORT.md) |
| 2 | Canonical data model + controlled cleaning | ✅ Complete | [STEP2_VALIDATION.md](STEP2_VALIDATION.md) |
| 3A | KPI semantic layer (definitions only) | ✅ Complete | [docs/KPI_SEMANTIC_LAYER.md](docs/KPI_SEMANTIC_LAYER.md) |
| 3B | Deterministic KPI computation engine | ✅ Complete | [STEP3B_VALIDATION.md](STEP3B_VALIDATION.md) |
| 3C | Materiality / anomaly detection engine | ✅ Complete | [STEP3C_VALIDATION.md](STEP3C_VALIDATION.md) |
| 3D | Driver decomposition engine (PVM + contribution) | ✅ Complete | [STEP3D_VALIDATION.md](STEP3D_VALIDATION.md) |
| 4 | Evidence Fabric (structured + unstructured RAG) | ✅ Complete | [STEP4_VALIDATION.md](STEP4_VALIDATION.md) |
| 4A | Retrieval failure analysis + BM25 + hybrid architecture | ✅ Complete | [STEP4A_VALIDATION.md](STEP4A_VALIDATION.md) |
| 5 | Secure Multi-Agent Investigation Engine | ✅ Complete | [STEP5_VALIDATION.md](STEP5_VALIDATION.md) |
| 6 | Causal Analysis and Evidence-Tier Engine | ✅ Complete | [STEP6_VALIDATION.md](STEP6_VALIDATION.md) |
| 7 | Decision & Action Intelligence Engine | ✅ Complete | [STEP7_VALIDATION.md](STEP7_VALIDATION.md) |
| 8 | Persona-Aware KPI Storytelling | ✅ Complete | [STEP8_VALIDATION.md](STEP8_VALIDATION.md) |
| 9 | Human Feedback & Learning Loop | ✅ Complete | [STEP9_VALIDATION.md](STEP9_VALIDATION.md) |
| — | Frontend/API | 🟡 Frontend exists, demo-mode only (untracked); no backend API yet | `frontend/` |

---

## Step 1 — Raw Data EDA + Repository/Data Foundation Audit

**Source data:** found and extracted `archive.zip` (the real Kaggle Olist
Brazilian E-Commerce dataset) into `data/raw/olist/` — 9 CSVs, 99,441 orders,
verified never modified since.

**What was built:** a first exploratory pass (`scripts/profile_olist.py`,
`kpi_temporal_eda.py`, `text_and_entity_eda.py`, `join_driver_anomaly_eda.py`,
notebook, `docs/EDA_REPORT.md` + 6 companion docs) followed by a **second,
independent audit** (`scripts/audit_raw_data.py`) that re-derived every headline
number from scratch rather than trusting the first pass — both agreed on every
recomputed figure, which is itself the finding worth remembering: the raw data
and both codebases are internally consistent.

**Headline findings that shaped everything after:**
- Order volume collapses at both edges of the raw date range (329 orders across
  all of 2016, 20 across Sept–Oct 2018) — later became the analytical-window
  decision in Step 2.
- Naively joining `orders ⋈ order_items ⋈ order_payments ⋈ order_reviews` before
  summing `price` inflates revenue (~4-4.5% depending on join shape) — became the
  anti-fan-out architecture in Step 2.
- `order_items.price` and `order_payments.payment_value` agree within 1 cent for
  99.61% of orders; the 0.39% gap concentrates in financed installment payments —
  became the CAUSA_REVENUE decision in Step 2.
- `order_reviews.review_id` is not a clean key (814 duplicates, 547 multi-review
  orders) — became the review-governance question resolved in Step 2.
- The dataset is pre-anonymized (no name/email/phone anywhere); 0 organic
  prompt-injection content found in review text.

Full detail: [DATA_FOUNDATION_REPORT.md](DATA_FOUNDATION_REPORT.md),
[REPOSITORY_AUDIT.md](REPOSITORY_AUDIT.md), [docs/EDA_REPORT.md](docs/EDA_REPORT.md).

## Step 2 — Canonical Data Model + Controlled Cleaning Layer

**What was built:** 10 canonical Parquet tables in `data/processed/` (3 dims, 4
facts at native grain, 3 explicit order-level aggregates), 5 build/analysis
scripts, 62 passing pytest tests, 6 new governance docs, raw data verified
untouched throughout (full clean rebuild reproduces identical output).

**Decisions made, each backed by a fresh quantitative pass (not copied from
Step 1):**
- **Analytical window: 2017-01 → 2018-08.** Derived by an explicit rule (<10% of
  median month's volume), cross-validated — 2018-09/10 turned out to be
  structurally incomplete (items coverage 6.25%/0%), not just low-volume.
- **CAUSA_REVENUE = `SUM(order_items.price)`**, never `payment_value`. The 381
  mismatches cluster almost perfectly by installment count (0 at 0 installments,
  rising with installments) — confirms financing interest, not a defect.
- **Review governance is use-case-specific**: `fact_reviews` keeps every raw row
  (for future retrieval); `agg_order_reviews.latest_review_score` (bias −0.073)
  is the order-level KPI default; `highest_review_score` was quantitatively
  disqualified (bias +0.376, cherry-picking).
- **Fan-out is structurally prevented**, not just documented — no fan-out-prone
  measure lives on `fact_orders`; `tests/test_fanout.py` proves the naive join
  inflates the total before proving the canonical path doesn't.
- **New finding**: 166 orders have `carrier_delivery_timestamp` before
  `purchase_timestamp` — investigated (121 within an hour, clock-skew; 2
  multi-day outliers), flagged `INVALID_SEQUENCE`, never silently dropped.
- **Geolocation excluded** from the canonical layer — `dim_customer`/`dim_seller`
  already carry clean state/city fields; geolocation has no usable key (26.18%
  exact duplicates).

Full detail: [STEP2_VALIDATION.md](STEP2_VALIDATION.md),
[docs/CANONICAL_DATA_MODEL.md](docs/CANONICAL_DATA_MODEL.md),
[docs/DATA_LINEAGE_V2.md](docs/DATA_LINEAGE_V2.md),
[docs/KPI_SEMANTICS_PREVIEW.md](docs/KPI_SEMANTICS_PREVIEW.md),
[docs/REVIEW_GOVERNANCE.md](docs/REVIEW_GOVERNANCE.md),
[docs/ANALYTICAL_WINDOW.md](docs/ANALYTICAL_WINDOW.md),
[docs/GEOLOCATION_DECISION.md](docs/GEOLOCATION_DECISION.md).

## Step 3A — KPI Semantic Layer

**What was built:** 10 governed KPI contracts (`config/kpis.yaml`) validated
against a JSON Schema (`schemas/kpi_contract.schema.json`) by a Python loader
(`src/kpi/semantic_registry.py`) that computes nothing — it only validates
structure and cross-contract governance rules. 30 new tests
(`tests/test_kpi_contracts.py`), 109 tests passing across the whole repo.

**The 10 KPIs:** Revenue, Orders, AOV, Average Delivery Days, Average Review
Score (primary) + Freight Revenue, Review Volume, On-Time Delivery Rate,
Quantity Sold, Repeat Purchase Rate (supporting).

**Decisions made:**
- **Dimension support is grain-checked per KPI, not assumed.** Item-grain KPIs
  (Revenue, Freight Revenue, Quantity Sold) safely support seller/product/category
  slicing (6/6 dimensions); order-grain KPIs (Orders, AOV, Delivery, Review Score,
  On-Time Rate) do NOT — an order can span multiple sellers/products (~9.86% of
  orders are multi-item), so those dimensions are explicitly marked unsupported
  with a documented reason rather than silently offered.
- **AOV's denominator is deliberately not the same population as the Orders
  KPI** — it's orders-with-item-data specifically, to avoid diluting AOV with
  revenue-less orders.
- **Average Review Score ships 3 explicit variants**, none silently
  interchangeable: order-level representative (default, latest-by-timestamp),
  order-level true average, and review-level average (no dedup).
- **Repeat Purchase Rate is grain-locked to `customer_unique_id`** — a governance
  test fails the build if `customer_id` is ever used instead.
- **Materiality is configuration only** (`implemented: false` on all 10, schema-
  enforced) — no anomaly engine exists yet; thresholds are informed defaults from
  Step 1's exploratory scan, not tuned.
- **Security**: every KPI value is `PUBLIC_ANALYTICAL`; `seller_id` is `INTERNAL`
  wherever it's a supported dimension; no contract exposes a raw customer
  identifier as a queryable dimension at all.

Full detail: [docs/KPI_SEMANTIC_LAYER.md](docs/KPI_SEMANTIC_LAYER.md),
[reports/kpi_semantic_validation.json](reports/kpi_semantic_validation.json).

## Step 3B — Deterministic KPI Computation Engine

**What was built:** `src/kpi/engine.py` (`KPIEngine`), `models.py`
(`KPIRequest`/`KPIResult`/`ComparisonResult`), `query_planner.py` (validates
every request against the Step 3A contract *before* touching data),
`cache.py` (deterministic hash-based computation cache). 122 new tests across
3 files; 231 tests pass repo-wide.

**Architecture**: `KPIRequest → SemanticRegistry → query_planner.plan()
(validation) → QueryPlan → KPIEngine._compute_<kpi_id>() → data/processed/*.parquet
→ KPIResult` — exactly the pipeline the task specified. Every result carries
full metadata (value, period, grain, dimensions, filters, sample_size,
coverage, data_quality, source, lineage, warnings) — never a bare number.

**Validated exactly, computed live (not hardcoded)**: Revenue Oct 2017 =
R$664,219.43, Nov 2017 = R$1,010,271.37, change = +R$346,051.94 (+52.1%);
Orders Oct = 4,631, Nov = 7,544 (+62.9%) — all reproduce from the canonical
Parquet tables via `KPIEngine.compute()`/`compare_periods()`.

**Decisions & findings:**
- **A real bug was found and fixed during this step**: dimension-grouping
  Revenue by `product_category` silently *undercounted* the total by
  R$14,115.98, because pandas' `groupby()` drops `NaN` group keys by default
  (610 products have no category). Fixed with `dropna=False`; a regression
  test (grouped results must sum to the ungrouped total) now guards this
  permanently.
- **Quantity Sold's "1 row = 1 unit" assumption was verified against real data
  before implementing**, per the task's explicit instruction not to fabricate
  it — confirmed a repeat-purchase-within-an-order produces 2 separate
  `order_item` rows with the same product and price, not a quantity field.
- **Dimension support is enforced exactly as Step 3A declared it**: item-grain
  KPIs (Revenue, Freight Revenue, Quantity Sold) support 6 dimensions;
  order-grain KPIs (Orders, AOV, Delivery, Review Score, On-Time Rate) support
  only 2 (month, customer_state) — item-grain dimensions raise
  `UnsupportedDimensionError` with the contract's own documented reason.
- **`repeat_purchase_rate`'s month/cohort dimension is explicitly refused**,
  not approximated — the contract itself documents no ready cohort query
  exists; the engine cites that rather than silently computing something
  wrong.
- **Comparison periods are pure arithmetic** — `ComparisonResult` carries no
  `is_anomaly`/`significant` field of any kind, verified by a test.

Full detail: [STEP3B_VALIDATION.md](STEP3B_VALIDATION.md),
[docs/KPI_COMPUTATION_ENGINE.md](docs/KPI_COMPUTATION_ENGINE.md),
[reports/step3b_validation.json](reports/step3b_validation.json).

## Step 3C — Materiality / Anomaly Detection Engine

**What was built:** `src/anomaly/` — `baseline.py` (6 methods: previous
period, rolling mean/median/std, EWMA, seasonal, plus an entity → category →
regional → global historical-sufficiency fallback ladder), `statistics.py`
(z-score, robust z-score/MAD, percentile — each with documented assumptions),
`materiality.py` (the decision model), `engine.py` (orchestrator). Answers
exactly one question: *"is this KPI movement sufficiently unusual and
materially important to justify launching an investigation?"* — never *why*.
81 new tests; 312 tests pass repo-wide.

**Decisions made:**
- **Materiality is a median of three independent evidence dimensions**
  (magnitude, statistical abnormality, business impact), each tiered
  NORMAL→CRITICAL against the KPI's own governed thresholds — not a product
  or a single threshold crossing. Requires at least two of three to agree
  before the verdict is elevated, so a KPI that swings +100% off a
  denominator of 1 is correctly held at WATCH, not CRITICAL.
- **Two independent, after-the-fact caps** (low baseline confidence, low
  current-period data quality) can only ever pull the verdict *down* to
  WATCH — logged with the specific number that triggered them, never hidden.
- **A sixth verdict, `BASELINE_DISAGREEMENT`**, fires when independent
  baseline methods (previous-period vs. rolling vs. seasonal) disagree by
  ≥2 severity tiers — the engine reports the conflict rather than silently
  picking a winner. Exempted when seasonal is the primary baseline, since a
  season-naive baseline is *expected* to diverge from a genuine seasonal peak.
- **A real 2-observation product** (real canonical data, not synthetic) is
  shown falling back from entity → category level, capped at MEDIUM
  confidence and WATCH verdict — never a high-confidence anomaly from 2 rows.
- **November 2017 revenue is classified CRITICAL** (z≈5.3), with no causal
  language anywhere in the result — verified by a regex scan over every
  string field of the serialized output, not just a documentation promise.
- **A design bug was found and fixed mid-build**: a fallback-level baseline's
  *value* is that level's own raw aggregate (e.g. a whole category's monthly
  total), not scaled to the entity's size — comparing a sparse product's
  R$153 sale against its category's R$30K aggregate produced a nonsensical
  −99% "movement." Fixed by attaching an explicit warning to every such
  result rather than presenting the coarse number as precise.

Full detail: [STEP3C_VALIDATION.md](STEP3C_VALIDATION.md),
[docs/MATERIALITY_ENGINE.md](docs/MATERIALITY_ENGINE.md),
[reports/step3c_validation.json](reports/step3c_validation.json).

## Step 3D — Driver Decomposition Engine

**What was built:** `src/drivers/` — `pvm.py` (Revenue = Price × Volume ×
Mix bridge), `contribution.py` (additive category/seller/geographic
decomposition), `ranking.py` (deterministic, absolute-contribution-based),
`engine.py` (orchestrator + a reconciliation guard that raises rather than
returns a non-reconciling result). Answers exactly one question: *"which
measurable factors mathematically account for this KPI movement?"* — never
*why*. 42 new tests; 354 tests pass repo-wide.

**Validated exactly, computed live**: October→November 2017 Revenue
decomposes to Volume +R$417,227.65, Price +R$4,674.63, Mix −R$75,850.34,
checksum error 0.0 — reproducing Step 1's independently-derived figures from
the canonical layer instead of raw CSVs. Category, seller, customer_state,
and seller_state contributions all reconcile exactly to the same
+R$346,051.94 total, computed independently of each other.

**Decisions made:**
- **Mix is a residual by construction** (`ΔRevenue − Volume − Price`), which
  is what makes the bridge reconcile *exactly* rather than approximately.
- **A documented, deliberate quirk kept bit-for-bit compatible with the
  validated numbers**: a category with no prior-period sales gets an implicit
  R$0 baseline price, so its entire revenue lands in "price effect," not
  "mix" — counter-intuitive, but changing it would change the required
  October→November 2017 result, so it's disclosed rather than "fixed."
- **Seller identity is clearance-gated** (`INTERNAL`) — omitted by default
  with a logged warning, hard error (`UnauthorizedSegmentError`) if
  explicitly requested without clearance.
- **`history_periods`/`confidence` are kept strictly separate from
  `contribution`** — a real November 2017 seller with zero prior history
  still ranks #2 by dollar contribution (+R$14,047.70) while correctly
  flagged `MEDIUM`, not `HIGH`, confidence.
- **Concurrent KPI movements** (Orders, AOV, Freight, Delivery, Review Score)
  are computed for the same period pair via the unmodified Step 3B engine and
  reported as plain arithmetic — never combined into a conclusion; this is
  the deterministic evidence package a future investigation layer would
  consume, not a finding in itself.
- **A real bug was found and fixed mid-build**: the validation script's own
  report-generation helper used a truthy short-circuit
  (`percentage_change and round(...)`) instead of an explicit `is None`
  check, silently hiding a valid `share_of_total_movement` for every
  brand-new entity (whose `percentage_change` is legitimately `None`).

Full detail: [STEP3D_VALIDATION.md](STEP3D_VALIDATION.md),
[docs/DRIVER_DECOMPOSITION.md](docs/DRIVER_DECOMPOSITION.md),
[reports/step3d_validation.json](reports/step3d_validation.json).

---

## Step 4 — Evidence Fabric (Structured + Unstructured RAG)

**What was built:** `src/evidence/` — full Evidence Fabric over the
October-November 2017 review corpus. Schema (`schema.py`, Pydantic strict
mode), structured adapter (`structured_adapter.py` — converts Step 3B/3C/3D
outputs into `EvidenceObject`s with zero pandas in the module), review
ingestion pipeline (`review_ingestion.py` — NFKC normalization, category
attribution with 4 confidence levels), language/PII/safety detection,
embedding (`embeddings.py` — E5-small, disk cache), vector index
(`vector_index.py` — FlatCosineIndex, brute-force cosine, exact), retrieval
(`retrieval.py` — structured-first mandatory pipeline, MMR diversity
reranking), evidence graph (`graph.py` — NetworkX, 39 nodes/29 edges),
access control (`access_control.py` — 3-level clearance). 130 new tests
across 9 files; 508 total pass.

**Findings:** All structured evidence (KPI movements, PVM, anomaly,
segments) reproduced the exact Step 3B/3C/3D numbers. 56 EvidenceObjects
built for the November 2017 package. **But retrieval metrics revealed:**
P@5=0, P@10=0.017, MRR=0.017 — honestly disclosed, not hidden. (Corrected
2026-08-28: mostly an `EmbeddingCache` bug, not model weakness — real
corrected numbers are P@5=0.067, MRR=0.333. See Step 4A below and
`STEP4A_VALIDATION.md` §0.)

Full detail: [STEP4_VALIDATION.md](STEP4_VALIDATION.md),
[docs/EVIDENCE_FABRIC.md](docs/EVIDENCE_FABRIC.md),
[docs/RAG_GOVERNANCE.md](docs/RAG_GOVERNANCE.md).

## Step 4A — Retrieval Failure Analysis and Optimization

**Trigger:** P@5≈0 and P@10=0.017 on the engineering eval set could not
be accepted as-is. Step 4A was a mandated diagnostic and remediation pass.

**What was found (2026-08-27, later corrected — see below):** All 10
diagnostic axes were audited. Believed root cause at the time: E5-small
cosine similarity gap between on-topic and off-topic short Portuguese
reviews is only ~0.05. For "atraso na entrega, demora" (delivery query),
the best on-topic score (0.904) is barely above off-topic generic reviews
(0.844-0.87). With 5,019 candidates and only 5 expected documents, this
gap looked insufficient. All 31 expected eval row_ids ARE in the index (0
missing). Every other pipeline component (prefix convention, normalization,
similarity direction, candidate restriction, ranking direction) was
verified correct.

**Corrected 2026-08-28:** that diagnosis was wrong. The actual root cause
was an `EmbeddingCache` disk-persistence bug — `save()` wrote orphaned
vector rows left over from duplicate-text batches (427 of 5,019 reviews
share identical short text), while `_load()` re-derives each key's index
positionally, desyncing the key→vector mapping on every reload for most of
the corpus. `cache.get(key)` silently returned a *different* review's real
embedding. Found by comparing cached vs. freshly re-encoded vectors row by
row while unblocking the E5-base/large/cross-encoder work below with a
fresh HF token. Fixed in `src/evidence/embeddings.py`; full writeup in
`STEP4A_VALIDATION.md` §0. The ~0.05 discrimination gap above is real (and
re-confirmed post-fix) but was never the dominant cause of the eval set's
near-zero score.

**What was built:**
- `src/evidence/bm25_retriever.py` — BM25+ index (k1=1.5, b=0.75, delta=1.0),
  Portuguese-aware tokenizer, bilingual stop-words, governed query expansion
  vocabulary (no LLM). Build: 36ms, query: 0.9ms.
- `src/evidence/retriever_interface.py` — EmbeddingProvider and Retriever
  protocols (injected, never hardcoded), RETRIEVAL_INSUFFICIENT sentinel.
- `src/evidence/dense_retriever.py` — DenseRetriever with E5EmbeddingProvider
  (model injected, supports E5-small/base/large via from_model_name()).
- `src/evidence/hybrid_retriever.py` — HybridRetriever (RRF, k=60),
  LexicalRetriever wrapper.
- `scripts/step4a_retrieval_benchmark.py` — full benchmark script.
- `tests/test_bm25.py` — 37 new tests.
- `STEP4_RETRIEVAL_DIAGNOSTIC.md` — concrete per-component audit.
- `STEP4A_VALIDATION.md` — this step's validation document.

**Benchmark results (6-query eval set, Oct-Nov 2017 corpus, corrected 2026-08-28
after the cache fix):**

| Method | P@5 | P@10 | MRR | Latency |
|---|---|---|---|---|
| Dense E5-small | 0.067 | 0.033 | 0.333 | ~1,087ms cold / ~20ms warm |
| Dense E5-base | 0.033 | 0.050 | 0.190 | ~28ms |
| Dense E5-large | 0.033 | 0.033 | 0.190 | ~45ms |
| **BM25** | **0.133** | **0.083** | 0.333 | **0.9ms** |
| **BM25 + expansion** | **0.133** | 0.083 | **0.389** | 1.0ms |
| Hybrid RRF | 0.067 | 0.083 | 0.296 | 14.9ms |
| Hybrid RRF + expand | 0.033 | 0.083 | 0.230 | 14.0ms |
| BM25+expand → CE rerank | 0.067 | 0.050 | 0.333 | 459.6ms |

*(Originally reported, superseded: "E5-small (Step 4)" 0.000/0.017/0.017 at
1,284ms and "Dense E5-small" 0.000/0.000/0.000 — both were reading a
corrupted embedding cache, see `STEP4A_VALIDATION.md` §0.)*

**Key finding (corrected):** BM25+expansion (MRR=0.389) outperforms dense
E5-small by +17%, not 22× — dense retrieval was never as broken as first
measured. Hybrid RRF still does NOT beat BM25-alone, even now that dense
has genuine signal — a more robust finding than the original explanation
assumed. E5-base/E5-large both score *below* E5-small (unexpected; may be
eval-set-size noise). Cross-encoder reranking ties E5-small's MRR at
450-500× the latency. **Recommended production retriever: BM25 + query
expansion (unchanged).**

547 tests pass (37 new in Step 4A + 2 new regression tests for the cache
bug, 0 regressions). Steps 2–3D unchanged.

Full detail: [STEP4A_VALIDATION.md](STEP4A_VALIDATION.md),
[STEP4_RETRIEVAL_DIAGNOSTIC.md](STEP4_RETRIEVAL_DIAGNOSTIC.md),
[reports/step4a_retrieval_benchmark.json](reports/step4a_retrieval_benchmark.json).

---

## Step 5 — Secure Multi-Agent Investigation Engine

**What was built:** `src/agents/` (11 files) and `src/tools/` (5 files) — a
six-agent investigation pipeline sitting on top of the Evidence Fabric,
governed by a single Tool Gateway chokepoint.

- **Orchestrator** (`orchestrator.py`, deterministic) — drives a 9-state
  state machine (`state_machine.py`) through PLANNED → SECURITY_VALIDATED →
  HYPOTHESES_GENERATED → EVIDENCE_COLLECTION → COUNTER_EVIDENCE →
  CONTRADICTION_ANALYSIS → METHOD_SELECTION → CONFIDENCE_EVALUATION →
  COMPLETED (or ABSTAINED / NEEDS_CLARIFICATION / BUDGET_EXCEEDED /
  SECURITY_BLOCKED), never generating a business conclusion itself
  (AST-scanned to prove it).
- **Hypothesis / Evidence / Counter-Evidence Agents** (LLM-backed, real
  calls to Groq via `agents/llm_client.py`'s provider-agnostic
  `LLMClient` + a manual tool-use loop) — formulate diverse hypotheses,
  decide what evidence to request, classify it, and adversarially search
  for what would prove each hypothesis wrong.
- **Causal Method Selector / Confidence Judge** (`causal_selector.py`,
  `confidence_judge.py`, both 100% deterministic) — select
  T1_DESCRIPTIVE/T2_ARITHMETIC/INSUFFICIENT_DATA (never T3/T4 — this
  dataset has no natural experiment) and score HIGH/MEDIUM/LOW/ABSTAIN/
  NEEDS_CLARIFICATION, with hard caps so weak evidence can't reach HIGH and
  a STRONG contradiction can't reach HIGH either.
- **Tool Gateway** (`tools/gateway.py`) — Authentication → Authorization
  (fixed per-role tool allowlist) → Clearance derivation (RBAC, never
  agent-supplied) → Input Validation → Execution → Output Validation →
  Audit, for every tool call regardless of whether an LLM or deterministic
  code proposed it.
- **RBAC**: `EXECUTIVE`→`PUBLIC_ANALYTICAL`, `ANALYST`→`INTERNAL`,
  `INTERNAL`→`RESTRICTED`, reusing Step 4's existing clearance scale.
- **Guardrails**: a numeric guardrail (every cited number must trace to a
  real tool result), a causal-language guardrail (no agent output may
  assert causation), and an `<UNTRUSTED_EVIDENCE>` boundary around every
  retrieved review before it reaches the model.

**LLM provider: Groq, not Anthropic — a deliberate pivot mid-build.** The
user supplied 17 Groq API keys and asked for Groq specifically (cost). Keys
live in a local, gitignored `.env`, round-robined by `GroqKeyPool`. Two
live-API issues were found and fixed: the SDK's advertised default model
404'd on every one of the user's keys (switched to `openai/gpt-oss-20b`,
verified live with real tool-calling), and the account's 17 keys share one
8,000 TPM quota at the organization level, not 17 independent ones
(broadened exception handling + rotation backoff).

**Real end-to-end demonstration:** `scripts/step5_investigate_november_2017.py`
ran a real investigation (`dry_run: false` in `reports/step5_validation.json`)
against the real Step 1-4 engines and real Groq calls. The Hypothesis Agent
made genuine tool calls and proposed 3 diverse hypotheses (mix/customer_state,
freight_revenue, orders/customer_state); the numeric guardrail rejected a
fabricated number live, and separately caught its own false positive (a bare
"2017" read as a business figure — found and fixed during this run); both
the ANALYST and EXECUTIVE investigations honestly `ABSTAINED` when
evidence-gathering didn't converge within budget, rather than manufacturing
a conclusion. Revenue movement matched exactly: +52.1% / R$346,051.94.

**Bugs found and fixed while building this:** an uncaught
`DriverRequestError`/`KPIRequestError` that could crash the Tool Gateway; a
PII-redaction gap in `get_evidence` (redacted at retrieval, not when
fetched directly by id); a numeric-guardrail tolerance loose enough to miss
a same-order-of-magnitude fabrication; a causal-language regex that missed
bare "caused"; the bare-calendar-year false positive above.

139/139 Step 5 tests pass (12 files, ~90% via a fully deterministic
`FakeLLMClient` — no network needed for the suite to be reproducible). 686
total tests pass, 0 regressions against Steps 1-4A.

Full detail: [STEP5_VALIDATION.md](STEP5_VALIDATION.md),
[docs/MULTI_AGENT_ARCHITECTURE.md](docs/MULTI_AGENT_ARCHITECTURE.md),
[docs/AGENT_SECURITY.md](docs/AGENT_SECURITY.md),
[docs/INVESTIGATION_PROTOCOL.md](docs/INVESTIGATION_PROTOCOL.md),
[reports/step5_validation.json](reports/step5_validation.json).

---

## Step 6 — Causal Analysis and Evidence-Tier Engine

**What was built:** `src/causal/` (9 files) — `models.py` (`CausalHypothesis`,
`CausalTier`/`EligibilityVerdict`/`CausalMethod`/`CausalStatus` enums,
`EligibilityReport`, `MethodSelectionResult`, `CausalResult`), `eligibility.py`
(12 checks, always run, always fixed order, rolling up to
ELIGIBLE/PARTIALLY_ELIGIBLE/INELIGIBLE/CAUSAL_INELIGIBLE),
`method_selector.py` (a fixed-order decision table over 7 methods, no LLM
import), `did.py` (2×2 arithmetic + a hand-rolled parallel-trends
diagnostic), `interrupted_series.py` (OLS segmented regression +
autocorrelation + concurrent-intervention checks), `causal_impact.py` (an
optional-dependency probe that never becomes a hard requirement),
`diagnostics.py` (shared OLS/autocorrelation utilities + the confounder
registry), `language_gate.py` (reuses Step 5's causal-language regex),
`engine.py` (the single entry point + evidence-graph integration). 72 new
tests across the 7 required files.

**Governing principle carried forward, made mechanical:** "LLM proposes
hypotheses. Deterministic/statistical systems test them. LLM cannot declare
causality." No file in `src/causal/` imports an LLM client anywhere — an AST
scan across every module in the package proves it, mirroring the same
technique `tests/test_orchestrator.py` already used for Step 5's
Orchestrator.

**Three tier enums kept deliberately distinct, not conflated:**
`evidence.models.EvidenceTier` (per-evidence-item quality, Step 4),
`agents.models.AnalyticalMethod` (Step 5's hypothesis-support rigor label),
and the new `causal.models.CausalTier` (what one specific method run can
defensibly support after eligibility + diagnostics, Step 6) — a DiD run can
compute a T3-shaped estimate that gets capped back down to T1 because
parallel trends failed, a judgment neither of the other two enums has any
vocabulary for.

**Real result on the 4 required November 2017 hypotheses** (all real data,
`scripts/step6_causal_validation.py`):

| Hypothesis | Verdict | Method | Tier | `causal_claim_allowed` |
|---|---|---|---|---|
| C1 order-volume | PARTIALLY_ELIGIBLE | PVM | T2_ARITHMETIC | false |
| C2 category-growth | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | false |
| C3 delivery/review | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | false |
| C4 geographic | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | false |

Order-volume cites 48 real Step 4 evidence_ids and reproduces Step 3D's
exact PVM values (`volume_effect=417227.65`, `price_effect=4674.63`,
`mix_effect=-75850.34`) via `drivers.engine.decompose()` called unmodified.
Category-growth and geographic both fail on `treatment_precedes_outcome` —
a product category or a customer's state is a pre-existing group
characteristic with no assignment timing, so temporal order cannot be
established; the eligibility checker catches this by construction, not by
an arbitrary threshold. Delivery/review is the one hypothesis with a
genuinely well-formed temporal order (October delivery precedes November
review — the check **passes**) but fails on `control_variation` (no clean
group split for a continuous delivery-rate KPI) and honestly reports the
documented November 2017 Black Friday volume surge as a confounder rather
than ignoring it.

**This is the task's own definition of success, not a shortfall**: a
governed causal layer applied to an observational dataset with no designed
experiment is *supposed* to land here. Step 5's `causal_selector.py` reached
the same "never T3/T4 on this dataset" conclusion through a completely
different, LLM-adjacent mechanism — the two independent systems agreeing is
itself a form of cross-validation. To prove the DiD/ITS machinery itself is
correct (not just conservative), both are separately exercised against
small **synthetic** constructed natural experiments and genuinely reach
`T3_QUASI_EXPERIMENTAL`/`CAUSAL_SUPPORTED` — so "Olist doesn't support a
causal claim here" is demonstrably a fact about the data, not a limitation
of the engine.

**One deliberate, additive touch to a "completed" step:** Step 4's
`evidence.models.GRAPH_NODE_TYPES` gained 4 new members
(`CAUSAL_ANALYSIS`/`CAUSAL_RESULT`/`ASSUMPTION`/`DIAGNOSTIC`) and
`RelationshipType` gained 6 (`TESTED_BY`/`REJECTED_BY`/`HAS_ASSUMPTION`/
`HAS_DIAGNOSTIC`/`UPGRADED_TO`/`DOWNGRADED_TO`), needed so
`engine._extend_graph()` can wire a `CausalResult` into the existing
evidence graph. Purely additive — no pre-existing member's value changed,
verified by a dedicated test that snapshots the frozenset/enum before
asserting Step 6's new members are simply present alongside them.

**Confounder policy, made an assertion, not just a convention:**
`diagnostics.report_confounders_never_controlled()` raises if any
`ConfounderReport.controlled_for` is ever `True` — no method in this version
implements covariate adjustment, so claiming a confounder was "controlled
for" merely because it appears in the data would be a false governance
claim. The literal implementation of the task's own words: "Do not claim
they were controlled merely because they exist in the data."

72/72 Step 6 tests pass. Full repository suite: **758 tests pass, 0
regressions** against Steps 1–5 (686 prior + 72 new).

Full detail: [STEP6_VALIDATION.md](STEP6_VALIDATION.md),
[docs/CAUSAL_ARCHITECTURE.md](docs/CAUSAL_ARCHITECTURE.md),
[docs/CAUSAL_METHOD_SELECTION.md](docs/CAUSAL_METHOD_SELECTION.md),
[docs/CAUSAL_GOVERNANCE.md](docs/CAUSAL_GOVERNANCE.md),
[reports/step6_validation.json](reports/step6_validation.json).

---

## Running list of things intentionally left undone (don't rediscover these as surprises)

- No profit/margin KPI — no cost-of-goods field exists anywhere in the source data.
- No marketing-attribution KPI — no channel/spend/campaign data exists.
- No true customer LTV — only 3.12% of unique customers repeat, and there's no
  margin data to net against revenue.
- Geolocation is not in the canonical layer (see Step 2).
- `order_status` default filtering for "recognized revenue" is an open question,
  deliberately exposed as a filter rather than decided (see Step 3A).
- No backend HTTP/REST/GraphQL API exists yet (Steps 1-9 are all
  Python-callable, matching the task's own "don't introduce a UI/API unless
  one already exists" instruction) — `frontend/src/api/productionApi/`
  is a documented empty stub for when one does. A frontend UI does now
  exist on disk (`frontend/`, see the 2026-08-29 session note above) but
  runs entirely off static demo fixtures, is not yet committed to git, and
  has never been wired to a live backend call. Step 6 added causal inference EXECUTION
  (`src/causal/` — eligibility, method selection, DiD/ITS/CausalImpact
  estimators) on top of Step 5's Causal Method Selector (which only ever
  *selected* a rigor label and never ran an estimation procedure of its
  own). Step 7 added action recommendations, Step 8 added persona-specific
  narratives, Step 9 added the feedback/evaluation loop.
- Step 9's `EvaluationCase`/`RegressionTest` machinery is a general-purpose
  offline evaluator, but the demo's `candidate_runner` callables are
  hand-built stand-ins (`CandidateOutput(...)` literals) rather than live
  wrappers around `story.engine.generate_kpi_story()` / a re-run Step 7
  pipeline — wiring a real end-to-end candidate_runner against the live
  generator is natural future work, deliberately left open since it
  requires a live LLM call to be interesting (this demo runs
  `llm_client=None` throughout for reproducibility, same as Steps 7/8).
- Step 9's review workflow (`review_feedback`) supports exactly one
  reviewer per decision — `config/feedback.yaml`'s
  `review_workflow.min_approvals_required` is documented but not enforced
  in code (this repo has no multi-user session concept yet to count
  distinct reviewers against).
- `causal.did._build_did_inputs` (Step 6, called from `engine.py`) only
  assembles a single pre/post value pair from canonical data, not a real
  multi-period pre-trend series — so `did.py`'s parallel-trends diagnostic
  fails by default whenever engine.py drives it against real data (it is
  proven correct against synthetic multi-period fixtures instead). Building
  the same monthly panel `interrupted_series._build_its_inputs` already
  constructs, grouped by treatment/control value, is the natural next step.
- `causal_impact.py` (Step 6) has no installed Bayesian structural
  time-series package to call into — `requirements.txt` carries none by
  design (task explicitly says "do not make it a hard dependency"), so every
  real run takes the `METHOD_UNAVAILABLE` branch today.
- The KPI engine (Step 3B) cannot compute `repeat_purchase_rate` by cohort
  month (no ready query, by design) or `avg_review_score`'s `review_level_average`
  variant grouped by dimension (not built) — both raise explicit errors
  rather than approximate an answer.
- PVM decomposition (Step 3D) is Revenue-only — Price × Volume × Mix is only
  meaningful for a SUM-of-price KPI; generalizing it to other KPIs is future
  work.
- Step 5's Evidence Agent did not converge to a classification within its
  per-hypothesis tool-iteration budget in the captured real demonstration
  run (the model kept exploring rather than concluding) — global budgets
  were not exhausted, so this is a per-agent-call loop-size tuning question,
  not a hard system limit. See `STEP5_VALIDATION.md` §19.
- Step 5 has no adaptive re-invocation loop — each of the six agents runs
  exactly once per investigation; the Orchestrator never re-invokes Evidence/
  Counter-Evidence with a targeted follow-up when confidence comes back thin.
- `tools/context.build_tool_context()` (Step 5) builds the review corpus/
  index twice internally (reuses two separate Step 4 functions rather than
  one combined one) — a known, documented inefficiency, not hidden.

## How to pick this back up

1. Read this file top to bottom.
2. Read the most recent step's own validation doc in full (currently
   [STEP9_VALIDATION.md](STEP9_VALIDATION.md)).
3. Reproduce the current state if needed:
   ```bash
   python scripts/step2_04_build_canonical.py     # rebuild data/processed/
   python -m pytest tests/ -q                      # should show 1069 passed, 0 failed
   python scripts/step3b_validate_engine.py        # Nov 2017 KPI numbers should match exactly
   python scripts/step3c_validate_engine.py        # Nov 2017 anomaly verdict should be CRITICAL
   python scripts/step3d_validate_engine.py        # Nov 2017 PVM numbers should match exactly
   python scripts/step4_validate_engine.py         # rebuilds the Evidence Fabric package
   python scripts/step5_investigate_november_2017.py  # needs GROQ_API_KEYS in causa/.env for a
                                                        # real LLM run; falls back to a clearly-
                                                        # labeled dry run otherwise
   python scripts/step6_causal_validation.py       # runs the 4 required Nov 2017 causal
                                                        # hypotheses; every one should land at
                                                        # T1/T2 with causal_claim_allowed=false
   python scripts/step7_decision_engine_demo.py    # runs the decision/action pipeline demo
   python scripts/step8_persona_storytelling_demo.py  # generates all 4 persona KPI stories
   python scripts/step9_feedback_learning_demo.py  # runs the 5 required feedback fixtures through
                                                        # the full capture -> classify -> correct ->
                                                        # evaluate -> regression-test loop
   ```
4. Update this file's "Where we are right now" section and add a new entry to
   the Timeline table at the end of whatever step comes next.
