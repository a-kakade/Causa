"""Step 3C: tests for src/anomaly/statistics.py -- statistical abnormality
signals (§4). None of these functions decide materiality; these tests only
check the numbers and the documented caveats."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from anomaly.statistics import assumptions_note, mad, percentile_rank, robust_z_score, z_score  # noqa: E402


def test_z_score_basic():
    assert z_score(observed=110.0, mean=100.0, std=10.0) == 1.0
    assert z_score(observed=80.0, mean=100.0, std=10.0) == -2.0


def test_z_score_none_when_std_is_none_or_zero():
    assert z_score(100.0, 100.0, None) is None
    assert z_score(100.0, 100.0, 0.0) is None


def test_mad_of_symmetric_data():
    # values: 1,2,3,4,5 -> median 3, deviations 2,1,0,1,2 -> median deviation 1
    # scaled by 1.4826
    m = mad([1.0, 2.0, 3.0, 4.0, 5.0])
    assert abs(m - 1.4826) < 1e-6


def test_mad_of_empty_is_zero():
    assert mad([]) == 0.0


def test_robust_z_score_basic():
    # median=3, mad=1.4826 (from test above) -> robust_z(observed=10) = (10-3)/1.4826
    rz = robust_z_score(observed=10.0, median=3.0, mad_value=1.4826)
    assert abs(rz - (7.0 / 1.4826)) < 1e-9


def test_robust_z_score_none_when_mad_zero_or_none():
    assert robust_z_score(10.0, 5.0, None) is None
    assert robust_z_score(10.0, 5.0, 0.0) is None


def test_percentile_rank_extremes():
    hist = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert percentile_rank(60.0, hist) == 100.0     # above everything
    assert percentile_rank(5.0, hist) == 0.0        # below everything
    assert percentile_rank(30.0, hist) == 60.0       # 3 of 5 values <= 30


def test_percentile_rank_none_with_empty_history():
    assert percentile_rank(10.0, []) is None


def test_assumptions_note_flags_small_sample():
    notes = assumptions_note(n_historical=2)
    joined = " ".join(notes)
    assert "2 historical periods" in joined
    assert "Too few historical periods to compute a percentile" in joined


def test_assumptions_note_no_small_sample_caveat_when_history_is_ample():
    notes = assumptions_note(n_historical=24)
    joined = " ".join(notes)
    assert "below" not in joined.lower() or "historical periods available --" not in joined
    # the core assumption statements are always present regardless of n
    assert any("z_score assumes" in n for n in notes)
    assert any("robust_z_score" in n for n in notes)
    assert any("percentile is purely empirical" in n for n in notes)
