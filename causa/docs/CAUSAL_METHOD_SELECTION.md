# Causal Method Selection (Step 6)

Reference for `src/causal/method_selector.py`'s deterministic decision table.
Evaluated top-to-bottom, first match wins — no LLM call, no randomness, no
dict/set-iteration-order dependence (`tests/test_method_selector.py::
test_method_selection_is_deterministic_given_identical_inputs`).

| # | Condition | Selected | Tier ceiling |
|---|---|---|---|
| 1 | `eligibility.verdict == CAUSAL_INELIGIBLE` | `NONE` | n/a — `engine.py` short-circuits before method selection even runs |
| 2 | `outcome == "revenue"` and hypothesis targets a volume/price/mix component | `PVM` | `T2_ARITHMETIC`, fixed, never conditional |
| 3 | `eligibility.verdict == INELIGIBLE` | `NONE` (routed to a descriptive fallback in `engine.py`) | `T1_DESCRIPTIVE` |
| 4 | Both `treatment_group_value`/`control_group_value` set, `sufficient_pre_period` and `treatment_precedes_outcome` did not hard-fail | `DIFFERENCE_IN_DIFFERENCES` | up to `T3_QUASI_EXPERIMENTAL`, capped by `did.check_parallel_trends` |
| 5 | `treatment_dimension is None` (time-only intervention) and `sufficient_pre_period`/`sufficient_post_period` did not hard-fail | `INTERRUPTED_TIME_SERIES` | up to `T3_QUASI_EXPERIMENTAL`, capped by `interrupted_series`'s three diagnostics |
| 6 | An optional CausalImpact-style dependency is importable AND a control group exists | `CAUSAL_IMPACT` | up to `T3_QUASI_EXPERIMENTAL`, else `METHOD_UNAVAILABLE` → `T1_DESCRIPTIVE` |
| 7 | Hypothesis explicitly declares randomization in both `assumptions` and `required_data` | `EXPERIMENTAL_RESULT` | `T4_EXPERIMENTAL` — unreachable on real Olist data (no randomization field exists in canonical data); exercised only by a synthetic test |
| 8 | Treatment and outcome both resolve, no quasi-experimental structure fits | `DESCRIPTIVE_ASSOCIATION` | `T1_DESCRIPTIVE` |
| 9 | Fallback | `NONE` | no tier |

`why_other_methods_rejected` always has exactly the 6 non-selected
`CausalMethod` values as keys, filled from a fixed template map
(`method_selector._REJECTION_TEMPLATES`) with the concrete failing condition
named — never free text.

## PVM (row 2)

Reuses `drivers.engine.decompose()` **unmodified** — `engine.run_pvm()`
hardcodes `evidence_tier=T2_ARITHMETIC` and `causal_claim_allowed=False` with
no conditional branch that could produce anything else. `decompose()` itself
is scoped to `kpi_id == "revenue"` only (Step 3D's own restriction); Step 6
never widens that scope.

## Difference-in-Differences (row 4)

Point estimate: plain 2×2 arithmetic —

```
point_estimate = (mean(treatment_post) - mean(treatment_pre))
                - (mean(control_post) - mean(control_pre))
```

**Parallel-trends diagnostic** (`did.check_parallel_trends`): fits the
treatment and control groups' pre-period slopes via `numpy.linalg.lstsq`
(no scipy/statsmodels — this repo carries neither), then computes

```
ratio = |slope_treatment - slope_control| / max(|slope_treatment|, |slope_control|, 1e-9)
```

`ratio <= 0.5` (`PARALLEL_TRENDS_SLOPE_RATIO_TOLERANCE`) passes. Fewer than 2
pre-treatment periods is **treated as failed, not skipped** — absence of
evidence for parallel trends is not evidence of parallel trends. The point
estimate is always computed regardless of diagnostic outcome; only
`causal_claim_allowed` and the resulting tier are gated by it.

## Interrupted Time Series (row 5)

Segmented regression via a 4-column design matrix per period `t`
(0-indexed, intervention at index `T`):

```
[1, time, post, time_since_intervention]
  post = 1 if t >= T else 0
  time_since_intervention = max(0, t - T)
```

solved via `numpy.linalg.lstsq`, yielding `[intercept, pre_slope,
level_shift, slope_change]`.

**`MIN_PRE_PERIODS = 12`, `MIN_POST_PERIODS = 3`** — chosen deliberately
strict against Olist's own governed monthly window
(`config/kpis.yaml`'s `shared_valid_time_window`: `default_start=2017-01`,
`default_end=2018-08`, 20 months total). A November-2017-anchored ITS has
only 10 governed pre-intervention months (Jan–Oct 2017) and genuinely fails
this check — not a contrived example, the honest consequence of applying a
defensible threshold (a full calendar year of monthly observations before
trusting a segmented-regression trend on moderately volatile e-commerce
data) to this dataset's actual size.

**Autocorrelation** (`interrupted_series.check_autocorrelation`): hand-rolled
lag-1 Pearson correlation of residuals; `|r1| > 0.5` fails.

**Concurrent intervention** (`interrupted_series.check_concurrent_intervention`):
checks the intervention period against
`diagnostics.KNOWN_CONCURRENT_EVENTS` — a static registry seeded with the
already-documented November 2017 Black Friday volume surge
(`STEP4_VALIDATION.md` §12). Any overlap fails the diagnostic and is copied
into `CausalResult.confounders`.

Any one of the three diagnostics failing caps the tier at `T1_DESCRIPTIVE`
and blocks `causal_claim_allowed`; the segmented-regression coefficients are
still reported (never hidden).

## CausalImpact (row 6)

`causal_impact.is_causal_impact_available()` probes for `causalimpact` /
`tfcausalimpact` via `importlib.util.find_spec` — **never** a top-level hard
import, so this module always imports cleanly whether or not such a package
is installed. Neither is in `requirements.txt` today, so
`run_causal_impact()` always returns the `METHOD_UNAVAILABLE` contract on a
real run: `evidence_tier` forced to `T1_DESCRIPTIVE`, `causal_claim_allowed
=False`, a `DiagnosticResult("dependency_availability", False, ...)` naming
the reason. The identical contract fires when a package IS importable but
`is_suitable()` finds no control/donor series — "unavailable or unsuitable"
share one diagnostic name so callers/tests can assert on a single string
regardless of which branch triggered it.

## Experimental Result (row 7)

No canonical table in this repository carries a randomization-assignment
field, so this row is dead on real Olist data by honest construction —
`method_selector` only reaches it when a hypothesis explicitly names
randomization in both `assumptions` and `required_data`, which no
Step 6-authored hypothesis does. `engine._run_experimental_unimplemented`
returns a `T1_DESCRIPTIVE`, `causal_claim_allowed=False` result if this path
is ever exercised (a synthetic test does so deliberately).
