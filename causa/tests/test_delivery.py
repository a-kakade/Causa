"""Delivery-metric calculation and data-quality-flag tests (Step 2 §11, §21.9)."""

from __future__ import annotations

import pandas as pd


def test_delivery_days_matches_manual_recomputation(canonical):
    fo = canonical["fact_orders"]
    valid = fo.dropna(subset=["customer_delivery_timestamp", "purchase_timestamp"])
    expected = (valid["customer_delivery_timestamp"] - valid["purchase_timestamp"]).dt.total_seconds() / 86400
    diff = (valid["delivery_days"] - expected).abs()
    assert (diff < 1e-6).all(), f"{(diff >= 1e-6).sum()} rows have delivery_days that doesn't match customer_delivery_timestamp - purchase_timestamp"


def test_carrier_days_matches_manual_recomputation(canonical):
    fo = canonical["fact_orders"]
    valid = fo.dropna(subset=["carrier_delivery_timestamp", "purchase_timestamp"])
    expected = (valid["carrier_delivery_timestamp"] - valid["purchase_timestamp"]).dt.total_seconds() / 86400
    diff = (valid["carrier_days"] - expected).abs()
    assert (diff < 1e-6).all()


def test_delivery_delay_days_matches_manual_recomputation(canonical):
    fo = canonical["fact_orders"]
    valid = fo.dropna(subset=["customer_delivery_timestamp", "estimated_delivery_timestamp"])
    expected = (valid["customer_delivery_timestamp"] - valid["estimated_delivery_timestamp"]).dt.total_seconds() / 86400
    diff = (valid["delivery_delay_days"] - expected).abs()
    assert (diff < 1e-6).all()


def test_missing_dates_produce_null_not_zero(canonical):
    """§11 explicitly prohibits silently converting missing dates into zero. Every row
    with a null customer_delivery_timestamp must have a null delivery_days, never 0."""
    fo = canonical["fact_orders"]
    missing_customer_date = fo["customer_delivery_timestamp"].isna()
    assert fo.loc[missing_customer_date, "delivery_days"].isna().all(), (
        "Rows with a missing customer_delivery_timestamp must have a NULL delivery_days, not 0 or any "
        "other placeholder value."
    )
    missing_carrier_date = fo["carrier_delivery_timestamp"].isna()
    assert fo.loc[missing_carrier_date, "carrier_days"].isna().all()


def test_delivery_data_quality_flag_values(canonical):
    fo = canonical["fact_orders"]
    valid_flags = {"VALID", "MISSING_CARRIER_DATE", "MISSING_CUSTOMER_DATE", "INVALID_SEQUENCE"}
    seen = set(fo["delivery_data_quality_flag"].unique())
    assert seen <= valid_flags, f"Unexpected delivery_data_quality_flag values: {seen - valid_flags}"


def test_valid_flag_implies_nonnegative_delivery_and_carrier_days(canonical):
    fo = canonical["fact_orders"]
    valid_rows = fo[fo["delivery_data_quality_flag"] == "VALID"]
    assert (valid_rows["delivery_days"] >= 0).all(), "VALID-flagged rows must have delivery_days >= 0"
    assert (valid_rows["carrier_days"] >= 0).all(), "VALID-flagged rows must have carrier_days >= 0"


def test_invalid_sequence_rows_genuinely_have_a_negative_duration(canonical):
    """Regression guard: every row flagged INVALID_SEQUENCE must actually have a
    negative delivery_days or carrier_days -- the flag must never be set speculatively."""
    fo = canonical["fact_orders"]
    invalid_rows = fo[fo["delivery_data_quality_flag"] == "INVALID_SEQUENCE"]
    has_negative = (invalid_rows["delivery_days"].fillna(0) < 0) | (invalid_rows["carrier_days"].fillna(0) < 0)
    assert has_negative.all(), (
        f"{(~has_negative).sum()} rows are flagged INVALID_SEQUENCE without an actual negative duration."
    )


def test_invalid_sequence_count_matches_investigation(canonical):
    """Per Step 2 §11 ('Investigate negative durations. If any exist, report them
    rather than silently removing them.') -- 166 orders were found and documented in
    DATA_LINEAGE_V2.md / STEP2_VALIDATION.md. This is a regression guard, not a
    tautology: it will fail if a future build silently drops or 'fixes' these rows."""
    fo = canonical["fact_orders"]
    n_invalid = (fo["delivery_data_quality_flag"] == "INVALID_SEQUENCE").sum()
    assert n_invalid == 166, f"Expected 166 INVALID_SEQUENCE orders (documented finding), found {n_invalid}"


def test_has_delivery_data_flag_matches_valid_status(canonical):
    fo = canonical["fact_orders"]
    expected = fo["delivery_data_quality_flag"] == "VALID"
    mismatches = (fo["has_delivery_data"] != expected).sum()
    assert mismatches == 0, f"{mismatches} rows have has_delivery_data inconsistent with delivery_data_quality_flag"


def test_delivery_flag_distribution_matches_documented_counts(canonical):
    """From Step 1: 1,783 orders have a null raw carrier date, but the flag priority
    is INVALID_SEQUENCE > MISSING_CUSTOMER_DATE > MISSING_CARRIER_DATE > VALID (a
    negative-duration or missing-customer-date row is flagged with the more severe
    label even if its carrier date also happens to be null), so only the remainder --
    missing carrier date alone, with a valid, non-negative customer delivery -- gets
    MISSING_CARRIER_DATE. Documented and cross-checked in STEP2_VALIDATION.md."""
    fo = canonical["fact_orders"]
    counts = fo["delivery_data_quality_flag"].value_counts().to_dict()
    assert counts.get("VALID", 0) == 96310, f"Expected 96310 VALID, got {counts.get('VALID')}"
    assert counts.get("MISSING_CUSTOMER_DATE", 0) == 2964, f"Expected 2964 MISSING_CUSTOMER_DATE, got {counts.get('MISSING_CUSTOMER_DATE')}"
    assert counts.get("INVALID_SEQUENCE", 0) == 166, f"Expected 166 INVALID_SEQUENCE, got {counts.get('INVALID_SEQUENCE')}"
    assert counts.get("MISSING_CARRIER_DATE", 0) == 1, f"Expected 1 MISSING_CARRIER_DATE, got {counts.get('MISSING_CARRIER_DATE')}"
    assert sum(counts.values()) == len(fo), "Flag counts must sum to total row count -- every order must get exactly one flag"
