# Materiality and Anomaly Detection Engine — Step 3C

Turns a KPI movement (an observed value plus its history) into an explicit
answer to one question: **"is this movement sufficiently unusual and
economically meaningful to warrant an investigation?"** It distinguishes
NORMAL / WATCH / MATERIAL / CRITICAL / INSUFFICIENT_DATA /
BASELINE_DISAGREEMENT, and never equates a raw percentage change with an
anomaly.

**No PVM, causal inference, RAG, LLM, agents, recommendations, or frontend
exist in this module.** This engine does not, and structurally cannot, answer
*why* a movement happened — see §8.

---

## 1. Architecture

```
AnomalyRequest (models.py)
    │  observed value + a fallback ladder of historical PeriodObservations
    ▼
SemanticRegistry.get(kpi_id)          -- the Step 3A contract, unmodified
    │  (semantic.py reads materiality.* and aggregation into typed config)
    ▼
baseline.select_level()                -- historical sufficiency (§2)
    │
    ▼
baseline.compute_baselines()           -- baseline engine (§1)
    │
    ▼
statistics.{z_score, robust_z_score,   -- statistical abnormality (§4)
             percentile_rank}
    │
    ▼
materiality.compute_business_impact()  -- business impact (§5)
materiality.classify_persistence()     -- persistence (§6, informational)
materiality.decide()                   -- the decision model (§8/§9)
    │
    ▼
AnomalyResult (models.py)              -- every number that fed the verdict,
                                           never just the verdict
```

Every module stays pandas-free and depends only on plain dataclasses
(`PeriodObservation`, `BaselineLevel`, `AnomalyRequest`) — exactly the
discipline `kpi.query_planner` keeps relative to `kpi.engine`. Whoever builds
the history (`scripts/step3c_validate_engine.py`, using `kpi.engine.KPIEngine`
in this repo) is free to source it from live KPI computation, a cached report,
or synthetic test fixtures; the engine does not care which, and does not
import `kpi.engine` itself.

## 2. Historical sufficiency and the fallback ladder

A `BaselineLevel` is usable only if it clears **two independent bars**:

1. **Enough periods** to compute a baseline at all — at least 3 non-null
   historical points (the floor `rolling_mean`/`rolling_std` need; weaker
   methods like `previous_period`/`ewma` need fewer, but a level that clears
   this bar can support the stronger methods too).
2. **Enough underlying observations** — `sum(sample_size)` across that
   level's history must meet the KPI's own contract
   `materiality.minimum_observations` (e.g. 30 for Revenue, 100 for Repeat
   Purchase Rate). This is deliberately a **data-sufficiency gate, not a
   per-kpi_id lookup table**: whether a baseline is trustworthy is a function
   of how much history exists for *this specific entity/kpi combination*, not
   an intrinsic property of the kpi_id alone. A product-level Revenue slice
   with 2 historical rows cannot support a rolling std baseline even though
   Revenue overall (tens of thousands of rows/month) can.

`select_level()` walks the caller-supplied ladder (`entity → category →
regional → global`, most-specific first) and returns the first level clearing
both bars, carrying a `fallback_reason` that names every level it skipped
(e.g. `"entity, category_history_insufficient"`). If **no** level clears the
bars — including the global rung — the result is `INSUFFICIENT_DATA`, never a
fabricated baseline (task's explicit instruction: *"Never produce a
high-confidence anomaly from two observations"*).

**Confidence depends on whether a fallback actually happened, not on the
level's name.** A whole-of-business KPI (Revenue with no dimension slice)
legitimately supplies a single `"global"` level as its only and most-specific
rung — a healthy amount of platform-wide history there is genuine HIGH
confidence, not a degraded fallback. Confidence is downgraded only when a
level was reached *because* a more specific one proved insufficient:

| Reached via | Healthy history (≥6 periods) | Thin history |
|---|---|---|
| No fallback (first level supplied was sufficient) | HIGH | MEDIUM |
| Fallback (a more specific level was insufficient) | MEDIUM | LOW |
| No level anywhere was sufficient | — | NONE |

**Known limitation, disclosed not hidden**: when a fallback occurs, the
selected level's baseline *value* is that level's own raw aggregate (e.g. a
whole `product_category`'s monthly revenue total), not an estimate scaled down
to the entity's typical size. Comparing a single sparse product's R$153 sale
against its category's ~R$30K monthly total produces a `movement.percentage`
of roughly −99%, which is a coarse, different question ("how does this
entity's raw value compare to the category's raw aggregate") than "is this
entity unusual for an entity like it." The engine never hides this — every
such result carries an explicit warning (*"Baseline was computed at the
'{level}' level (fallback: ...) — its value is that level's own aggregate,
not scaled to this entity's typical size"*), and it is exactly why confidence
is never HIGH at a fallback level and the verdict is capped at WATCH once the
current period's own tiny sample size is also accounted for (§7). A true
per-entity-normalized fallback baseline is future work, not attempted here.

## 3. The baseline engine (§1)

Six methods, each computed independently when its own minimum-points bar is
cleared (`all_methods` on every `AnomalyResult` exposes every one that could
be computed, for transparency):

| Method | Minimum points | Notes |
|---|---|---|
| `previous_period` | 1 | The weakest baseline — a single observation. Never the sole basis for MATERIAL/CRITICAL on its own (the disagreement check, §9, guards this). |
| `rolling_mean` | 3 | Trailing window (default 6 months). |
| `rolling_median` | 3 | Reported alongside rolling_std for the robust z-score. |
| `rolling_std` | 3 | Sample std (ddof=1); withheld (not "computed from 2 points") below 3. |
| `ewma` | 2 | α = 2/(span+1) — reacts faster than rolling_mean, useful for thin-but-growing entities. |
| `seasonal` | 2 prior cycles | Mean of the same calendar month across ≥2 prior years. Requires real evidence of a pattern, not one occurrence. |

**Which one is "the" reported baseline** is chosen by a documented priority:
`seasonal > rolling_mean > ewma > previous_period`. Seasonal is preferred
whenever computable specifically because task §10 requires predictable
seasonal behavior to not be flagged as abnormal — comparing like-for-like
calendar periods is the most appropriate baseline whenever there is evidence
to do it. Given Causa's ~2-year dataset (`docs/ANALYTICAL_WINDOW.md`), seasonal
is frequently *not* computable in practice (fewer than 2 full prior cycles
exist for most of the reliable window) — the engine reports this honestly
(`seasonal: null` in `all_methods`) rather than fabricating a pattern from one
occurrence.

## 4. Statistical abnormality (§4)

Three signals, each with a documented assumption (see
`statistics.assumptions_note`, attached verbatim to every result):

- **z-score**: `(observed − rolling_mean) / rolling_std`. Assumes an
  approximately symmetric distribution; a heuristic magnitude-of-surprise
  measure, **not a formal significance test** — the docstring and the result's
  own `assumptions` list say so explicitly, per the task's instruction not to
  claim significance just because z > threshold.
- **robust z-score**: `0.6745 × (observed − median) / (1.4826 × MAD)`. Less
  sensitive to one outlier history point than z-score. The two are expected to
  broadly agree; `StatisticalSignals.signals_agree` flags when they diverge by
  more than 1 (itself informative — skewed/outlier-contaminated history, not
  necessarily a real signal).
- **percentile**: purely empirical rank within history, no distributional
  assumption at all, but unstable with few points (caveated below n=10, and
  simply not computed below n=3).

## 5. Business impact (§5)

`kpi_kind` is read from the contract's `aggregation` field (`semantic.py`),
never guessed:

- **additive** (`SUM`/`COUNT`/`COUNT_DISTINCT` — Revenue, Orders, Freight
  Revenue, Quantity Sold, Review Volume): `magnitude = observed − baseline`,
  reported as a plain total in the KPI's own unit.
- **rate_or_average** (`RATIO`/`DERIVED_RATIO`/`MEAN` — AOV, Average Delivery
  Days, Average Review Score, On-Time Delivery Rate, Repeat Purchase Rate):
  the same `observed − baseline` delta is computed, but the interpretation
  text explicitly states *"not a monetary total"* and reports
  `affected_population`/`denominator` (the current period's sample size)
  alongside it — never presented as if it were a dollar figure. Example
  (November 2017, live): Revenue → *"Revenue moved by +460,315.70 versus its
  baseline"*; Average Review Score → *"... moved by −0.2130 (its own unit, not
  a monetary total) across 7,480 underlying observations this period."*

## 6. Persistence (§6) — informational, never gates the verdict

Five classes: `ONE_OFF` (didn't carry into the next period — settled back
within normal range), `REVERSING` (the next period overshot materially in the
*opposite* direction — a genuine reversal, distinct from settling back),
`PERSISTENT` (carried into ≥1 subsequent period, same direction),
`TRENDING` (carried in, and the magnitude kept growing), `UNKNOWN` (no
subsequent-period data supplied yet, or it's null). Persistence is attached
to every result but **never used to gate the materiality verdict** — task §6
is explicit that a one-day revenue shock can still be material, and the test
suite (`test_10_one_off_shock_can_still_be_material`) enforces this: a
synthetic one-off shock the size of the real November 2017 movement still
reaches MATERIAL/CRITICAL even though it settles back the following period.

## 7. Data quality (§7) — never hidden

Two independent checks, both surfaced (never silently absorbed into a lower
score):

- **Current-period quality**: the observed value's own `sample_size` below
  the contract's `minimum_observations`, or `coverage` below the contract's
  `data_quality_requirements.coverage_threshold_pct` (the same field
  `kpi.engine`'s HIGH/MEDIUM/LOW tiering already uses — one coverage rule
  across the whole codebase, not two divergent ones).
- **Baseline quality**: `baseline_confidence` (§2).

Either one being poor **caps the verdict at WATCH**, applied *after* the
tier combination (§8) — not folded into it, so a data-quality problem can
never masquerade as evidence. Every cap is logged in
`materiality.reasons` with the specific number (e.g. *"Current period sample
size (1) is below the contract's minimum_observations (30)"*).

## 8. The materiality decision (§8/§9/§13) — design rationale

**This is not a multiplication of dimensions**, per the task's explicit
instruction. Three independent evidence dimensions are scored 0–3
(NORMAL/WATCH/MATERIAL/CRITICAL as ordinals) using thresholds read from the
KPI's own contract (`absolute_threshold`, `relative_threshold`,
`statistical_threshold`, `minimum_business_impact` — all still `config/
kpis.yaml`'s Step 3A values, informed by `docs/INVESTIGATION_SCENARIOS.md`'s
exploratory 15% scan, still not statistically tuned or backtested — same
posture as the shared `materiality_note` those contracts already carry):

- **magnitude** — is the raw move large relative to this KPI's configured
  absolute/relative thresholds? Either can trigger it alone (Revenue's
  +R$300K example, §3), which is deliberate.
- **statistical** — is the move large relative to *this KPI's own historical
  variability* (max of |z|, |robust z|, vs. `statistical_threshold`)?
- **business impact** — is the move large relative to
  `minimum_business_impact`?

**Combination: the median of the three tiers.** Not the max, not a weighted
product. The median has one specific, load-bearing property: it takes **at
least two of the three independent dimensions agreeing** to reach a given
severity. A KPI that swings 100% in percentage terms off a denominator of 1
(magnitude tier high) but shows no statistical abnormality and no real
business impact (both low) is correctly held to WATCH, not MATERIAL — task
§3's *"a small product: +100% may be statistically meaningless"* case,
verified live (`test_5_large_percentage_movement_tiny_sample_...`). A
genuinely broad movement like November 2017 (large in all three dimensions:
tier 3/3/3 computed live) is not held down by any single dimension's
idiosyncrasy.

**`score` (0–1) is the raw, uncapped combination** (`(tier_m + tier_s +
tier_b) / 9`) — a continuous transparency signal, reported on every result
even when the verdict itself is capped. This is deliberate: a WATCH verdict
with `score: 0.889` (the sparse-product case, §12/§18) tells a reader *"the
evidence pattern looks strong, but we don't have enough confidence in the
underlying data to act on it as high-confidence"* — the score and the verdict
answer two different questions, and neither is hidden from the other.

**Baseline disagreement (§9/§13) runs before the tier combination.**
Independent baseline methods' magnitude tiers (the primary method, plus
`previous_period` and `seasonal` when they differ from primary) are compared;
if they span ≥2 tiers (e.g. one reads NORMAL, another reads MATERIAL), the
verdict is `BASELINE_DISAGREEMENT` and the engine stops — it does not pick a
winner among disagreeing baselines. **Exception**: when `seasonal` is the
primary baseline, a season-naive baseline (`previous_period`) is *expected* to
diverge for a genuine seasonal peak — that divergence is the definition of
seasonality (§10), not evidence of uncertainty, so it is exempted from
triggering disagreement. Both behaviors are verified live
(`test_11_contradictory_baselines_...`, `test_8_seasonal_peak_...`).

## 9. Threshold configuration

Every number that decides a verdict is read from `config/kpis.yaml`'s
Step 3A `materiality` block at runtime (`semantic.py` is the one place that
reads those field names, mirroring `kpi.engine`'s own contract-reading
discipline) — **nothing here is a hardcoded per-KPI constant**. The
tier-multiplier ladders (how many multiples of the configured threshold reach
WATCH/MATERIAL/CRITICAL — `1×/2×/4×` for magnitude and business impact,
`1×/1.5×/2.5×` for statistical) are engine-level configuration, documented and
centralized in `materiality.py`'s module constants, not tuned against a real
detection backtest — same explicit posture `config/kpis.yaml`'s own
`shared_materiality_note` already states for its starting-default thresholds.
The Step 3A brief's 15% exploratory threshold is one input among several
configured thresholds here, not the sole rule.

## 10. Never conflating anomaly with cause (§15)

No field, anywhere in `src/anomaly/`, names or infers *why* a movement
happened. `AnomalyResult.business_impact.business_interpretation` describes
magnitude and population, never a driver. `materiality.reasons` explains which
*evidence dimensions* produced the verdict (magnitude/statistical/business-
impact tiers, confidence caps), never a business narrative. The November 2017
test case explicitly asserts a MATERIAL/CRITICAL verdict **and** is covered by
the causal-language scan (`tests/test_anomaly_engine.py::
test_no_result_contains_a_causal_claim`) that greps every string field of the
serialized result for causal phrasing (`"caused by"`, `"due to"`, `"black
friday"`, `"driven by"`, ...) — this is a real, machine-enforced boundary, not
a documentation promise.

## 11. Known limitations (disclosed, not hidden)

- **Fallback-level baseline scale mismatch** (§2) — a fallback level's
  baseline value is that level's own raw aggregate, not scaled to the
  entity's size. Disclosed via an explicit result warning on every such case;
  a true per-entity-normalized fallback is future work.
- **Seasonal baseline is rarely computable on this dataset** — Causa's
  reliable window is under 2 years (`docs/ANALYTICAL_WINDOW.md`), so most
  entities never accumulate the 2 prior same-calendar-month observations this
  engine requires before trusting a seasonal claim. The engine reports `null`
  rather than fabricate a pattern from one occurrence; this means, in
  practice, `rolling_mean` is the primary baseline for most real Causa
  queries today, not `seasonal`.
- **Persistence requires the caller to supply subsequent-period data** — this
  engine does not look ahead on its own (it has no notion of "the next period"
  beyond what `AnomalyRequest.subsequent` is given), so persistence is
  `UNKNOWN` whenever a caller evaluates a period without also supplying what
  came after it. This is correct (never guessing), not a bug.
- **Tier-multiplier ladders and baseline-method minimum-period floors are
  engine defaults, not statistically tuned** — same posture as `config/
  kpis.yaml`'s own thresholds; both are configuration, documented as such, and
  should be revisited once real investigation outcomes exist to backtest
  against.
- **No cross-KPI or cross-entity aggregation** — this engine assesses one
  KPI's one movement at a time. Deciding "how many entities are anomalous
  right now" or ranking movements against each other is not built here.
