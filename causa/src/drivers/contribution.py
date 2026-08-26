"""
contribution.py — Step 3D: segment-level revenue contribution decomposition
(task §4 product_category, §5 seller, §6 customer_state/seller_state).

Unlike pvm.py's 3-way effect decomposition, this is a SIMPLE additive
partition: revenue is summed at the same item grain (fact_order_items) that
config/kpis.yaml already certifies as safe for these exact dimensions --
docs/KPI_SEMANTIC_LAYER.md's central structural finding is that item-grain
KPIs like Revenue can safely slice by seller/product/product_category/
seller_state because summing at item grain naturally attributes each row to
exactly the entity it belongs to. No attribution rule is invented here for
multi-item orders (task §14) -- this module trusts the same grain the KPI
engine already validated, it does not re-derive that safety claim.

Because every row belongs to exactly one segment value, the per-segment
deltas sum EXACTLY to the total revenue change across all items in scope --
an algebraic identity, not an approximation, checked by the engine's
reconciliation guard (task §13).
"""

from __future__ import annotations

from typing import Optional

import pandas as pd

from drivers.models import SegmentContribution

# Sentinel labels for a missing/NULL segment key -- task §4: "Never drop NULL
# category rows." Applied uniformly to every supported segment dimension, not
# just product_category.
MISSING_LABEL_BY_SEGMENT = {
    "product_category": "uncategorized",
    "seller": "unknown_seller",
    "customer_state": "unknown_state",
    "seller_state": "unknown_state",
}

# Not statistically tuned -- same "configuration, not truth" posture as the
# Step 3C anomaly engine's thresholds (docs/MATERIALITY_ENGINE.md). This is a
# DATA-VOLUME signal (how much history/sample backs this number), explicitly
# NOT a materiality judgement (task §10: "Do not confuse contribution with
# statistical confidence") -- Step 3C's anomaly engine is the place that makes
# materiality calls; this is a plain, separate disclosure.
HIGH_CONFIDENCE_MIN_HISTORY_PERIODS = 6
HIGH_CONFIDENCE_MIN_SAMPLE_SIZE = 30
MEDIUM_CONFIDENCE_MIN_HISTORY_PERIODS = 2
MEDIUM_CONFIDENCE_MIN_SAMPLE_SIZE = 5


def confidence_for(history_periods: Optional[int], sample_size: int) -> str:
    hp = history_periods or 0
    if hp >= HIGH_CONFIDENCE_MIN_HISTORY_PERIODS and sample_size >= HIGH_CONFIDENCE_MIN_SAMPLE_SIZE:
        return "HIGH"
    if hp >= MEDIUM_CONFIDENCE_MIN_HISTORY_PERIODS or sample_size >= MEDIUM_CONFIDENCE_MIN_SAMPLE_SIZE:
        return "MEDIUM"
    return "LOW"


def compute_segment_contributions(items_previous: pd.DataFrame, items_current: pd.DataFrame,
                                   group_col: str, segment_type: str, total_change: float,
                                   history_periods_by_key: Optional[dict] = None) -> list[SegmentContribution]:
    """`items_previous`/`items_current` must both carry `group_col` (already
    normalized so a NULL/missing value is the segment's documented sentinel
    label -- see MISSING_LABEL_BY_SEGMENT -- never a raw NaN) and `price`.
    `total_change` is the KPI's ACTUAL total revenue change for the two
    periods (the caller passes this in rather than it being recomputed here),
    so every `share_of_total_movement` is measured against one consistent,
    authoritative total even if a segment's own two frames were filtered
    slightly differently for some reason."""
    old_agg = items_previous.groupby(group_col)["price"].agg(["sum", "size"])
    new_agg = items_current.groupby(group_col)["price"].agg(["sum", "size"])
    all_keys = old_agg.index.union(new_agg.index)
    old_agg = old_agg.reindex(all_keys, fill_value=0)
    new_agg = new_agg.reindex(all_keys, fill_value=0)
    history_periods_by_key = history_periods_by_key or {}

    results = []
    for key in all_keys:
        previous_value = float(old_agg.loc[key, "sum"])
        current_value = float(new_agg.loc[key, "sum"])
        absolute_change = current_value - previous_value
        # previous_value == 0 -> percentage_change undefined (a brand-new
        # entity), never infinity (task §9). current_value == 0 with
        # previous_value > 0 is a well-defined -100%, computed normally --
        # same convention kpi.engine.compare_periods already uses.
        percentage_change = None if previous_value == 0 else (absolute_change / previous_value * 100)
        share = None if total_change == 0 else (absolute_change / total_change * 100)
        sample_size = int(new_agg.loc[key, "size"])
        history_periods = history_periods_by_key.get(key)
        results.append(SegmentContribution(
            segment_type=segment_type, segment_value=str(key),
            previous_value=previous_value, current_value=current_value,
            absolute_change=absolute_change, percentage_change=percentage_change,
            share_of_total_movement=share, rank=None, sample_size=sample_size,
            history_periods=history_periods, confidence=confidence_for(history_periods, sample_size),
        ))
    return results
