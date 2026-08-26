"""
audit_raw_data.py — STEP 1: Repository and Data Foundation Audit.

This script performs an INDEPENDENT, from-scratch verification of the raw Olist CSVs
in data/raw/olist/. It does NOT import or trust any result from the prior EDA scripts
(profile_olist.py, kpi_temporal_eda.py, etc.) — every number here is recomputed
directly from the raw files so it can be cross-checked against those prior findings
rather than assumed consistent with them.

It does NOT clean, modify, deduplicate, or overwrite anything. It only reads the raw
CSVs and writes one output file: reports/raw_data_profile.json.

Covers:
  1. Per-file inventory: filename, size, encoding/BOM check, delimiter, row/col count,
     columns, pandas-inferred dtypes.
  2. Per-table integrity: duplicate rows, duplicate candidate keys, null % by column,
     unique count by column, min/max for numeric and date columns, invalid (unparseable)
     dates, suspicious numerical values (negative/zero prices, zero dimensions, etc).
  3. Candidate key verification (PK/composite PK/natural key) — uniqueness %, null %,
     duplicate count. Nothing is assumed valid because a column is named `*_id`.
  4. Relationship audit for the 6 core relationships (+2 supporting ones): left rows,
     right rows, matched rows, unmatched rows, match %, multiplicity, orphan detection,
     one-to-many / many-to-many classification, fan-out risk flag.
  5. Customer identity: customer_id vs customer_unique_id cardinality and repeat-order
     distribution.
  6. Review audit: review/order ratios, duplicate review_id, duplicate order_id, score
     distribution, text/title availability & length, language distribution via a real
     detector (langdetect, seeded for determinism), boilerplate/duplicate text rate,
     timestamp coverage.
  7. Temporal coverage: earliest/latest per date column, monthly counts for every
     relevant timestamp, explicit 2016/2017/2018 breakdown, gap detection.

Usage:
    python scripts/audit_raw_data.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from langdetect import DetectorFactory, detect

    DetectorFactory.seed = 0  # deterministic results across runs
    LANGDETECT_AVAILABLE = True
except ImportError:
    LANGDETECT_AVAILABLE = False

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "raw" / "olist"
REPORTS_DIR = REPO_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

TABLES = {
    "customers": "olist_customers_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "category_translation": "product_category_name_translation.csv",
}

DATE_COLUMNS = {
    "orders": ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
               "order_delivered_customer_date", "order_estimated_delivery_date"],
    "order_items": ["shipping_limit_date"],
    "order_reviews": ["review_creation_date", "review_answer_timestamp"],
}

# Candidate keys to VERIFY (not assumed valid). Empty list = "no single/composite
# candidate key is even proposed for this table" (documented explicitly, not silently
# skipped).
CANDIDATE_KEYS = {
    "customers": {"customer_id": ["customer_id"]},
    "orders": {"order_id": ["order_id"]},
    "order_items": {"order_id+order_item_id": ["order_id", "order_item_id"]},
    "order_payments": {"order_id+payment_sequential": ["order_id", "payment_sequential"]},
    "order_reviews": {"review_id": ["review_id"], "order_id": ["order_id"]},
    "products": {"product_id": ["product_id"]},
    "sellers": {"seller_id": ["seller_id"]},
    "geolocation": {},  # explicitly: no candidate key proposed, see integrity section
    "category_translation": {"product_category_name": ["product_category_name"]},
}

# Natural keys (identify the real-world entity, may differ from the technical PK)
NATURAL_KEYS = {
    "customers": "customer_unique_id",  # customer_id is order-scoped, not the person
}

# (relationship_name, left_table, left_col, right_table, right_col)
RELATIONSHIPS = [
    ("orders.order_id -> order_items.order_id", "orders", "order_id", "order_items", "order_id"),
    ("orders.order_id -> order_payments.order_id", "orders", "order_id", "order_payments", "order_id"),
    ("orders.order_id -> order_reviews.order_id", "orders", "order_id", "order_reviews", "order_id"),
    ("order_items.product_id -> products.product_id", "order_items", "product_id", "products", "product_id"),
    ("order_items.seller_id -> sellers.seller_id", "order_items", "seller_id", "sellers", "seller_id"),
    ("orders.customer_id -> customers.customer_id", "orders", "customer_id", "customers", "customer_id"),
    # supporting relationships, not in the spec's minimum list but relevant to integrity
    ("products.product_category_name -> category_translation.product_category_name",
     "products", "product_category_name", "category_translation", "product_category_name"),
]

SUSPICIOUS_NUMERIC_RULES = {
    ("order_items", "price"): lambda s: {"<=0": int((s <= 0).sum()), "null": int(s.isna().sum())},
    ("order_items", "freight_value"): lambda s: {"<0": int((s < 0).sum()), "==0": int((s == 0).sum())},
    ("order_payments", "payment_value"): lambda s: {"<0": int((s < 0).sum()), "==0": int((s == 0).sum())},
    ("order_payments", "payment_installments"): lambda s: {"<0": int((s < 0).sum()), "==0": int((s == 0).sum())},
    ("products", "product_weight_g"): lambda s: {"==0": int((s == 0).sum()), "null": int(s.isna().sum())},
    ("products", "product_length_cm"): lambda s: {"<=0": int((s.dropna() <= 0).sum())},
    ("products", "product_height_cm"): lambda s: {"<=0": int((s.dropna() <= 0).sum())},
    ("products", "product_width_cm"): lambda s: {"<=0": int((s.dropna() <= 0).sum())},
    ("order_reviews", "review_score"): lambda s: {"outside_1_5": int((~s.between(1, 5)).sum())},
}


# ---------------------------------------------------------------------------
# 1. File inventory (encoding, delimiter, size) — verified, not assumed
# ---------------------------------------------------------------------------

def inspect_file_bytes(path: Path) -> dict:
    raw = path.read_bytes()
    has_bom = raw[:3] == b"\xef\xbb\xbf"
    try:
        raw.decode("utf-8")
        utf8_valid = True
    except UnicodeDecodeError:
        utf8_valid = False
    try:
        raw.decode("ascii")
        ascii_only = True
    except UnicodeDecodeError:
        ascii_only = False
    first_line = raw.split(b"\n", 1)[0]
    delimiter_counts = {
        ",": first_line.count(b","), ";": first_line.count(b";"), "\t": first_line.count(b"\t"),
    }
    inferred_delimiter = max(delimiter_counts, key=delimiter_counts.get)
    return {
        "size_bytes": len(raw),
        "size_mb": round(len(raw) / 1_000_000, 2),
        "has_utf8_bom": has_bom,
        "utf8_decodable": utf8_valid,
        "ascii_only": ascii_only,
        "delimiter_char_counts_first_line": delimiter_counts,
        "inferred_delimiter": inferred_delimiter,
        "header_raw": first_line.decode("utf-8", errors="replace"),
    }


def load_table(name: str) -> tuple[pd.DataFrame, dict]:
    path = DATA_DIR / TABLES[name]
    if not path.exists():
        return None, {"exists": False, "expected_filename": TABLES[name]}
    byte_info = inspect_file_bytes(path)
    # Read with explicit, documented parameters -- do not rely on silent defaults.
    df = pd.read_csv(path, encoding="utf-8", sep=",")
    dtypes = {c: str(t) for c, t in df.dtypes.items()}
    file_info = {
        "exists": True,
        "filename": TABLES[name],
        **byte_info,
        "n_rows": int(df.shape[0]),
        "n_cols": int(df.shape[1]),
        "columns": df.columns.tolist(),
        "pandas_inferred_dtypes": dtypes,
    }
    return df, file_info


# ---------------------------------------------------------------------------
# 2. Raw integrity: duplicates, nulls, min/max, invalid dates, suspicious values
# ---------------------------------------------------------------------------

def validate_date_column(series: pd.Series) -> dict:
    n_total = len(series)
    n_null_raw = int(series.isna().sum())
    parsed = pd.to_datetime(series, errors="coerce")
    n_null_after_parse = int(parsed.isna().sum())
    n_invalid = max(n_null_after_parse - n_null_raw, 0)  # non-null raw value that failed to parse
    n_valid = n_total - n_null_raw - n_invalid
    return {
        "n_total": n_total,
        "n_null_raw": n_null_raw,
        "n_invalid_unparseable": n_invalid,
        "n_valid_parsed": n_valid,
        "min": str(parsed.min()) if n_valid else None,
        "max": str(parsed.max()) if n_valid else None,
    }


def table_integrity(name: str, df: pd.DataFrame) -> dict:
    n_rows = len(df)
    col_stats = {}
    for col in df.columns:
        s = df[col]
        n_null = int(s.isna().sum())
        entry = {
            "dtype": str(s.dtype),
            "null_count": n_null,
            "null_pct": round(n_null / n_rows * 100, 4) if n_rows else None,
            "unique_count": int(s.nunique(dropna=True)),
            "unique_pct": round(s.nunique(dropna=True) / n_rows * 100, 4) if n_rows else None,
        }
        if pd.api.types.is_numeric_dtype(s):
            entry["min"] = None if s.dropna().empty else float(s.min())
            entry["max"] = None if s.dropna().empty else float(s.max())
            entry["mean"] = None if s.dropna().empty else round(float(s.mean()), 4)
        col_stats[col] = entry

    date_cols = DATE_COLUMNS.get(name, [])
    date_validation = {c: validate_date_column(df[c]) for c in date_cols if c in df.columns}

    suspicious = {}
    for (tbl, col), rule in SUSPICIOUS_NUMERIC_RULES.items():
        if tbl == name and col in df.columns:
            suspicious[col] = rule(df[col])

    return {
        "n_rows": n_rows,
        "n_full_row_duplicates": int(df.duplicated().sum()),
        "columns": col_stats,
        "date_validation": date_validation,
        "suspicious_numeric_values": suspicious,
    }


# ---------------------------------------------------------------------------
# 3. Candidate key verification
# ---------------------------------------------------------------------------

def verify_candidate_key(df: pd.DataFrame, cols: list[str]) -> dict:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        return {"columns": cols, "columns_exist": False, "missing_columns": missing}
    n_rows = len(df)
    n_null_in_any_key_col = int(df[cols].isna().any(axis=1).sum())
    n_dup_key_rows = int(df.duplicated(subset=cols).sum())
    n_unique_combinations = int(df.drop_duplicates(subset=cols).shape[0])
    uniqueness_pct = round(n_unique_combinations / n_rows * 100, 4) if n_rows else None
    is_valid_key = n_rows > 0 and n_dup_key_rows == 0 and n_null_in_any_key_col == 0
    return {
        "columns": cols,
        "columns_exist": True,
        "n_rows": n_rows,
        "n_null_in_key": n_null_in_any_key_col,
        "n_duplicate_key_rows": n_dup_key_rows,
        "n_unique_key_combinations": n_unique_combinations,
        "uniqueness_pct": uniqueness_pct,
        "verified_valid_key": is_valid_key,
    }


def key_audit(dfs: dict[str, pd.DataFrame]) -> dict:
    result = {}
    for table, candidates in CANDIDATE_KEYS.items():
        if table not in dfs:
            continue
        if not candidates:
            result[table] = {"note": "No candidate primary/composite key proposed for this table "
                                      "-- verify manually if a key is later required (see geolocation)."}
            continue
        result[table] = {cand_name: verify_candidate_key(dfs[table], cols)
                          for cand_name, cols in candidates.items()}
    # natural keys
    natural = {}
    for table, col in NATURAL_KEYS.items():
        if table in dfs and col in dfs[table].columns:
            natural[f"{table}.{col}"] = verify_candidate_key(dfs[table], [col])
    result["_natural_keys"] = natural
    return result


# ---------------------------------------------------------------------------
# 4. Relationship audit
# ---------------------------------------------------------------------------

def relationship_audit(dfs: dict[str, pd.DataFrame]) -> list[dict]:
    results = []
    for rel_name, lt, lc, rt, rc in RELATIONSHIPS:
        if lt not in dfs or rt not in dfs:
            continue
        left, right = dfs[lt], dfs[rt]
        if lc not in left.columns or rc not in right.columns:
            continue

        left_keys_nonnull = left[lc].dropna()
        right_keys = set(right[rc].dropna().unique())

        n_left_rows = len(left)
        n_right_rows = len(right)
        n_left_null_key = int(left[lc].isna().sum())

        matched_mask = left_keys_nonnull.isin(right_keys)
        n_matched_rows = int(matched_mask.sum())
        n_unmatched_rows = n_left_rows - n_matched_rows  # includes null-key rows as unmatched
        match_pct = round(n_matched_rows / n_left_rows * 100, 4) if n_left_rows else None

        # multiplicity: how many right rows per distinct left key value (right side counts)
        right_counts_per_key = right[rc].value_counts()
        left_distinct_keys = left_keys_nonnull.unique()
        counts_for_left_keys = right_counts_per_key.reindex(left_distinct_keys, fill_value=0)
        max_right_per_left = int(counts_for_left_keys.max()) if len(counts_for_left_keys) else 0
        pct_left_keys_with_multiple_right = round(
            float((counts_for_left_keys > 1).mean()) * 100, 4
        ) if len(counts_for_left_keys) else None

        # reverse: how many left rows per distinct right key (fan-out risk direction)
        left_counts_per_key = left[lc].value_counts()
        pct_keys_with_multiple_left_rows = round(
            float((left_counts_per_key > 1).mean()) * 100, 4
        ) if len(left_counts_per_key) else None

        if max_right_per_left <= 1 and left_counts_per_key.max() <= 1:
            multiplicity = "one-to-one (at most)"
        elif max_right_per_left <= 1:
            multiplicity = "many-to-one (left has repeats, right does not)"
        elif left_counts_per_key.max() <= 1:
            multiplicity = "one-to-many (left unique, right repeats)"
        else:
            multiplicity = "many-to-many (both sides repeat) -- FAN-OUT RISK if joined directly"

        sample_orphans = left_keys_nonnull[~matched_mask].unique()[:5].tolist()

        results.append({
            "relationship": rel_name,
            "left_table": lt, "left_column": lc, "right_table": rt, "right_column": rc,
            "left_rows": n_left_rows, "right_rows": n_right_rows,
            "left_rows_with_null_key": n_left_null_key,
            "matched_rows": n_matched_rows, "unmatched_rows": n_unmatched_rows,
            "match_pct": match_pct,
            "multiplicity": multiplicity,
            "max_right_rows_per_left_key": max_right_per_left,
            "pct_left_keys_with_gt1_right_row": pct_left_keys_with_multiple_right,
            "pct_left_key_values_appearing_gt1_time_in_left": pct_keys_with_multiple_left_rows,
            "sample_orphan_keys": sample_orphans,
            "fan_out_risk": "many-to-many" in multiplicity,
        })
    return results


# ---------------------------------------------------------------------------
# 5. Customer identity
# ---------------------------------------------------------------------------

def customer_identity_audit(customers: pd.DataFrame, orders: pd.DataFrame) -> dict:
    n_customer_id = int(customers["customer_id"].nunique())
    n_customer_unique_id = int(customers["customer_unique_id"].nunique())

    orders_per_customer_id = orders.groupby("customer_id").size()
    merged = orders.merge(customers[["customer_id", "customer_unique_id"]], on="customer_id", how="left")
    orders_per_unique_id = merged.groupby("customer_unique_id").size()

    repeat_dist = orders_per_unique_id.value_counts().sort_index().to_dict()
    n_repeat_customers = int((orders_per_unique_id > 1).sum())

    return {
        "n_distinct_customer_id": n_customer_id,
        "n_distinct_customer_unique_id": n_customer_unique_id,
        "customer_id_records_per_unique_person_ratio": round(n_customer_id / n_customer_unique_id, 4),
        "orders_per_customer_id": {
            "mean": round(float(orders_per_customer_id.mean()), 4),
            "max": int(orders_per_customer_id.max()),
            "pct_with_gt1_order": round(float((orders_per_customer_id > 1).mean()) * 100, 4),
        },
        "orders_per_customer_unique_id": {
            "mean": round(float(orders_per_unique_id.mean()), 4),
            "max": int(orders_per_unique_id.max()),
            "pct_with_gt1_order": round(float((orders_per_unique_id > 1).mean()) * 100, 4),
        },
        "n_repeat_customers_by_unique_id": n_repeat_customers,
        "repeat_order_count_distribution": {str(k): int(v) for k, v in repeat_dist.items()},
        "recommendation": {
            "order_level_analysis": "customer_id (matches the orders grain 1:1 by construction)",
            "customer_level_analysis": "customer_unique_id (customer_id is re-issued per order, "
                                        "confirmed: {} customer_id values map to only {} unique "
                                        "people)".format(n_customer_id, n_customer_unique_id),
            "repeat_purchase_analysis": "customer_unique_id -- using customer_id would show 0% "
                                         "repeat rate by construction, which is wrong",
        },
    }


# ---------------------------------------------------------------------------
# 6. Review audit
# ---------------------------------------------------------------------------

def detect_language_sample(texts: pd.Series, sample_size: int = 3000, seed: int = 42) -> dict:
    if not LANGDETECT_AVAILABLE:
        return {"available": False, "note": "langdetect not installed -- run `pip install langdetect`"}
    sample = texts if len(texts) <= sample_size else texts.sample(sample_size, random_state=seed)
    counts = Counter()
    failures = 0
    for t in sample:
        try:
            counts[detect(t)] += 1
        except Exception:
            failures += 1
    total = sum(counts.values()) + failures
    return {
        "available": True,
        "detector": "langdetect (seeded, deterministic)",
        "sample_size": total,
        "distribution_pct": {k: round(v / total * 100, 2) for k, v in counts.most_common()},
        "detection_failures": failures,
    }


def review_audit(reviews: pd.DataFrame, orders: pd.DataFrame) -> dict:
    n_reviews = len(reviews)
    dup_review_id = int(reviews.duplicated(subset=["review_id"]).sum())
    orders_review_counts = reviews.groupby("order_id").size()
    dup_order_id_orders = int((orders_review_counts > 1).sum())

    title = reviews["review_comment_title"].fillna("")
    msg = reviews["review_comment_message"].fillna("")
    non_empty_msg = msg[msg.str.strip() != ""]

    lengths_chars = non_empty_msg.str.len()
    lengths_words = non_empty_msg.str.split().apply(len)

    dup_text_counts = non_empty_msg.value_counts()
    n_boilerplate_dupe_rows = int(dup_text_counts[dup_text_counts > 1].sum())

    lang = detect_language_sample(non_empty_msg)

    ts_creation = validate_date_column(reviews["review_creation_date"])
    ts_answer = validate_date_column(reviews["review_answer_timestamp"])

    orders_without_review = int(orders["order_id"].shape[0] - reviews["order_id"].nunique())

    return {
        "n_review_rows": n_reviews,
        "n_distinct_order_ids_in_reviews": int(reviews["order_id"].nunique()),
        "reviews_per_order_orders_with_gt1_review": dup_order_id_orders,
        "duplicate_review_id_rows": dup_review_id,
        "orders_with_no_review_at_all": orders_without_review,
        "review_score_distribution": reviews["review_score"].value_counts().sort_index().to_dict(),
        "title_non_empty_count": int((title.str.strip() != "").sum()),
        "title_non_empty_pct": round(float((title.str.strip() != "").mean()) * 100, 2),
        "message_non_empty_count": len(non_empty_msg),
        "message_non_empty_pct": round(len(non_empty_msg) / n_reviews * 100, 2),
        "message_length_chars": {
            "mean": round(float(lengths_chars.mean()), 1), "median": float(lengths_chars.median()),
            "max": int(lengths_chars.max()),
        } if len(non_empty_msg) else None,
        "message_length_words": {
            "mean": round(float(lengths_words.mean()), 1), "median": float(lengths_words.median()),
            "max": int(lengths_words.max()),
        } if len(non_empty_msg) else None,
        "language_detection": lang,
        "boilerplate_rows_with_duplicate_message_text": n_boilerplate_dupe_rows,
        "boilerplate_pct_of_nonempty": round(n_boilerplate_dupe_rows / len(non_empty_msg) * 100, 2)
        if len(non_empty_msg) else None,
        "top_5_duplicate_texts": [{"text": t[:100], "count": int(c)} for t, c in dup_text_counts.head(5).items()],
        "timestamp_coverage": {"review_creation_date": ts_creation, "review_answer_timestamp": ts_answer},
        "dedup_strategies_available": [
            "keep_latest_by_review_answer_timestamp",
            "keep_first_by_review_creation_date",
            "keep_highest_review_score",
            "model_as_true_1_to_many_fact_no_dedup",
        ],
        "dedup_recommendation": "Not decided in this audit (Step 1 is inspection-only). "
                                 "The 4 strategies above are documented as options; the choice is a "
                                 "STEP 2 decision and must be made explicitly, not defaulted silently.",
    }


# ---------------------------------------------------------------------------
# 6b. Revenue source reconciliation (order_items vs order_payments) -- verified
#     independently here rather than carried over from any prior EDA pass.
# ---------------------------------------------------------------------------

def revenue_reconciliation_check(items: pd.DataFrame, payments: pd.DataFrame) -> dict:
    items_per_order = items.groupby("order_id").agg(
        item_price_total=("price", "sum"), item_freight_total=("freight_value", "sum")
    )
    items_per_order["order_items_total"] = items_per_order["item_price_total"] + items_per_order["item_freight_total"]
    payments_per_order = payments.groupby("order_id").agg(payment_total=("payment_value", "sum"))

    both = items_per_order.join(payments_per_order, how="inner")
    both["abs_diff"] = (both["payment_total"] - both["order_items_total"]).abs()
    matched_1c = int((both["abs_diff"] <= 0.01).sum())
    n_both = len(both)

    only_items = int(items_per_order.index.difference(payments_per_order.index).shape[0])
    only_payments = int(payments_per_order.index.difference(items_per_order.index).shape[0])

    return {
        "orders_with_both_items_and_payments": n_both,
        "orders_with_items_only_no_payment_row": only_items,
        "orders_with_payment_only_no_item_row": only_payments,
        "matched_within_1_cent": matched_1c,
        "matched_pct_of_both": round(matched_1c / n_both * 100, 4) if n_both else None,
        "mismatched_count": n_both - matched_1c,
        "mismatch_abs_diff_max": round(float(both.loc[both["abs_diff"] > 0.01, "abs_diff"].max()), 2)
        if (both["abs_diff"] > 0.01).any() else None,
        "note": "Independently recomputed in this Step 1 audit (not imported from the prior EDA's "
                "kpi_temporal_eda.py) to verify rather than assume the revenue reconciliation claim.",
    }


def fan_out_check(orders: pd.DataFrame, items: pd.DataFrame, payments: pd.DataFrame) -> dict:
    """Independently verify the join-fan-out revenue-inflation risk by actually
    performing the naive join and comparing to the correct pre-aggregated sum."""
    correct_total = float(items["price"].sum())
    naive = items.merge(payments, on="order_id", how="inner")
    naive_total_if_summed_after_join = float(naive["price"].sum())
    inflation_pct = round((naive_total_if_summed_after_join / correct_total - 1) * 100, 4)

    n_items_per_order = items.groupby("order_id").size()
    n_payments_per_order = payments.groupby("order_id").size()
    multi_both = n_items_per_order[n_items_per_order > 1].index.intersection(
        n_payments_per_order[n_payments_per_order > 1].index
    )
    example = None
    if len(multi_both):
        oid = multi_both[0]
        example = {
            "order_id": oid,
            "n_items": int(n_items_per_order[oid]),
            "n_payments": int(n_payments_per_order[oid]),
            "true_price_total": round(float(items.loc[items.order_id == oid, "price"].sum()), 2),
            "price_sum_if_naively_joined_to_payments_first": round(
                float(items.loc[items.order_id == oid, "price"].sum()) * int(n_payments_per_order[oid]), 2
            ),
        }

    return {
        "correct_revenue_sum_order_items_price": round(correct_total, 2),
        "naive_revenue_if_items_joined_to_payments_then_summed": round(naive_total_if_summed_after_join, 2),
        "inflation_pct": inflation_pct,
        "concrete_example_order": example,
        "note": "Independently re-derived in this Step 1 audit by actually performing the naive join, "
                "not carried over from the prior EDA pass.",
    }


# ---------------------------------------------------------------------------
# 7. Temporal coverage
# ---------------------------------------------------------------------------

def temporal_coverage(dfs: dict[str, pd.DataFrame]) -> dict:
    result = {}
    for table, cols in DATE_COLUMNS.items():
        if table not in dfs:
            continue
        df = dfs[table]
        table_result = {}
        for col in cols:
            if col not in df.columns:
                continue
            parsed = pd.to_datetime(df[col], errors="coerce").dropna()
            if parsed.empty:
                continue
            monthly = parsed.dt.to_period("M").value_counts().sort_index()
            yearly = parsed.dt.year.value_counts().sort_index()
            # gap detection: calendar days with zero records within [min, max]
            daily = parsed.dt.normalize().value_counts()
            full_range = pd.date_range(parsed.min().normalize(), parsed.max().normalize(), freq="D")
            missing_days = int((~full_range.isin(daily.index)).sum())
            table_result[col] = {
                "min": str(parsed.min()), "max": str(parsed.max()),
                "n_valid": int(len(parsed)),
                "monthly_counts": {str(k): int(v) for k, v in monthly.items()},
                "yearly_counts": {str(k): int(v) for k, v in yearly.items()},
                "n_calendar_days_in_range": int(len(full_range)),
                "n_calendar_days_with_zero_records": missing_days,
                "pct_days_with_zero_records": round(missing_days / len(full_range) * 100, 2),
            }
        result[table] = table_result
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    dfs = {}
    file_inventory = {}
    for name in TABLES:
        df, info = load_table(name)
        file_inventory[name] = info
        if df is not None:
            dfs[name] = df

    integrity = {name: table_integrity(name, df) for name, df in dfs.items()}
    keys = key_audit(dfs)
    relationships = relationship_audit(dfs)
    customer_identity = customer_identity_audit(dfs["customers"], dfs["orders"]) \
        if "customers" in dfs and "orders" in dfs else None
    reviews_audit_result = review_audit(dfs["order_reviews"], dfs["orders"]) \
        if "order_reviews" in dfs and "orders" in dfs else None
    revenue_reconciliation = revenue_reconciliation_check(dfs["order_items"], dfs["order_payments"]) \
        if "order_items" in dfs and "order_payments" in dfs else None
    fan_out = fan_out_check(dfs["orders"], dfs["order_items"], dfs["order_payments"]) \
        if all(t in dfs for t in ("orders", "order_items", "order_payments")) else None
    temporal = temporal_coverage(dfs)

    output = {
        "meta": {
            "purpose": "STEP 1 -- independent raw-data audit, computed fresh from data/raw/olist/, "
                       "not derived from or dependent on any prior EDA script's output.",
            "langdetect_available": LANGDETECT_AVAILABLE,
        },
        "file_inventory": file_inventory,
        "raw_integrity": integrity,
        "key_audit": keys,
        "relationship_audit": relationships,
        "customer_identity": customer_identity,
        "review_audit": reviews_audit_result,
        "revenue_reconciliation": revenue_reconciliation,
        "fan_out_check": fan_out,
        "temporal_coverage": temporal,
    }

    out_path = REPORTS_DIR / "raw_data_profile.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    # concise stdout summary
    print("=== FILE INVENTORY ===")
    for name, info in file_inventory.items():
        if info.get("exists"):
            print(f"{name:22} rows={info['n_rows']:>8,} cols={info['n_cols']:>2} "
                  f"size={info['size_mb']:>7.2f}MB bom={info['has_utf8_bom']} "
                  f"delim={info['inferred_delimiter']!r}")
        else:
            print(f"{name:22} MISSING (expected {info['expected_filename']})")

    print("\n=== RELATIONSHIP AUDIT ===")
    for r in relationships:
        print(f"{r['relationship']}")
        print(f"    left={r['left_rows']:,} right={r['right_rows']:,} matched={r['matched_rows']:,} "
              f"unmatched={r['unmatched_rows']:,} match%={r['match_pct']}")
        print(f"    multiplicity={r['multiplicity']}  fan_out_risk={r['fan_out_risk']}")

    if revenue_reconciliation:
        print("\n=== REVENUE RECONCILIATION (order_items vs order_payments) ===")
        print(f"matched within 1 cent: {revenue_reconciliation['matched_within_1_cent']:,} "
              f"of {revenue_reconciliation['orders_with_both_items_and_payments']:,} "
              f"({revenue_reconciliation['matched_pct_of_both']}%)")

    if fan_out:
        print("\n=== FAN-OUT CHECK (naive items x payments join) ===")
        print(f"correct revenue: {fan_out['correct_revenue_sum_order_items_price']:,}")
        print(f"naive revenue:   {fan_out['naive_revenue_if_items_joined_to_payments_then_summed']:,}")
        print(f"inflation:       +{fan_out['inflation_pct']}%")

    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
