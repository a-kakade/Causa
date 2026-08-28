# Causal Governance (Step 6)

## 1. Eligibility roll-up

`eligibility.check_eligibility()` always runs all 12 checks, always in the
same fixed order (`eligibility.CHECK_NAMES`), and rolls them up:

```
any check HARD_FAIL
  -> INELIGIBLE
  -> unless the ONLY hard fail is treatment_precedes_outcome -> CAUSAL_INELIGIBLE
else any check SOFT_FAIL -> PARTIALLY_ELIGIBLE
else                     -> ELIGIBLE
```

`CAUSAL_INELIGIBLE` is a stricter, distinct verdict from plain `INELIGIBLE`
reserved for temporal-order failure (task's own language: "If temporal
ordering is unreliable: CAUSAL_INELIGIBLE"). `engine.run_causal_analysis`
short-circuits on it — no method is even attempted, since no statistical
method can license a causal claim once treatment cannot be shown to precede
outcome.

Checks 4/5/8/9 (`sufficient_pre_period`, `sufficient_post_period`,
`sample_size`, `missingness`) are **escalating**: below a lower bound they
are `HARD_FAIL`, between the lower and upper bound `SOFT_FAIL`, at/above the
upper bound `PASS`. Every other check is fixed-severity. `confounders` is
the one check that is **never** `HARD_FAIL` — task's own words: "Explicitly
report known/suspected confounders," not "reject the hypothesis." A
confounder is a governance flag surfaced in `CausalResult.confounders`, not
an eligibility blocker.

## 2. Confounder policy

`diagnostics.detect_known_confounders()` is the single source of truth every
eligibility check and every method wrapper (PVM, DiD, ITS, CausalImpact,
descriptive) consults for the same hypothesis — so they never report
differently for identical inputs. Two families:

- **Calendar/event confounders** (`diagnostics.KNOWN_CONCURRENT_EVENTS`) — a
  static registry seeded with the already-documented November 2017 Black
  Friday volume surge (`STEP4_VALIDATION.md` §12). Flagged whenever a
  hypothesis's treatment/outcome period overlaps that month.
- **Structural confounders** — a pre-existing group characteristic
  (`product_category`, `customer_state`, `seller_state`, `seller`) is never
  a randomly-assigned treatment; flagged as `SUSPECTED` whenever
  `treatment_dimension` names one of these.

**`ConfounderReport.controlled_for` defaults `False` and is asserted never
`True`** (`diagnostics.report_confounders_never_controlled`) — no method in
this version of `src/causal/` implements covariate adjustment, so claiming a
confounder was "controlled for" merely because it appears in the data would
be a false governance claim. This is the literal implementation of the
task's own words: "Do not claim they were controlled merely because they
exist in the data."

## 3. Language gate vocabulary

Reuses `agents.models.UNSUPPORTED_CAUSAL_PATTERN` /
`assert_no_unsupported_causal_language` directly
(`causal.language_gate.enforce_language_gate`) — the same stricter-superset
regex Step 5 already established, not a third independent copy. Banned:
`caused`/`caused by`, `causes`, `because of`, `due to` (unless "excluded due
to"), `the reason is/for`, `as a result of`, `led to`, `driven by`, `drove
the`, `responsible for`, `resulted in`. Allowed (never pattern-matched):
`associated with`, `consistent with`, `coincides with`, `contributed
mathematically`, `supports the hypothesis`, `may be associated with`,
`mathematically explains` (the last added to `agents.models.
ALLOWED_HEDGED_PHRASES` in Step 6 — verified to contain no token the banned
pattern matches).

The gate is applied to **every** free-text field on a `CausalResult`
(`limitations`, `assumptions`) unconditionally, regardless of
`causal_claim_allowed` — even a licensed T3/T4 result's prose must stay
non-causal-phrased, since the actual causal assertion lives only in
`CausalResult.status`/`estimate`, never in a sentence.

## 4. Honest abstention on Olist data

Running `scripts/step6_causal_validation.py`'s four required hypotheses
(order-volume, category-growth, delivery/review, geographic) against real
November 2017 canonical data produces:

| Hypothesis | Verdict | Method | Tier | `causal_claim_allowed` |
|---|---|---|---|---|
| C1 order-volume | PARTIALLY_ELIGIBLE | PVM | T2_ARITHMETIC | False |
| C2 category-growth | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | False |
| C3 delivery/review | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | False |
| C4 geographic | INELIGIBLE | DESCRIPTIVE_ASSOCIATION | T1_DESCRIPTIVE | False |

**Every real hypothesis lands at T1/T2 with `causal_claim_allowed=False`.
This is the successful, intended outcome of a governed causal layer applied
to an observational dataset with no designed experiment** — Olist has no
marketing-campaign flag, no randomization, no natural experiment for a
revenue-movement question. Category-growth and geographic both fail
eligibility outright because group membership (a product category, a
customer's state) has no assignment timing — `treatment_precedes_outcome`
hard-fails by construction, not by an overly strict threshold. Order-volume
routes to PVM, Step 3D's exact, already-validated decomposition, which this
package classifies `T2_ARITHMETIC` unconditionally and never calls causal.
Delivery/review is the one hypothesis with a genuinely well-formed temporal
order (October delivery precedes November review) but has no clean
treatment/control split and is confounded by the same documented Black
Friday surge — an honest `INELIGIBLE`, not a forced conclusion.

This mirrors Step 5's own `causal_selector.py`, which never selects
`T3_QUASI_EXPERIMENTAL`/`T4_EXPERIMENTAL` on this dataset either. Step 6
does not manufacture a different answer by trying harder — it is not
supposed to. The DiD/ITS/CausalImpact code paths themselves are verified
correct against **synthetic** data with a genuinely constructed natural
experiment (`tests/test_did.py`, `tests/test_diagnostics.py`), so "this
dataset doesn't support it" is demonstrably a fact about Olist, not a gap in
the engine.

## 5. Abstention outcomes

`causal.diagnostics.compute_abstention_status` is the single, shared policy
every method wrapper calls into:

```
verdict == CAUSAL_INELIGIBLE          -> CAUSAL_REJECTED
tier == T2_ARITHMETIC                 -> ARITHMETIC_ONLY
tier == T1_DESCRIPTIVE                -> DESCRIPTIVE_ONLY
tier in {T3, T4} and claim_allowed
    and diagnostics_passed
    and verdict == ELIGIBLE           -> CAUSAL_SUPPORTED
verdict == PARTIALLY_ELIGIBLE
    or not diagnostics_passed         -> CAUSAL_INSUFFICIENT
else                                  -> CAUSAL_REJECTED
```

`CAUSAL_SUPPORTED` is reachable through exactly one fully-earned combination
— never a default, never a fallback
(`tests/test_abstention.py::test_never_forces_a_causal_conclusion_when_data_is_ambiguous`
fuzzes the full input space and asserts this).
