"""
ranking.py — Step 3D: deterministic ranking (task §11).

Ranks by ABSOLUTE contribution, never by percentage change alone -- a seller
that grew +300% off a R$10 base ranks BELOW one that grew +R$80,000 off a
R$1M base, because the question this engine answers is "how much of the
movement does this account for," not "which grew fastest." No LLM, no
learned model, no randomness -- a single deterministic sort, same result
every time for the same input.
"""

from __future__ import annotations

from drivers.models import DriverContribution, SegmentContribution


def rank_segment_contributions(contributions: list[SegmentContribution]) -> list[SegmentContribution]:
    """Sorts by |absolute_change| descending (ties broken by segment_value for
    full determinism) and assigns `rank` (1-indexed) on each object in place,
    returning the same objects in ranked order."""
    ranked = sorted(contributions, key=lambda c: (-abs(c.absolute_change), c.segment_value))
    for i, c in enumerate(ranked, start=1):
        c.rank = i
    return ranked


def top_n(contributions: list[SegmentContribution], n: int) -> list[SegmentContribution]:
    return rank_segment_contributions(contributions)[:n]


def rank_drivers(drivers: list[DriverContribution]) -> list[DriverContribution]:
    return sorted(drivers, key=lambda d: (-abs(d.contribution_value), d.driver))


def rank_dimensions_by_contribution(segment_contributions: dict[str, list[SegmentContribution]]) -> list[dict]:
    """Answers task §7's "what dimensions contributed most to the movement?"
    -- ranks each segment TYPE (product_category, seller, ...) by the largest
    single absolute contribution any of its values accounts for, so a caller
    can decide which dimension is worth drilling into first."""
    summary = []
    for segment_type, contributions in segment_contributions.items():
        if not contributions:
            continue
        ranked = rank_segment_contributions(list(contributions))
        summary.append({
            "dimension": segment_type,
            "max_absolute_contribution": abs(ranked[0].absolute_change),
            "top_segment_value": ranked[0].segment_value,
            "total_absolute_contribution": sum(abs(c.absolute_change) for c in ranked),
            "n_segment_values": len(ranked),
        })
    summary.sort(key=lambda s: (-s["max_absolute_contribution"], s["dimension"]))
    return summary
