# STEP 3D VALIDATION — Driver Decomposition Engine

Every number in this document is computed live by `src/drivers/engine.py`
(PVM against real order-item rows; concurrent KPIs via the unmodified Step 3B
`kpi.engine.KPIEngine`) via `scripts/step3d_validate_engine.py` — none are
hardcoded constants. Full machine-readable output:
`reports/step3d_validation.json`. Architecture and design rationale:
`docs/DRIVER_DECOMPOSITION.md`.

Reproduce:

```bash
python scripts/step3d_validate_engine.py
```

---

## 1. PVM methodology

```
Delta Revenue = Volume Effect + Price Effect + Mix Effect

Volume Effect = (Qty_new_total − Qty_old_total) × overall_avg_price_old
Price Effect  = Σ_category( Qty_new_cat × (Price_new_cat − Price_old_cat) )
Mix Effect    = Delta Revenue − Volume Effect − Price Effect     (residual)
```

Computed at `product_category` grain (`dim_product.category_name_en`, NULL
normalized to `"uncategorized"` — never dropped). Reproduces the exact bridge
independently validated in Step 1 (`docs/INVESTIGATION_SCENARIOS.md` §2), now
computed against the canonical layer (`data/processed/*.parquet`) instead of
raw CSVs. Mix is a residual by construction, which is what makes the bridge
reconcile exactly rather than approximately. Full rationale, including the
documented (not hidden) treatment of brand-new/discontinued categories:
`docs/DRIVER_DECOMPOSITION.md` §2.

## 2. November 2017 exact results — real data, live computation

| Metric | Computed | Required | Match |
|---|---|---|---|
| Revenue, October 2017 | R$664,219.43 | R$664,219.43 | ✅ |
| Revenue, November 2017 | R$1,010,271.37 | R$1,010,271.37 | ✅ |
| Revenue change | +R$346,051.94 | +R$346,051.94 | ✅ |
| Volume effect | +R$417,227.65 | +R$417,227.65 | ✅ |
| Price effect | +R$4,674.63 | +R$4,674.63 | ✅ |
| Mix effect | −R$75,850.34 | −R$75,850.34 | ✅ |

**All required values match exactly**, computed live via
`drivers.engine.decompose()` against `data/processed/*.parquet` — not copied
from any prior step's report (independently re-derived, and cross-checked
against `docs/INVESTIGATION_SCENARIOS.md`'s Step 1 figures, which used raw
CSVs rather than the canonical layer — the two sources agree to the cent).

## 3. PVM checksum

```
417,227.65
+   4,674.63
−  75,850.34
= 346,051.94   (matches the actual revenue change exactly)
```

`checksum_error: 0.0`, `reconciled: true`, `tolerance: 0.01`. The engine
raises `ReconciliationError` rather than returning a non-reconciling result —
verified with a deliberately-broken bridge in
`tests/test_driver_engine.py::test_engine_raises_reconciliation_error_on_a_deliberately_broken_bridge`.

## 4. Category contribution

Top 3 of 68 categories present in either period (full ranked list reconciles
exactly to +R$346,051.94 across all 68, not just the top-N returned):

| Rank | Category | Previous | Current | Contribution | Share of movement | Confidence |
|---|---|---|---|---|---|---|
| 1 | `bed_bath_table` | R$46,198.00 | R$89,412.54 | +R$43,214.54 | 12.49% | HIGH |
| 2 | `health_beauty` | R$41,915.72 | R$79,120.40 | +R$37,204.68 | 10.75% | HIGH |
| 3 | `furniture_decor` | R$30,227.51 | R$63,223.97 | +R$32,996.46 | 9.54% | HIGH |

Matches Step 1's independently-computed top contributors
(`docs/INVESTIGATION_SCENARIOS.md` §2) exactly, in English category names
(the canonical `dim_product.category_name_en` translation of the raw
`cama_mesa_banho`/`beleza_saude`/`moveis_decoracao`).

## 5. Seller contribution

Computed with `requester_clearance="INTERNAL"` (Revenue's `seller` dimension
is `security_classification: INTERNAL` per its governed contract — omitted
by default, see `docs/DRIVER_DECOMPOSITION.md` §4-6). Top 3 of hundreds of
sellers active in either period:

| Rank | Seller | Previous | Current | Contribution | History periods | Confidence |
|---|---|---|---|---|---|---|
| 1 | `53243585a1...` | R$41,708.00 | R$20,339.96 | **−R$21,368.04** | 3 | MEDIUM |
| 2 | `b94cc9f10d...` | R$0.00 | R$14,047.70 | +R$14,047.70 | *(no prior history)* | MEDIUM |
| 3 | `2bf6a2c1e7...` | R$0.00 | R$12,149.80 | +R$12,149.80 | *(no prior history)* | MEDIUM |

**The single largest seller-level movement in November 2017 is a DECLINE**
(rank #1, −R$21,368.04) even though total Revenue grew — a real, disclosed
finding, not smoothed over by only reporting growth. Ranks #2 and #3 are
brand-new sellers (`percentage_change: null`, correctly undefined rather than
infinite — task §9) still contributing a real, rankable dollar figure (task
§11: ranked by absolute contribution, not percentage).

## 6. Geographic contribution

| Dimension | Top value | Contribution | Share of movement |
|---|---|---|---|
| `seller_state` | SP | +R$199,072.00 | 57.5% |
| `customer_state` | SP | +R$132,346.39 | 38.2% |

Both dimensions' full ranked sets reconcile exactly to +R$346,051.94. No
geographic causality is inferred (task §6) — these are additive contribution
figures only. Per `ranking.rank_dimensions_by_contribution()`,
`seller_state` is the single largest-magnitude contributing dimension for
this movement (see `docs/DRIVER_DECOMPOSITION.md` §7 for the full ranking).

## 7. Concurrent KPI movements

| KPI | October 2017 | November 2017 | Change |
|---|---|---|---|
| Orders | 4,631 | 7,544 | +62.9% |
| AOV | R$145.41 | R$135.59 | −6.75% |
| Freight Revenue | R$105,092.94 | R$168,872.40 | +60.69% |
| Average Delivery Days | 11.86 | 15.16 | +27.87% |
| Average Review Score | 4.123 | 3.911 | −5.16% |

Computed via the unmodified Step 3B `KPIEngine.compare_periods()` — plain
arithmetic, **not combined into a conclusion** anywhere in this module (task
§15). These, together with §1-6 above, form the **November investigation
context** (task §16) — a deterministic evidence package for a future,
not-built Agentic Investigation Engine.

## 8. Sparse entity handling

See §5's ranks #2/#3 above (real data, not synthetic): brand-new sellers get
`percentage_change: null` (never infinity), a real ranked `absolute_change`,
and `confidence: "MEDIUM"` (not HIGH) precisely because `history_periods` is
unknown. `contribution` and `confidence` are always reported as **separate**
fields (task §10) — never blended into one score, and never allowed to let a
large percentage swing on a thin sample masquerade as a confident finding.

## 9. Zero-baseline handling

Verified at both the whole-KPI level (an entirely-empty previous period —
`tests/test_pvm.py::test_pvm_handles_brand_new_previous_period_of_zero_without_crashing`)
and the segment level (§5/§8 above, real data) — `previous_value == 0` always
produces `percentage_change: None`, never `inf`/`NaN`/a crash. Ranking always
falls back to `absolute_change` in this case, which remains well-defined.

## 10. Test results

**354 tests pass across the entire repository** (prior steps: 312; Step 3D:
42), reproduced from a clean state:

```bash
python -m pytest tests/ scripts/test_profile_olist.py -q
# 354 passed
```

Step 3D's 42 tests break down as:

| File | Count | Covers |
|---|---|---|
| `tests/test_pvm.py` | 10 | Simple/pure volume/pure price/mix-shift cases, many-random-case reconciliation, zero-baseline and discontinued-category edge cases, uncategorized-never-dropped, confidence bands |
| `tests/test_contributions.py` | 12 | Segment reconciliation (synthetic + randomized), NULL-key handling, zero→positive and positive→zero entities, no-infinity/no-NaN guard, sparse-entity confidence, deterministic ranking (incl. the task's own +80K/+8% vs. +300/+300% example) |
| `tests/test_driver_engine.py` | 20 | November 2017 exact PVM values (real data), category/customer_state/seller_state/seller reconciliation (real data, all 4 dimensions), top-N vs. full-set reconciliation, unsupported/unauthorized dimensions, `ReconciliationError` on a deliberately-broken bridge (via monkeypatch), `causal_claim` false everywhere + a causal-language scan, concurrent-KPI completeness, contribution-tree shape |

All 15 required scenarios from task §18 are covered — §1 PVM exact
reconciliation and §7 NULL category handling in `test_pvm.py`; §8/§9
zero-baseline entities and §10 sparse-entity metadata and §11 ranking in
`test_contributions.py`; §2-6, §12-15 in `test_driver_engine.py` against
**real** canonical data.

## 11. Known limitations

- PVM is implemented for Revenue only in this step — `decompose()` rejects
  any other `kpi_id` (task §1's explicit scope).
- Brand-new/discontinued categories' revenue lands entirely in `price_effect`
  rather than a separate bucket — a documented, deliberate property of the
  validated formula, not an oversight (`docs/DRIVER_DECOMPOSITION.md` §2).
- `history_periods` scans the full available canonical history on every call
  (once per requested segment dimension); fine at this dataset's size, not
  optimized for a much larger one.
- `confidence` (segment- and PVM-level) is a fixed, undtuned data-volume
  heuristic — not a statistical significance test, same posture as Step 3C's
  thresholds.
- No cross-period trend or multi-period decomposition — exactly two periods
  per call.

---

## STOP CONDITION MET

No causal inference, RAG, LLM, agents, recommendations, or frontend exist
anywhere in `src/drivers/`. Every PVM/segment figure traces to
`data/processed/*.parquet` through the exact filtering discipline Step 3B
already established, verified by a reconciliation guard that would raise
rather than silently mis-report. The November 2017 movement (task §2)
reproduces the required Volume/Price/Mix values exactly, computed live, with
`causal_claim: false` on every driver and segment result and no causal
language anywhere in the output (machine-verified).

**Step 3D is complete. Causal inference, RAG, agents, LLM reasoning, and
recommendations have not been started.**
