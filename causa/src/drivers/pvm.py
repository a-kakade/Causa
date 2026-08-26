"""
pvm.py — Step 3D: Revenue Price / Volume / Mix decomposition (task §1/§2).

Reproduces the exact bridge validated in Step 1
(docs/INVESTIGATION_SCENARIOS.md §2, scripts/join_driver_anomaly_eda.py's
pvm_decomposition) against the canonical layer instead of raw CSVs -- same
numbers (independently re-verified against data/processed/*.parquet before
this module was written), more authoritative source (Step 2's cleaned,
deduplicated, anti-fan-out data).

    Delta Revenue = Volume Effect + Price Effect + Mix Effect

    Volume Effect = (Qty_new_total − Qty_old_total) × overall_avg_price_old
        "How much would revenue have moved if only the TOTAL number of units
        sold changed, at last period's average price, holding category mix
        and per-category prices fixed?"

    Price Effect  = Σ_category( Qty_new_cat × (Price_new_cat − Price_old_cat) )
        "For the units actually sold in the new period, how much of the
        change is attributable to each category's own average price moving?"

    Mix Effect    = Delta Revenue − Volume Effect − Price Effect   (residual)
        Captures the shift in COMPOSITION of what was sold: growth
        concentrated in higher- or lower-priced categories than before. This
        is a residual BY CONSTRUCTION, which is what makes the bridge
        reconcile EXACTLY (task §13) rather than approximately -- it is not
        an independently-estimated third quantity that happens to sum
        correctly, it is defined as "whatever the first two effects don't
        explain."

CAVEAT (carried forward from Step 1, not hidden): this is a category-mix
decomposition, not a true like-for-like SKU price change. Category-level
avg_price mixes genuinely different SKUs within a category (no
list-price/promo-price field exists in this schema to isolate discounting
from mix within-category). "Price effect" here means "shift in each
category's own average per-unit price," not "the same SKU got more/less
expensive."

None of Volume/Price/Mix is a causal claim -- each is an exact algebraic
identity over the observed data (`relationship_type: deterministic_decomposition`
for all three, per every KPI contract's own driver declarations in
config/kpis.yaml -- this module does not invent that classification, it
implements what the contract already declares).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

CATEGORY_COL = "category"                 # normalized internal column name this module expects
UNCATEGORIZED_LABEL = "uncategorized"     # sentinel for a NULL product category -- never dropped (task §4)

# Not statistically tuned -- a floor below which a PVM bridge is still
# arithmetically exact (it always is, by construction) but the categories
# behind it are too thin to trust as a business signal. Same "configuration,
# not truth" posture as Step 3C's thresholds.
MIN_ROWS_FOR_HIGH_CONFIDENCE = 30


@dataclass
class PVMBridge:
    revenue_previous: float
    revenue_current: float
    qty_previous: int
    qty_current: int
    volume_effect: float
    price_effect: float
    mix_effect: float
    checksum_error: float           # (volume + price + mix) - delta_revenue -- must be ~0
    n_categories: int
    confidence: str


def _category_aggregates(items: pd.DataFrame) -> pd.DataFrame:
    """`items` must already carry a `category` column with NO NaN values --
    the caller (engine.py) is responsible for normalizing a NULL product
    category to UNCATEGORIZED_LABEL before calling this function. This
    function never drops or silently coalesces a null category itself (task
    §4's explicit instruction lives one layer up, at the call site, but is
    enforced by a test that feeds this function real NaN-containing data via
    the engine and checks UNCATEGORIZED_LABEL survives to the output)."""
    g = items.groupby(CATEGORY_COL).agg(qty=("price", "size"), revenue=("price", "sum"))
    g["avg_price"] = g["revenue"] / g["qty"]
    return g


def compute_pvm_bridge(items_previous: pd.DataFrame, items_current: pd.DataFrame) -> PVMBridge:
    """items_previous / items_current: order-item-grain rows (one row per unit
    sold), each with a `category` column (see _category_aggregates) and a
    `price` column, already filtered to their respective period/scope by the
    caller. Handles an entirely-empty previous period (a brand-new KPI/entity,
    task §9) without producing NaN or infinity -- see the zero-qty branch
    below."""
    old_agg = _category_aggregates(items_previous)
    new_agg = _category_aggregates(items_current)
    all_cats = old_agg.index.union(new_agg.index)
    old_agg = old_agg.reindex(all_cats, fill_value=0)
    new_agg = new_agg.reindex(all_cats, fill_value=0)

    revenue_old = float(old_agg["revenue"].sum())
    revenue_new = float(new_agg["revenue"].sum())
    qty_old = float(old_agg["qty"].sum())
    qty_new = float(new_agg["qty"].sum())
    overall_avg_price_old = (revenue_old / qty_old) if qty_old else 0.0

    volume_effect = (qty_new - qty_old) * overall_avg_price_old
    # A category absent from the previous period is reindexed in with
    # fill_value=0 -- including its avg_price, i.e. treated as having had an
    # implicit price of R$0 last period. Its entire new-period revenue
    # therefore lands in price_effect (qty_new * (price_new - 0)), not in
    # mix -- a brand-new category's arrival reads as "price went from R$0",
    # not as a composition shift. This is a real, disclosed property of the
    # bridge, not an oversight: it is EXACTLY the formula validated against
    # the real October->November 2017 data in Step 1
    # (docs/INVESTIGATION_SCENARIOS.md, scripts/join_driver_anomaly_eda.py),
    # which itself contains 4 such brand-new categories -- changing this
    # treatment would change the required validated numbers, so it is kept
    # bit-for-bit compatible rather than "improved". See
    # docs/DRIVER_DECOMPOSITION.md §2 for the full discussion. `.fillna(0.0)`
    # below is a defensive no-op given fill_value=0 above (kept for clarity
    # if reindex's fill strategy ever changes).
    price_effect = float(((new_agg["avg_price"] - old_agg["avg_price"]).fillna(0.0) * new_agg["qty"]).sum())
    delta_revenue = revenue_new - revenue_old
    mix_effect = delta_revenue - volume_effect - price_effect

    confidence = "HIGH" if (qty_old >= MIN_ROWS_FOR_HIGH_CONFIDENCE and qty_new >= MIN_ROWS_FOR_HIGH_CONFIDENCE) else "LOW"

    return PVMBridge(
        revenue_previous=revenue_old, revenue_current=revenue_new,
        qty_previous=int(qty_old), qty_current=int(qty_new),
        volume_effect=volume_effect, price_effect=price_effect, mix_effect=mix_effect,
        checksum_error=(volume_effect + price_effect + mix_effect) - delta_revenue,
        n_categories=int(len(all_cats)), confidence=confidence,
    )
