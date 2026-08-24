"""
test_profile_olist.py

Lightweight tests for the pure helper functions in profile_olist.py. These use small
synthetic DataFrames only — they do not touch data/raw/olist/ and do not require the
real Olist dataset to be present.

Usage:
    python -m pytest scripts/test_profile_olist.py -v
    # or, without pytest:
    python scripts/test_profile_olist.py
"""

from __future__ import annotations

import pandas as pd

from profile_olist import (
    check_foreign_key,
    compute_relationship_cardinality,
    detect_date_columns,
    validate_candidate_key,
    validate_date_column,
)


# ---- validate_candidate_key -------------------------------------------------

def test_candidate_key_unique_confirmed():
    df = pd.DataFrame({"id": [1, 2, 3], "val": ["a", "b", "c"]})
    result = validate_candidate_key(df, ["id"])
    assert result["columns_exist"] is True
    assert result["n_duplicate_key_rows"] == 0
    assert result["n_unique_key_combinations"] == 3
    assert result["uniqueness_confirmed"] is True


def test_candidate_key_duplicates_not_confirmed():
    df = pd.DataFrame({"id": [1, 1, 2], "val": ["a", "b", "c"]})
    result = validate_candidate_key(df, ["id"])
    assert result["columns_exist"] is True
    assert result["n_duplicate_key_rows"] == 1
    assert result["n_unique_key_combinations"] == 2
    assert result["uniqueness_confirmed"] is False


def test_candidate_key_missing_columns():
    df = pd.DataFrame({"other": [1, 2, 3]})
    result = validate_candidate_key(df, ["id"])
    assert result["columns_exist"] is False
    assert result["missing_columns"] == ["id"]
    assert result["uniqueness_confirmed"] is False


def test_candidate_key_composite():
    df = pd.DataFrame({"a": [1, 1, 2], "b": [1, 2, 1]})
    result = validate_candidate_key(df, ["a", "b"])
    assert result["n_duplicate_key_rows"] == 0
    assert result["uniqueness_confirmed"] is True


def test_candidate_key_empty_config_not_confirmed():
    df = pd.DataFrame({"id": [1, 2, 3]})
    result = validate_candidate_key(df, [])
    assert result["uniqueness_confirmed"] is False


def test_candidate_key_empty_dataframe_not_confirmed():
    df = pd.DataFrame({"id": pd.Series([], dtype="int64")})
    result = validate_candidate_key(df, ["id"])
    assert result["n_rows"] == 0
    assert result["uniqueness_confirmed"] is False


# ---- check_foreign_key -------------------------------------------------------

def test_foreign_key_no_orphans_no_nulls():
    parent = pd.DataFrame({"id": [1, 2, 3]})
    child = pd.DataFrame({"parent_id": [1, 1, 2, 3]})
    result = check_foreign_key(child, "parent_id", parent, "id")
    assert result["n_distinct_child_keys"] == 3
    assert result["n_distinct_parent_keys"] == 3
    assert result["n_orphan_keys"] == 0
    assert result["n_orphan_rows"] == 0
    assert result["n_null_fk"] == 0
    assert result["null_fk_rate"] == 0.0


def test_foreign_key_with_orphans_counts_rows_not_just_ids():
    parent = pd.DataFrame({"id": [1, 2]})
    # key 99 is an orphan and appears in 3 rows -> orphan_rows should be 3, not 1
    child = pd.DataFrame({"parent_id": [1, 2, 99, 99, 99]})
    result = check_foreign_key(child, "parent_id", parent, "id")
    assert result["n_orphan_keys"] == 1
    assert result["n_orphan_rows"] == 3
    assert result["orphan_row_rate"] == 3 / 5


def test_foreign_key_with_nulls():
    parent = pd.DataFrame({"id": [1, 2]})
    child = pd.DataFrame({"parent_id": [1, 2, None, None]})
    result = check_foreign_key(child, "parent_id", parent, "id")
    assert result["n_null_fk"] == 2
    assert result["null_fk_rate"] == 0.5
    # nulls should not count as orphans
    assert result["n_orphan_keys"] == 0
    assert result["n_orphan_rows"] == 0


def test_foreign_key_missing_column_returns_none():
    parent = pd.DataFrame({"id": [1, 2]})
    child = pd.DataFrame({"other": [1, 2]})
    result = check_foreign_key(child, "parent_id", parent, "id")
    assert result is None


# ---- compute_relationship_cardinality ---------------------------------------

def test_cardinality_basic_distribution():
    parents = pd.DataFrame({"id": [1, 2, 3, 4]})
    # parent 1 -> 2 children, parent 2 -> 1 child, parent 3 -> 0 children, parent 4 -> 3 children
    children = pd.DataFrame({"parent_id": [1, 1, 2, 4, 4, 4]})
    result = compute_relationship_cardinality(parents, "id", children, "parent_id")
    assert result["n_parent_rows"] == 4
    assert result["n_child_rows"] == 6
    assert result["n_distinct_parents"] == 4
    assert result["max_children_per_parent"] == 3
    assert result["avg_children_per_parent"] == 1.5  # (2+1+0+3)/4
    assert result["pct_parents_with_zero_children"] == 25.0
    assert result["pct_parents_with_more_than_one_child"] == 50.0  # parents 1 and 4


def test_cardinality_missing_column_returns_none():
    parents = pd.DataFrame({"id": [1, 2]})
    children = pd.DataFrame({"other": [1, 2]})
    result = compute_relationship_cardinality(parents, "id", children, "parent_id")
    assert result is None


def test_cardinality_all_parents_have_exactly_one_child():
    parents = pd.DataFrame({"id": [1, 2, 3]})
    children = pd.DataFrame({"parent_id": [1, 2, 3]})
    result = compute_relationship_cardinality(parents, "id", children, "parent_id")
    assert result["pct_parents_with_zero_children"] == 0.0
    assert result["pct_parents_with_more_than_one_child"] == 0.0
    assert result["avg_children_per_parent"] == 1.0
    assert result["median_children_per_parent"] == 1.0


# ---- detect_date_columns / validate_date_column -----------------------------

def test_detect_date_columns():
    df = pd.DataFrame(
        columns=["order_purchase_timestamp", "order_id", "review_creation_date", "price"]
    )
    cols = detect_date_columns(df)
    assert set(cols) == {"order_purchase_timestamp", "review_creation_date"}


def test_validate_date_column_all_parseable():
    series = pd.Series(["2020-01-01", "2020-02-01", "2020-03-01"])
    result = validate_date_column(series)
    assert result["n_total"] == 3
    assert result["n_parseable"] == 3
    assert result["n_failed_parse"] == 0
    assert result["failed_parse_rate"] == 0.0
    assert result["min"] == "2020-01-01 00:00:00"
    assert result["max"] == "2020-03-01 00:00:00"


def test_validate_date_column_with_failures_and_nulls():
    series = pd.Series(["2020-01-01", "not-a-date", None, "2020-03-01"])
    result = validate_date_column(series)
    assert result["n_total"] == 4
    assert result["n_failed_parse"] == 1  # "not-a-date" fails; the None does not count as a failure
    assert result["n_parseable"] == 2
    assert result["failed_parse_rate"] == 0.25


def test_validate_date_column_all_null():
    series = pd.Series([None, None])
    result = validate_date_column(series)
    assert result["n_parseable"] == 0
    assert result["n_failed_parse"] == 0
    assert result["min"] is None
    assert result["max"] is None


if __name__ == "__main__":
    # allow running without pytest installed
    import sys as _sys

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
        _sys.exit(1)
