"""
test_geolocation.py

Tests for data_pipeline/preprocessing/geolocation.py. Uses small synthetic
DataFrames only — does not require the real Olist dataset to be present, and never
touches data/raw/olist/.

Usage:
    python -m pytest tests/test_geolocation.py -v
    # or, without pytest:
    python tests/test_geolocation.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Allow running this file directly (`python tests/test_geolocation.py`) without the
# package being installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_pipeline.preprocessing.geolocation import (
    OUTPUT_COLUMNS,
    RAW_CITY_COL,
    RAW_LAT_COL,
    RAW_LNG_COL,
    RAW_STATE_COL,
    RAW_ZIP_COL,
    _mode_deterministic,
    aggregate_geolocation,
    build_ambiguity_report,
    profile_raw_geolocation,
    validate_geolocation_dimension,
)


def make_raw(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=[RAW_ZIP_COL, RAW_LAT_COL, RAW_LNG_COL, RAW_CITY_COL, RAW_STATE_COL])


# A small synthetic dataset mimicking the real shape:
# - prefix 1001: unambiguous, 3 clean samples
# - prefix 1002: ambiguous city (two distinct city names), same state
# - prefix 1003: ambiguous state (two distinct states)
# - prefix 1004: single row (no spread at all)
SAMPLE_RAW = make_raw(
    [
        {RAW_ZIP_COL: 1001, RAW_LAT_COL: -23.55, RAW_LNG_COL: -46.63, RAW_CITY_COL: "sao paulo", RAW_STATE_COL: "SP"},
        {RAW_ZIP_COL: 1001, RAW_LAT_COL: -23.56, RAW_LNG_COL: -46.64, RAW_CITY_COL: "sao paulo", RAW_STATE_COL: "SP"},
        {RAW_ZIP_COL: 1001, RAW_LAT_COL: -23.54, RAW_LNG_COL: -46.65, RAW_CITY_COL: "sao paulo", RAW_STATE_COL: "SP"},
        {RAW_ZIP_COL: 1002, RAW_LAT_COL: -22.90, RAW_LNG_COL: -43.20, RAW_CITY_COL: "rio de janeiro", RAW_STATE_COL: "RJ"},
        {RAW_ZIP_COL: 1002, RAW_LAT_COL: -22.91, RAW_LNG_COL: -43.21, RAW_CITY_COL: "rio de janeiro", RAW_STATE_COL: "RJ"},
        {RAW_ZIP_COL: 1002, RAW_LAT_COL: -22.92, RAW_LNG_COL: -43.19, RAW_CITY_COL: "niteroi", RAW_STATE_COL: "RJ"},
        {RAW_ZIP_COL: 1003, RAW_LAT_COL: -15.79, RAW_LNG_COL: -47.88, RAW_CITY_COL: "brasilia", RAW_STATE_COL: "DF"},
        {RAW_ZIP_COL: 1003, RAW_LAT_COL: -15.80, RAW_LNG_COL: -47.89, RAW_CITY_COL: "brasilia", RAW_STATE_COL: "GO"},
        {RAW_ZIP_COL: 1004, RAW_LAT_COL: -3.10, RAW_LNG_COL: -60.02, RAW_CITY_COL: "manaus", RAW_STATE_COL: "AM"},
    ]
)


# ---- _mode_deterministic ------------------------------------------------------

def test_mode_deterministic_clear_winner():
    s = pd.Series(["a", "a", "b"])
    assert _mode_deterministic(s) == "a"


def test_mode_deterministic_tie_breaks_alphabetically():
    s = pd.Series(["zebra", "apple"])
    assert _mode_deterministic(s) == "apple"


def test_mode_deterministic_stable_regardless_of_row_order():
    s1 = pd.Series(["b", "a", "b", "a"])
    s2 = pd.Series(["a", "b", "a", "b"])
    # both are 2-2 ties -> alphabetical winner "a" regardless of order encountered
    assert _mode_deterministic(s1) == _mode_deterministic(s2) == "a"


# ---- profile_raw_geolocation ---------------------------------------------------

def test_profile_counts_distinct_prefixes():
    profile = profile_raw_geolocation(SAMPLE_RAW)
    assert profile.n_raw_rows == 9
    assert profile.n_distinct_prefixes == 4


def test_profile_detects_multi_city_and_multi_state():
    profile = profile_raw_geolocation(SAMPLE_RAW)
    assert profile.n_prefixes_multi_city == 1  # prefix 1002
    assert profile.n_prefixes_multi_state == 1  # prefix 1003


def test_profile_detects_exact_duplicates():
    dupe_raw = pd.concat([SAMPLE_RAW, SAMPLE_RAW.iloc[[0]]], ignore_index=True)
    profile = profile_raw_geolocation(dupe_raw)
    assert profile.n_exact_duplicate_rows == 1


def test_profile_normalized_city_count_folds_case_and_accents():
    # "sao paulo" vs "são paulo" should collapse to one name once folded
    raw = make_raw(
        [
            {RAW_ZIP_COL: 5000, RAW_LAT_COL: -23.5, RAW_LNG_COL: -46.6, RAW_CITY_COL: "sao paulo", RAW_STATE_COL: "SP"},
            {RAW_ZIP_COL: 5000, RAW_LAT_COL: -23.5, RAW_LNG_COL: -46.6, RAW_CITY_COL: "são paulo", RAW_STATE_COL: "SP"},
        ]
    )
    profile = profile_raw_geolocation(raw)
    # raw comparison sees two distinct city strings -> ambiguous
    assert profile.n_prefixes_multi_city == 1
    # folded comparison sees them as the same city -> not ambiguous once normalized
    assert profile.n_prefixes_multi_city_normalized == 0


# ---- build_ambiguity_report -----------------------------------------------------

def test_ambiguity_report_flags_expected_prefixes():
    report = build_ambiguity_report(SAMPLE_RAW)
    flagged = set(report.ambiguous_prefixes["zip_code_prefix"])
    assert flagged == {1002, 1003}
    assert report.n_multi_city_prefixes == 1
    assert report.n_multi_state_prefixes == 1


def test_ambiguity_report_excludes_unambiguous_prefixes():
    report = build_ambiguity_report(SAMPLE_RAW)
    flagged = set(report.ambiguous_prefixes["zip_code_prefix"])
    assert 1001 not in flagged
    assert 1004 not in flagged


def test_ambiguity_report_records_all_candidate_values_not_just_the_choice():
    report = build_ambiguity_report(SAMPLE_RAW)
    row = report.ambiguous_prefixes.set_index("zip_code_prefix").loc[1002]
    assert row["distinct_cities"] == ["niteroi", "rio de janeiro"]
    assert row["n_distinct_cities"] == 2


# ---- aggregate_geolocation -------------------------------------------------------

def test_aggregate_one_row_per_prefix():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    assert len(agg) == SAMPLE_RAW[RAW_ZIP_COL].nunique() == 4
    assert agg["zip_code_prefix"].is_unique


def test_aggregate_uses_median_coordinates():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    row = agg.set_index("zip_code_prefix").loc[1001]
    expected_lat = SAMPLE_RAW.loc[SAMPLE_RAW[RAW_ZIP_COL] == 1001, RAW_LAT_COL].median()
    expected_lng = SAMPLE_RAW.loc[SAMPLE_RAW[RAW_ZIP_COL] == 1001, RAW_LNG_COL].median()
    assert row["latitude"] == expected_lat
    assert row["longitude"] == expected_lng


def test_aggregate_uses_mode_city_and_state():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    row = agg.set_index("zip_code_prefix").loc[1002]
    assert row["city"] == "rio de janeiro"  # 2 of 3 rows
    assert row["state"] == "RJ"


def test_aggregate_source_row_count_matches_raw():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    counts = SAMPLE_RAW.groupby(RAW_ZIP_COL).size()
    for _, row in agg.iterrows():
        assert row["source_row_count"] == counts.loc[row["zip_code_prefix"]]


def test_aggregate_flags_ambiguous_prefixes():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    flags = agg.set_index("zip_code_prefix")["is_ambiguous"]
    assert flags.loc[1001] is False or flags.loc[1001] == False  # noqa: E712
    assert flags.loc[1002] == True  # noqa: E712
    assert flags.loc[1003] == True  # noqa: E712
    assert flags.loc[1004] == False  # noqa: E712


def test_aggregate_output_schema_matches_spec():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    assert list(agg.columns) == OUTPUT_COLUMNS


def test_aggregate_is_deterministic_across_repeated_runs():
    agg1, _ = aggregate_geolocation(SAMPLE_RAW)
    agg2, _ = aggregate_geolocation(SAMPLE_RAW)
    pd.testing.assert_frame_equal(agg1, agg2)


def test_aggregate_is_deterministic_regardless_of_row_order():
    shuffled = SAMPLE_RAW.sample(frac=1, random_state=42).reset_index(drop=True)
    agg_original, _ = aggregate_geolocation(SAMPLE_RAW)
    agg_shuffled, _ = aggregate_geolocation(shuffled)
    pd.testing.assert_frame_equal(agg_original, agg_shuffled)


def test_aggregate_does_not_mutate_raw_input():
    raw_copy = SAMPLE_RAW.copy(deep=True)
    aggregate_geolocation(SAMPLE_RAW)
    pd.testing.assert_frame_equal(SAMPLE_RAW, raw_copy)


# ---- validate_geolocation_dimension ----------------------------------------------

def test_validate_passes_on_well_formed_aggregate():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    profile = profile_raw_geolocation(SAMPLE_RAW)
    result = validate_geolocation_dimension(agg, profile)
    assert result["passed"] is True
    assert result["key_is_unique"] is True
    assert result["matches_distinct_prefix_count"] is True


def test_validate_raises_on_duplicate_key():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    profile = profile_raw_geolocation(SAMPLE_RAW)
    broken = pd.concat([agg, agg.iloc[[0]]], ignore_index=True)  # introduce a duplicate key
    try:
        validate_geolocation_dimension(broken, profile)
        raised = False
    except AssertionError:
        raised = True
    assert raised, "expected validate_geolocation_dimension to raise on a duplicate key"


def test_validate_raises_on_row_count_mismatch():
    agg, _ = aggregate_geolocation(SAMPLE_RAW)
    profile = profile_raw_geolocation(SAMPLE_RAW)
    truncated = agg.iloc[:-1]  # drop a row so it no longer matches distinct prefix count
    try:
        validate_geolocation_dimension(truncated, profile)
        raised = False
    except AssertionError:
        raised = True
    assert raised, "expected validate_geolocation_dimension to raise on row count mismatch"


if __name__ == "__main__":
    test_functions = [obj for name, obj in list(globals().items()) if name.startswith("test_")]
    failures = 0
    for fn in test_functions:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{len(test_functions) - failures}/{len(test_functions)} tests passed")
    if failures:
        sys.exit(1)
