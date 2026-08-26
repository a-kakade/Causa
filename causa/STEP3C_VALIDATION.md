# STEP 3C VALIDATION — Materiality and Anomaly Detection Engine

Every number in this document is computed live by `src/anomaly/engine.py`
(against real KPI values from `src/kpi/engine.py` for the November 2017 and
sparse-entity cases) via `scripts/step3c_validate_engine.py` — none are
hardcoded constants. Full machine-readable output:
`reports/step3c_validation.json`. Architecture and design rationale:
`docs/MATERIALITY_ENGINE.md`.

Reproduce:

```bash
python scripts/step3c_validate_engine.py
```

---

## 1. Baseline strategies implemented

Six methods (`src/anomaly/baseline.py`): `previous_period`, `rolling_mean`,
`rolling_median`, `rolling_std`, `ewma`, `seasonal`. Each is computed only when
its own minimum-points bar is cleared; every feasible method's value is
exposed in `AnomalyResult.baseline.all_methods` for transparency, but exactly
one is selected as the reported baseline by a documented priority (`seasonal
> rolling_mean > ewma > previous_period`) — see
`docs/MATERIALITY_ENGINE.md` §3. Not every method is used for every KPI or
every entity: which ones are *feasible* is a function of how much history
exists for that specific entity/kpi combination, not a static per-kpi_id
table (§2 of the same doc explains why a static table was deliberately
rejected).

## 2. Statistical methods implemented

`z_score`, `robust_z_score` (median/MAD, scaled ×1.4826), `percentile_rank`
(`src/anomaly/statistics.py`). Every result carries an explicit `assumptions`
list stating what each signal does and does not assume (symmetric
distribution for z-score, outlier-sensitivity difference for robust z-score,
empirical-only but small-sample-unstable for percentile) — no result claims
statistical significance from a threshold crossing alone.

## 3. Materiality scoring design

Three independent evidence dimensions (magnitude, statistical abnormality,
business impact), each tiered 0–3 against the KPI's own contract thresholds,
combined by **median** (not multiplication) — requires at least two of three
to agree before the verdict is elevated. Two independent, after-the-fact caps
(baseline confidence, current-period data quality) can only ever pull the
verdict down to WATCH, never up, and are always logged with the specific
number that triggered them. Full rationale: `docs/MATERIALITY_ENGINE.md` §8.

Six possible verdicts: `NORMAL`, `WATCH`, `MATERIAL`, `CRITICAL`,
`INSUFFICIENT_DATA`, `BASELINE_DISAGREEMENT`.

## 4. Threshold configuration

Every threshold (`absolute_threshold`, `relative_threshold`,
`statistical_threshold`, `minimum_observations`, `minimum_business_impact`,
`persistence_periods`) is read from `config/kpis.yaml`'s Step 3A
`materiality` block at runtime (`src/anomaly/semantic.py`) — none are
hardcoded per-KPI constants in the engine. The engine's own tier-multiplier
ladders (how many multiples of a configured threshold reach
WATCH/MATERIAL/CRITICAL) and baseline-method minimum-period floors are
engine-level configuration, explicitly documented as starting defaults, not
statistically tuned or backtested — the same posture `config/kpis.yaml`
already states for its own threshold values.

## 5. Sparse-history behavior — real data

Computed live against a real 2-observation, 2-month product
(`0030e635639c898b323826589761cf23`, category `garden_tools`):

| Field | Value |
|---|---|
| Entity history (before fallback) | 1 period, 1 total underlying observation |
| Fallback | `entity_history_insufficient` → category level |
| Baseline level used | `category` |
| Baseline confidence | `MEDIUM` (never HIGH — a fallback level) |
| Observed value (2018-06) | R$153.00 |
| Materiality tiers (magnitude/statistical/business) | 3 / 3 / 2 |
| **Verdict** | **`WATCH`** (capped — current-period sample size is 1, below Revenue's `minimum_observations` of 30) |
| Materiality score (uncapped) | 0.889 |

**Never CRITICAL, never HIGH confidence, from 2 observations** — exactly the
requirement task §12 states. The raw uncapped score (0.889) still shows
strong evidence-dimension agreement, which is intentional: the score and the
verdict answer different questions (§8 of `docs/MATERIALITY_ENGINE.md`). The
result also carries an explicit warning that the category-level baseline is
that category's own raw aggregate, not scaled to this product's typical size
— see the "Known limitation" in the same doc.

## 6. Seasonal behavior

Verified with a constructed fixture (3 years of monthly data with a clean,
repeating November peak — `test_8_seasonal_peak_matching_prior_years_is_normal`):
a movement that would read as a large statistical outlier against a
season-naive rolling baseline is correctly classified `NORMAL` once ≥2 prior
same-calendar-month observations are available and selected as the primary
baseline. On the **real** Causa dataset, seasonal is rarely computable in
practice — the reliable window is under 2 years
(`docs/ANALYTICAL_WINDOW.md`), so most entities (including whole-of-business
Revenue evaluated at November 2017, below) never accumulate 2 prior
same-calendar-month points. The engine reports `seasonal: null` honestly
rather than fabricate a pattern from one occurrence, and falls through to
`rolling_mean`.

## 7. November 2017 result — real data, live computation

Computed via `kpi.engine.KPIEngine` (Step 3B, unmodified) for the history and
observed value, then `anomaly.engine.detect()`:

| Field | Value |
|---|---|
| Revenue, October 2017 (for reference — matches STEP3B_VALIDATION.md exactly) | R$664,219.43 |
| Revenue, November 2017 (observed) | R$1,010,271.37 |
| Baseline method | `rolling_mean` (seasonal unavailable — <2 prior Novembers in the reliable window) |
| Baseline value (Jan–Oct 2017 rolling mean) | R$549,955.67 |
| Baseline confidence | `HIGH` |
| Movement (vs. rolling-mean baseline) | +R$460,315.70 (+83.7%) |
| z-score / robust z-score | 5.32 / 5.02 |
| Materiality tiers (magnitude / statistical / business impact) | 3 / 3 / 3 |
| **Verdict** | **`CRITICAL`** |
| Materiality score | 1.0 |
| Business impact | *"Revenue moved by +460,315.70 versus its baseline (observed value 1,010,271.37)"* — 8,665 contributing order items, coverage 98.8% |

**Identified as a strong candidate for investigation, exactly as task §11
requires — with no causal claim anywhere in the result.** The result's
`materiality.reasons` states only *"Combined from magnitude tier=3,
statistical tier=3, business-impact tier=3 (median of the three...)"* — it
does not say "Black Friday," does not reference a calendar event, and does
not name a driver. (Note: the baseline here is the rolling mean of Jan–Oct
2017, which is lower than the R$664,219.43 October-alone figure documented in
`docs/INVESTIGATION_SCENARIOS.md`/`STEP3B_VALIDATION.md` §5, because it
averages across the platform's ramp months earlier in 2017 — both the
Oct-vs-Nov comparison and the rolling-mean-vs-Nov comparison independently
classify the movement as CRITICAL, so this does not change the verdict.)

## 8. Test results

**312 tests pass across the entire repository** (prior steps: 231; Step 3C:
81), reproduced from a clean state:

```bash
python -m pytest tests/ scripts/test_profile_olist.py -q
# 312 passed
```

Step 3C's 81 tests break down as:

| File | Count | Covers |
|---|---|---|
| `tests/test_baselines.py` | 29 | All 6 baseline methods, primary-method priority, the fallback ladder (single-hop, multi-hop, total failure), confidence bands |
| `tests/test_statistics.py` | 10 | z-score, robust z-score/MAD, percentile, documented assumptions/caveats |
| `tests/test_materiality.py` | 23 | Tier classification (magnitude/statistical/business-impact), median combination, business impact (additive vs. rate), all 5 persistence classes, `decide()`'s combination/caps/disagreement/seasonal-exemption |
| `tests/test_anomaly_engine.py` | 19 | All 15 scenarios required by task §16 (see below) + a 4-case parametrized causal-language scan |

All 15 required scenarios from task §16 are covered, 2 of them (#6 sparse
entity, #15 November 2017) against **real** canonical data, not synthetic
fixtures:

| # | Scenario | Test |
|---|---|---|
| 1 | Normal movement | `test_1_normal_movement_is_not_flagged` |
| 2 | Large movement | `test_2_large_broad_based_movement_is_material_or_critical` |
| 3 | Statistically unusual movement | `test_3_statistically_unusual_movement_flagged_by_zscore` |
| 4 | Business-impactful small % movement | `test_4_small_percentage_movement_can_still_be_material_via_absolute_impact` |
| 5 | Large % movement, tiny sample | `test_5_large_percentage_movement_tiny_sample_is_not_automatically_critical` |
| 6 | Sparse entity (real data) | `test_6_sparse_real_product_falls_back_and_never_reaches_high_confidence` |
| 7 | Baseline fallback | `test_7_baseline_fallback_chain_entity_to_category_to_global` |
| 8 | Seasonal movement | `test_8_seasonal_peak_matching_prior_years_is_normal` |
| 9 | Persistent movement | `test_9_persistent_movement_is_classified_but_persistence_does_not_gate_verdict` |
| 10 | One-off shock | `test_10_one_off_shock_can_still_be_material` |
| 11 | Baseline disagreement | `test_11_contradictory_baselines_produce_baseline_disagreement` |
| 12 | Low-quality data | `test_12_low_quality_current_period_downgrades_and_is_disclosed` |
| 13 | NULL KPI | `test_13_null_kpi_value_is_insufficient_data_not_a_crash` |
| 14 | Zero denominator | `test_14_zero_denominator_ratio_is_insufficient_data` |
| 15 | November 2017 revenue (real data) | `test_15_november_2017_revenue_is_flagged_material_or_critical` |

**No result contains a causal claim** — verified programmatically
(`test_no_result_contains_a_causal_claim`), which serializes each of 4
representative results (normal, large movement, baseline disagreement, NULL
KPI) to a dict and greps every string field for causal phrasing (`"caused
by"`, `"because of"`, `"due to"`, `"black friday"`, `"driven by"`, `"led
to"`, `"responsible for"`, ...). None match, for any of the 4 cases.

## 9. Known limitations

- Fallback-level baselines compare an entity's raw value against a coarser
  level's own raw aggregate (not scaled to the entity's typical size) —
  disclosed via an explicit result warning, not silently approximated. See
  `docs/MATERIALITY_ENGINE.md` §2/§11.
- Seasonal baselines are rarely computable on Causa's real (~2-year) dataset;
  `rolling_mean` is the practical primary baseline for most real queries
  today.
- Persistence requires the caller to supply subsequent-period observations;
  it is `UNKNOWN` (not guessed) whenever they are not provided.
- Tier-multiplier ladders and baseline minimum-period floors are engine
  defaults, explicitly not statistically tuned or backtested — same posture
  as `config/kpis.yaml`'s own materiality thresholds.
- This engine assesses one KPI's one movement at a time; cross-KPI or
  cross-entity ranking/aggregation is not built here.

## 10. Cases where the engine abstains

The engine explicitly refuses to produce a confident verdict, rather than
guessing, in these cases (all covered by tests):

- **`INSUFFICIENT_DATA`** — the observed KPI value is NULL (a zero-denominator
  ratio, or no rows in scope), *or* no level in the fallback ladder (including
  global) clears the historical-sufficiency bars.
- **`BASELINE_DISAGREEMENT`** — independent baseline methods disagree on
  materiality by ≥2 tiers; the engine reports the conflict and every
  underlying signal rather than silently choosing one baseline.
- **Verdict capped at `WATCH`** — whenever baseline confidence is LOW/NONE, or
  the current period's own sample size/coverage is below the contract's
  configured floor, regardless of how strong the raw combined score looks.
  The uncapped `score` is still reported alongside, so the underlying evidence
  is never hidden even when the engine declines to act on it with confidence.
- **`persistence_class: UNKNOWN`** — whenever no subsequent-period data is
  supplied; the engine does not guess whether a movement will persist,
  reverse, or trend.
- **`seasonal: null`** — whenever fewer than 2 prior same-calendar-month
  observations exist; the engine does not infer a seasonal pattern from one
  occurrence.

---

## STOP CONDITION MET

No PVM, causal inference, RAG, LLM, agents, recommendations, or frontend exist
anywhere in `src/anomaly/`. Every threshold that decides a verdict is read
from `config/kpis.yaml`'s Step 3A `materiality` block at runtime, not
hardcoded. The November 2017 movement (task §11) is classified `CRITICAL`
with no causal claim anywhere in the result, computed live against
`data/processed/*.parquet` via the unmodified Step 3B engine. A real
2-observation product (task §12) is shown falling back from entity to
category level and capped at `WATCH`, never reaching a high-confidence
verdict from 2 observations.

**Step 3C is complete. PVM, causal inference, RAG, agents, LLM reasoning, and
recommendations have not been started.**
