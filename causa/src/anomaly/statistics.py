"""
statistics.py — Step 3C: statistical abnormality signals (task §4).

Three signals, each with a documented assumption, none treated as proof of
significance on its own:

- z_score: (observed - mean) / std, against the rolling window. Assumes the
  historical distribution is roughly symmetric and that the sample std is a
  meaningful spread estimate -- both assumptions weaken fast below ~6 points, so
  z_score is annotated with a caveat whenever n < 6 rather than presented bare.
- robust_z_score: 0.6745 * (observed - median) / MAD. Median/MAD are far less
  sensitive to one extreme historical point than mean/std, so this is reported
  alongside z_score specifically so the two can be compared -- large divergence
  between them is itself informative (a skewed or outlier-contaminated
  history), not just redundant.
- percentile: empirical rank of the observed value within its own historical
  distribution (0..100). Makes no distributional assumption at all, but is
  correspondingly unstable with a small n (a percentile computed from 4 points
  can only ever be one of ~5 values) -- also caveated below n=10.

None of these functions decide materiality. That combination happens in
materiality.py -- this module only computes numbers and states what they do and
do not assume.
"""

from __future__ import annotations

from typing import Optional

Z_SCORE_MIN_N = 3      # below this, std is not a meaningful spread estimate at all
ROBUST_Z_MIN_N = 3
PERCENTILE_MIN_N = 3
SMALL_SAMPLE_CAVEAT_N = 6      # z/robust-z below this n get an explicit caveat, not withheld
PERCENTILE_CAVEAT_N = 10


def z_score(observed: float, mean: float, std: Optional[float]) -> Optional[float]:
    if std is None or std == 0:
        return None
    return (observed - mean) / std


def mad(values: list[float]) -> float:
    """Median absolute deviation, scaled by 1.4826 so it estimates the standard
    deviation under a normal-distribution assumption (the conventional scaling
    -- makes robust_z_score comparable in magnitude to z_score)."""
    if not values:
        return 0.0
    med = _median(values)
    deviations = [abs(v - med) for v in values]
    return 1.4826 * _median(deviations)


def robust_z_score(observed: float, median: float, mad_value: Optional[float]) -> Optional[float]:
    if mad_value is None or mad_value == 0:
        return None
    return (observed - median) / mad_value


def percentile_rank(observed: float, historical_values: list[float]) -> Optional[float]:
    """% of historical values <= observed, purely empirical (no distribution
    assumed). Ties are counted as <=; the observed value itself is NOT added to
    the reference set (it is being evaluated against history, not against
    itself)."""
    if not historical_values:
        return None
    n = len(historical_values)
    n_le = sum(1 for v in historical_values if v <= observed)
    return 100.0 * n_le / n


def _median(values: list[float]) -> float:
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def assumptions_note(n_historical: int) -> list[str]:
    """Explicit, human-readable caveats attached to StatisticalSignals.
    Documents assumptions rather than hiding them (task §4: "Document the
    assumptions", "Do NOT claim statistical significance simply because
    z-score > threshold")."""
    notes = [
        "z_score assumes the historical distribution is approximately symmetric; "
        "it is a heuristic magnitude-of-surprise measure, not a formal significance test.",
        "robust_z_score (median/MAD) is less sensitive to outlier history points than "
        "z_score, but the two are expected to broadly agree -- large divergence between "
        "them indicates skewed or outlier-contaminated history, not necessarily a real signal.",
        "percentile is purely empirical (no distribution assumed) and is unstable with "
        "few historical points.",
    ]
    if n_historical < SMALL_SAMPLE_CAVEAT_N:
        notes.append(
            f"Only {n_historical} historical periods available -- below {SMALL_SAMPLE_CAVEAT_N}, "
            "z_score/robust_z_score should be read as directional signals only, not precise estimates."
        )
    if n_historical < PERCENTILE_MIN_N:
        notes.append("Too few historical periods to compute a percentile at all.")
    elif n_historical < PERCENTILE_CAVEAT_N:
        notes.append(f"percentile computed from only {n_historical} points -- coarse-grained by construction.")
    return notes
