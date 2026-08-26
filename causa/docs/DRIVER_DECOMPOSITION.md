# Driver Decomposition Engine — Step 3D

Turns a Revenue movement between two periods into an explicit answer to one
question: **"which measurable factors mathematically account for this
movement?"** It never answers *why* — see §8.

**No causal inference, RAG, LLM, agents, recommendations, or frontend exist
in this module.**

```
WHAT CHANGED?              -- Step 3B (KPIEngine) / Step 3C (anomaly engine)
    ↓
HOW MUCH DID EACH DRIVER    -- Step 3D (this module)
CONTRIBUTE?
    ↓
WHY DID IT HAPPEN?          -- NOT built here
    ↓
WHAT SHOULD WE DO?          -- NOT built here
```

---

## 1. Architecture

```
DriverDecompositionRequest (models.py)
    │
    ▼
SemanticRegistry.get("revenue")        -- dimension validity + clearance (§14)
    │
    ▼
CanonicalDataStore (reused from kpi.engine, read-only)
    │  filtered item-grain rows for the current & previous period
    ├─→ pvm.compute_pvm_bridge()                        -- Volume/Price/Mix
    ├─→ contribution.compute_segment_contributions()     -- per requested dimension
    └─→ kpi.engine.KPIEngine.compare_periods()            -- concurrent KPIs
    │
    ▼
reconciliation checks -- raises ReconciliationError on failure (§13)
    │
    ▼
DriverDecompositionResult
```

`src/drivers/` stays decoupled from `kpi.engine`'s private helpers — it
reuses only the public `CanonicalDataStore` and `KPIEngine` classes and
reimplements the small amount of date/window/status filtering logic locally
(`engine._load_period_items`), documented as mirroring the same discipline
`kpi.engine._compute_item_grain_sum` uses for Revenue. Same posture
`src/anomaly/` took relative to `src/kpi/` in Step 3C.

## 2. Revenue PVM (§1/§2)

```
Delta Revenue = Volume Effect + Price Effect + Mix Effect

Volume Effect = (Qty_new_total − Qty_old_total) × overall_avg_price_old
Price Effect  = Σ_category( Qty_new_cat × (Price_new_cat − Price_old_cat) )
Mix Effect    = Delta Revenue − Volume Effect − Price Effect     (residual)
```

Computed at `product_category` grain (`dim_product.category_name_en`) — the
exact bridge validated in Step 1 (`docs/INVESTIGATION_SCENARIOS.md` §2,
`scripts/join_driver_anomaly_eda.py`), re-verified against the canonical
layer (`data/processed/*.parquet`) instead of raw CSVs before this module was
written, and reproduced exactly by `src/drivers/pvm.py`.

**Mix is a residual by construction** — this is what makes the bridge
reconcile *exactly*, not approximately: it is defined as "whatever Volume and
Price don't explain," not independently estimated and hoped to add up.

**A documented, deliberate property of the formula, not an oversight**: a
category absent from the previous period is reindexed in with an implicit
prior average price of R$0. Its entire new-period revenue therefore lands in
`price_effect` (`qty_new × (price_new − 0)`), not in `mix_effect` — a
brand-new category's arrival reads as "price moved from R$0," which is an
unusual framing, but it is *exactly* the formula validated against the real
October→November 2017 data (which itself contains 4 such brand-new
categories: `books_imported`, `furniture_mattress_and_upholstery`,
`fashio_female_clothing`, `flowers`). Changing this treatment to fold
brand-new/discontinued categories into `mix_effect` instead would be more
intuitive but would change the required validated numbers — kept
bit-for-bit compatible instead. Flagged here, not hidden.

**Caveat carried forward from Step 1**: this is a category-mix decomposition,
not a true like-for-like SKU price change. Category-level `avg_price` mixes
genuinely different SKUs within a category (no list-price/promo-price field
exists in this schema to isolate discounting from mix within-category).
"Price effect" means "shift in each category's own average per-unit price,"
not "the same SKU got more/less expensive."

None of Volume/Price/Mix is a causal claim — each is an exact algebraic
identity over the observed data, matching every KPI contract's own
`relationship_type: deterministic_decomposition` driver declaration in
`config/kpis.yaml` (this module implements what the contract already
declares, it does not invent that classification).

## 3. The driver contribution object (§3)

```json
{
  "driver": "volume",
  "contribution_value": 417227.65,
  "contribution_pct_of_change": 120.6,
  "direction": "positive",
  "method": "PVM",
  "period_current": "2017-11",
  "period_previous": "2017-10",
  "evidence_type": "deterministic",
  "confidence": "HIGH",
  "lineage": [...],
  "causal_claim": false
}
```

`confidence` reflects data VOLUME behind the bridge (≥30 order items in both
periods → HIGH, else LOW) — not statistical significance (that is Step 3C's
job, not repeated here) and not a business-materiality judgement.

## 4-6. Segment contribution (§4/5/6)

`product_category`, `seller`, `customer_state`, `seller_state` — each a
**simple additive partition**, not a 3-way effect decomposition. Because
Revenue is summed at item grain (`fact_order_items`) and every item belongs
to exactly one segment value, the per-segment deltas sum EXACTLY to the total
revenue change — an algebraic identity, checked by the reconciliation guard
(§13), not an approximation.

**Never drops a NULL segment value** — a missing `product_category`,
`seller_id`, or `customer_state`/`seller_state` is normalized to an explicit
sentinel label (`"uncategorized"`, `"unknown_seller"`, `"unknown_state"`)
before aggregation, so it still contributes its own row to the partition
rather than silently vanishing (task §4's explicit instruction, and the same
`dropna=False` discipline `kpi.engine`'s dimension grouping already
enforces — see `docs/KPI_COMPUTATION_ENGINE.md` §6's R$14,115.98 undercount
regression).

**Seller identity is clearance-gated** (§5). `requester_clearance` below
`INTERNAL` (the contract's declared `security_classification` for the
`seller` dimension) means:
- the *default* segment list (no explicit `segment_dimensions` given) simply
  omits `seller`, with a logged warning — a caller who didn't ask for it by
  name shouldn't get a hard error;
- an *explicit* request for `seller` raises `UnauthorizedSegmentError` — a
  caller who did ask for something they're not cleared for gets a loud,
  specific rejection, matching `kpi.query_planner`'s
  `UnauthorizedDimensionError` convention for the same dimension in Step 3B.

## 7. Driver hierarchy

```
Revenue
│
├── PVM
│   ├── Volume
│   ├── Price
│   └── Mix
│
├── Product Category
├── Seller                (INTERNAL clearance required)
├── Customer State
└── Seller State
```

`ranking.rank_dimensions_by_contribution()` answers *"what dimensions
contributed most to the movement?"* — ranks each segment TYPE by the largest
single absolute contribution any of its values accounts for. Live for
November 2017: `seller_state` (SP: +R$199,072.00) > `customer_state` (SP:
+R$132,346.39) > `product_category` (bed_bath_table: +R$43,214.54) >
`seller` (one seller: −R$21,368.04) — geography is the single largest
individual-value contributor here, though `product_category`'s TOTAL
absolute contribution across its 10 ranked values (R$288,103.16) still
exceeds any single seller's.

## 8. Contribution vs. causation (§8) — the boundary this module does not cross

Every `DriverContribution` and `SegmentContribution` carries
`causal_claim: false` (a hardcoded dataclass default, not a caller-settable
field) and uses "contribution"/"associated movement"/"mathematical
decomposition" language. No generated string anywhere in `src/drivers/`
contains "caused," "responsible for," "led to," "driven by," or similar —
verified programmatically
(`tests/test_driver_engine.py::test_no_result_contains_a_causal_claim`),
which scans every string field of a real, fully-populated November 2017
result (and its contribution-tree export) for causal phrasing. This is a
real, machine-enforced boundary, not a documentation promise.

`method` is `"PVM"` for the three Volume/Price/Mix drivers (task §3's
example) and `"deterministic_contribution_analysis"` for every segment
contribution (task §8) — both are specific instances of the same underlying
discipline: exact arithmetic over observed data, never an inferred or
estimated causal effect.

## 9. Zero / new / discontinued entities (§9)

`previous_value == 0` → `percentage_change = None` (undefined, never
`inf`/`nan`) — a brand-new entity's growth cannot be expressed as "% change
from zero." `current_value == 0` with `previous_value > 0` is a well-defined
`-100%`, computed normally (same convention `kpi.engine.compare_periods`
already uses for a zero previous KPI value). Ranking always uses
`absolute_change`, never percentage — see §11.

The PVM bridge itself handles an entirely-empty previous period (task §9's
zero-baseline case at the whole-KPI level) the same way: `qty_old = 0` makes
`volume_effect = 0` by construction (no baseline to grow from), and every
category reads as brand-new, so the entire revenue lands in `price_effect`
per §2's documented treatment — no crash, no `NaN`, no `inf`.

## 10. Sparse entities (§10) — contribution ≠ confidence

Every `SegmentContribution` carries `history_periods` (distinct calendar
months, across ALL available canonical history up to and including the
previous period, in which this segment value had ≥1 order-item row — a real,
deterministic count, not a guess) and `confidence` (`HIGH`/`MEDIUM`/`LOW`,
derived from `history_periods` and current-period `sample_size`). These are
explicitly **separate fields from `absolute_change`/`share_of_total_movement`**
— a tiny seller can legitimately show a huge percentage swing and a real,
correctly-computed dollar contribution while simultaneously being flagged
`LOW` confidence, and both facts are reported side by side rather than one
overriding the other. Live example (November 2017, real data): seller
`b94cc9f10ddc85e4ba73a6f7974e7101` contributes +R$14,047.70 (4.06% of the
total movement, rank #2 among sellers) with `history_periods: null` (no prior
activity found anywhere in the canonical history before October 2017 — a
genuinely brand-new seller) and `confidence: "MEDIUM"`.

This is a distinct question from Step 3C's materiality/anomaly verdict —
Step 3D's `confidence` here is a plain data-volume disclosure, not a
statistical significance or business-materiality judgement (that stays
Step 3C's job, not duplicated here).

## 11. Ranking (§11)

`ranking.rank_segment_contributions()` sorts by `abs(absolute_change)`
descending (ties broken by segment value for full determinism) — never by
percentage change alone. No LLM, no learned model, no randomness: the same
input always produces the same ranking. Verified with the task's own example
shape (`tests/test_contributions.py::test_ranking_uses_absolute_contribution_not_percentage`):
a seller with +R$80,000/+8% ranks above one with +R$300/+300%.

## 12. Contribution tree (§12)

`engine.build_contribution_tree()` renders a `DriverDecompositionResult` into
the lighter, nested-dict shape the task's §12 example specifies (`kpi`,
`movement`, `drivers`, `segments`, `reconciliation`, `causal_claim`) — a
presentation/export view over an already-built, already-reconciled result,
not a second computation.

## 13. Reconciliation (§13) — the engine MUST fail, and does

Two independent reconciliation checks run on every decomposition:

1. **PVM**: `volume_effect + price_effect + mix_effect` vs. the actual
   revenue change, tolerance `0.01` (one cent) — default. Mix is a residual,
   so this is essentially exact (`error: 0.0` on the real November 2017 case).
2. **Every requested segment**: the FULL set of per-segment `absolute_change`
   values (not just the returned top-N) vs. the actual revenue change, same
   tolerance.

Either check failing raises `ReconciliationError` — the engine refuses to
return an apparently-valid, non-reconciling result. Verified with a
deliberately-broken bridge
(`tests/test_driver_engine.py::test_engine_raises_reconciliation_error_on_a_deliberately_broken_bridge`,
via `monkeypatch`) — this is not just a documented promise, the guard
actually fires when the arithmetic is wrong.

## 14. Dimension safety (§14)

Every requested segment dimension is validated against
`config/kpis.yaml`'s governed Revenue contract via
`SemanticRegistry.get_dimension()` — an unsupported/undeclared name raises
`UnsupportedSegmentError` carrying the contract's own list of supported
dimensions. No order-level attribution is invented for multi-item orders:
`product_category`/`seller`/`seller_state` are computed at item grain
(`fact_order_items`, one row per unit — the same grain Step 3B already
certified safe for these exact dimensions), and `customer_state` is a
whole-order attribute broadcast onto every item of that order (safe
regardless of how many items the order contains, since it doesn't depend on
splitting the order). This engine does not re-derive that safety claim, it
trusts the one `docs/KPI_SEMANTIC_LAYER.md` already established.

## 15-16. Concurrent KPI movements / November investigation context (§15/16)

For every Revenue decomposition, `engine.decompose()` also computes Orders,
AOV, Freight Revenue, Average Delivery Days, and Average Review Score
movements over the SAME period pair, via
`kpi.engine.KPIEngine.compare_periods()` — deterministic arithmetic only,
identical to any other Step 3B comparison, **never combined into a
conclusion here**. Every `ConcurrentKPIMovement` is a plain
previous/current/absolute/percentage tuple with no materiality, verdict, or
anomaly field of any kind (verified:
`tests/test_driver_engine.py::test_concurrent_kpis_are_complete_and_match_known_november_2017_figures`
asserts none leak in from Step 3C). These, together with the PVM bridge and
every segment's top-N contributions, form the **November investigation
context** — a deterministic evidence package (`scripts/step3d_validate_engine.py`'s
`november_investigation_context`), explicitly labeled as future input to a
not-yet-built Agentic Investigation Engine, not a conclusion drawn here.

## 17. Known limitations (disclosed, not hidden)

- **PVM is Revenue-only in this step** — `decompose()` raises
  `DriverRequestError` for any other `kpi_id`. Price × Volume × Mix is only
  meaningful for a SUM-of-price KPI (task §1's explicit scope); generalizing
  the bridge to, say, Freight Revenue is plausible future work, not attempted
  here.
- **Brand-new/discontinued categories land entirely in `price_effect`**, not
  split out into a separate "new/discontinued" bucket — see §2. A more
  granular bridge (4+ effects) is possible but would break the required
  validated numbers.
- **`history_periods` scans the full available canonical history** every
  time it's computed (once per requested segment dimension) — fine at this
  dataset's size (~113K order items), but not optimized for a much larger
  dataset; no caching across calls within one `decompose()` invocation beyond
  what's naturally reused.
- **`confidence` (§10) is a fixed, undtuned data-volume heuristic** — same
  "configuration, not statistically tuned" posture as Step 3C's thresholds,
  explicitly not a backtested significance test.
- **No cross-period trend or multi-period decomposition** — this engine
  compares exactly two periods per call; a rolling PVM series across many
  months would require repeated calls, not a new capability.
