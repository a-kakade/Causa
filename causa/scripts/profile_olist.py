"""
profile_olist.py

Automated profiling of the raw Olist CSV dataset. This script does NOT transform,
modify, or write to data/raw/olist/ — it only reads the CSVs there. It exists purely to
validate and characterize the dataset ahead of designing the Causa data model and KPI
layer. No KPI or preprocessing decisions are made here.

For each table it reports:
  - row/column counts, dtypes
  - null counts and null rates per column
  - duplicate row counts
  - cardinality (n unique) per column
  - min/max for date-like and numeric columns

Across tables it reports:
  - candidate key validation: for each configured candidate key, whether all of its
    columns exist, how many duplicate key rows there are, how many unique key
    combinations exist, and whether uniqueness is actually confirmed by the data (a key
    being listed in configuration does NOT imply it is valid)
  - foreign-key quality: distinct child/parent keys, orphan keys, orphan rows, and null
    FK counts/rates (not just a count of distinct orphan ids)
  - relationship cardinality: for key one-to-many relationships, parent/child row
    counts and the distribution of children per parent (mean/median/max, % with zero
    children, % with more than one child)
  - date validation: for every detected date-like column, how many values parsed
    successfully vs. failed, and the min/max of the values that did parse

Output:
  - Prints a human-readable summary to stdout
  - Writes a machine-readable companion file, data/raw/olist/_profile_summary.json, so
    findings can be diffed across data pulls. This is the only file this script writes;
    docs/DATA_QUALITY_REPORT.md and friends are curated by hand and never touched here.

Usage:
    python scripts/profile_olist.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data" / "raw" / "olist"
OUTPUT_JSON = DATA_DIR / "_profile_summary.json"

# table name -> filename
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

# Candidate primary keys per table. These are hypotheses to be checked against the
# data, not assumptions — see validate_candidate_key(). A key being listed here does
# NOT mean the data actually satisfies uniqueness.
CANDIDATE_PRIMARY_KEYS = {
    "customers": ["customer_id"],
    "orders": ["order_id"],
    "order_items": ["order_id", "order_item_id"],
    "order_payments": ["order_id", "payment_sequential"],
    "order_reviews": ["review_id"],
    "products": ["product_id"],
    "sellers": ["seller_id"],
    "geolocation": [],  # no single-row candidate key; it's a lookup of zip prefixes
    "category_translation": ["product_category_name"],
}

# (child_table, child_fk_column) -> (parent_table, parent_pk_column)
FOREIGN_KEYS = [
    ("orders", "customer_id", "customers", "customer_id"),
    ("order_items", "order_id", "orders", "order_id"),
    ("order_items", "product_id", "products", "product_id"),
    ("order_items", "seller_id", "sellers", "seller_id"),
    ("order_payments", "order_id", "orders", "order_id"),
    ("order_reviews", "order_id", "orders", "order_id"),
    ("products", "product_category_name", "category_translation", "product_category_name"),
]

# (relationship_name, parent_table, parent_key_col, child_table, child_key_col)
# parent_key_col / child_key_col are evaluated against the frame returned by
# _cardinality_frames() below, which handles the customers -> customers_unique
# indirection (customer_unique_id lives on `customers`, not on `orders`).
RELATIONSHIPS = [
    ("orders -> order_items", "orders", "order_id", "order_items", "order_id"),
    ("orders -> order_payments", "orders", "order_id", "order_payments", "order_id"),
    ("orders -> order_reviews", "orders", "order_id", "order_reviews", "order_id"),
    ("customers_unique -> orders", "customers_unique", "customer_unique_id", "orders", "customer_unique_id"),
    ("products -> order_items", "products", "product_id", "order_items", "product_id"),
    ("sellers -> order_items", "sellers", "seller_id", "order_items", "seller_id"),
]

DATE_COLUMN_HINTS = ("_date", "_timestamp")


def load_tables() -> dict[str, pd.DataFrame]:
    dfs = {}
    missing = []
    for name, filename in TABLES.items():
        path = DATA_DIR / filename
        if not path.exists():
            missing.append(filename)
            continue
        df = pd.read_csv(path)
        dfs[name] = df
    if missing:
        print("WARNING: missing expected files in data/raw/olist/:")
        for m in missing:
            print(f"  - {m}")
        print()
    if not dfs:
        print(
            "ERROR: no Olist CSV files found in data/raw/olist/. "
            "Download the dataset and place the CSVs there before running this script.",
            file=sys.stderr,
        )
        sys.exit(1)
    return dfs


def detect_date_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in df.columns if any(hint in c for hint in DATE_COLUMN_HINTS)]


def profile_table(name: str, df: pd.DataFrame) -> dict:
    n_rows, n_cols = df.shape
    col_profiles = {}

    for col in df.columns:
        series = df[col]
        n_null = int(series.isna().sum())
        profile = {
            "dtype": str(series.dtype),
            "n_null": n_null,
            "null_rate": round(n_null / n_rows, 4) if n_rows else None,
            "n_unique": int(series.nunique(dropna=True)),
        }
        if col in detect_date_columns(df):
            parsed = pd.to_datetime(series, errors="coerce")
            profile["min"] = str(parsed.min())
            profile["max"] = str(parsed.max())
        elif pd.api.types.is_numeric_dtype(series):
            profile["min"] = float(series.min()) if n_null < n_rows else None
            profile["max"] = float(series.max()) if n_null < n_rows else None
        col_profiles[col] = profile

    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "duplicate_rows": int(df.duplicated().sum()),
        "columns": col_profiles,
    }


def validate_candidate_key(df: pd.DataFrame, key_cols: list[str]) -> dict:
    """Check a candidate key against the actual data rather than assuming it is valid.

    Reports whether all columns exist, how many duplicate key rows exist, how many
    unique key combinations exist, and whether uniqueness is actually confirmed
    (all columns present AND zero duplicate key rows AND at least one row).
    """
    if not key_cols:
        return {
            "key_columns": key_cols,
            "columns_exist": None,
            "n_rows": len(df),
            "n_duplicate_key_rows": None,
            "n_unique_key_combinations": None,
            "uniqueness_confirmed": False,
            "note": "no candidate key configured for this table",
        }

    missing_cols = [c for c in key_cols if c not in df.columns]
    columns_exist = len(missing_cols) == 0

    if not columns_exist:
        return {
            "key_columns": key_cols,
            "columns_exist": False,
            "missing_columns": missing_cols,
            "n_rows": len(df),
            "n_duplicate_key_rows": None,
            "n_unique_key_combinations": None,
            "uniqueness_confirmed": False,
        }

    n_rows = len(df)
    n_duplicate_key_rows = int(df.duplicated(subset=key_cols).sum())
    n_unique_key_combinations = int(df.drop_duplicates(subset=key_cols).shape[0])
    uniqueness_confirmed = n_rows > 0 and n_duplicate_key_rows == 0

    return {
        "key_columns": key_cols,
        "columns_exist": True,
        "n_rows": n_rows,
        "n_duplicate_key_rows": n_duplicate_key_rows,
        "n_unique_key_combinations": n_unique_key_combinations,
        "uniqueness_confirmed": uniqueness_confirmed,
    }


def validate_candidate_keys(dfs: dict[str, pd.DataFrame]) -> dict:
    results = {}
    for table, key_cols in CANDIDATE_PRIMARY_KEYS.items():
        if table not in dfs:
            continue
        results[table] = validate_candidate_key(dfs[table], key_cols)
    return results


def check_foreign_key(
    child_df: pd.DataFrame, child_col: str, parent_df: pd.DataFrame, parent_col: str
) -> dict | None:
    """Report FK quality: distinct child/parent keys, orphan keys, orphan rows, and
    null FK counts/rates — not just a count of distinct orphan ids.
    """
    if child_col not in child_df.columns or parent_col not in parent_df.columns:
        return None

    child_series = child_df[child_col]
    n_null_fk = int(child_series.isna().sum())
    n_child_rows = len(child_df)
    null_fk_rate = round(n_null_fk / n_child_rows, 4) if n_child_rows else None

    child_keys_nonnull = child_series.dropna()
    distinct_child_keys = set(child_keys_nonnull.unique())
    distinct_parent_keys = set(parent_df[parent_col].dropna().unique())
    orphan_keys = distinct_child_keys - distinct_parent_keys

    n_orphan_rows = int(child_keys_nonnull.isin(orphan_keys).sum())

    return {
        "child_column": child_col,
        "parent_column": parent_col,
        "n_distinct_child_keys": len(distinct_child_keys),
        "n_distinct_parent_keys": len(distinct_parent_keys),
        "n_orphan_keys": len(orphan_keys),
        "orphan_key_rate": round(len(orphan_keys) / len(distinct_child_keys), 4)
        if distinct_child_keys
        else None,
        "n_orphan_rows": n_orphan_rows,
        "orphan_row_rate": round(n_orphan_rows / n_child_rows, 4) if n_child_rows else None,
        "n_null_fk": n_null_fk,
        "null_fk_rate": null_fk_rate,
        "sample_orphans": list(orphan_keys)[:5],
    }


def check_referential_integrity(dfs: dict[str, pd.DataFrame]) -> list[dict]:
    results = []
    for child_table, child_col, parent_table, parent_col in FOREIGN_KEYS:
        if child_table not in dfs or parent_table not in dfs:
            continue
        fk_result = check_foreign_key(dfs[child_table], child_col, dfs[parent_table], parent_col)
        if fk_result is None:
            continue
        fk_result = {"child_table": child_table, "parent_table": parent_table, **fk_result}
        results.append(fk_result)
    return results


def _cardinality_frames(dfs: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Build the lookup of frames used by relationship cardinality checks.

    Adds a synthetic `customers_unique` frame (one row per customer_unique_id) and an
    `orders` frame enriched with `customer_unique_id` (joined from `customers`), so the
    customers_unique -> orders relationship can be computed the same way as the others.
    """
    frames = dict(dfs)
    if "customers" in dfs and "orders" in dfs:
        customers = dfs["customers"]
        if "customer_unique_id" in customers.columns and "customer_id" in customers.columns:
            frames["customers_unique"] = customers.drop_duplicates(subset=["customer_unique_id"])[
                ["customer_unique_id"]
            ]
            orders_enriched = dfs["orders"].merge(
                customers[["customer_id", "customer_unique_id"]],
                on="customer_id",
                how="left",
            )
            frames["orders"] = orders_enriched
    return frames


def compute_relationship_cardinality(
    parent_df: pd.DataFrame, parent_key: str, child_df: pd.DataFrame, child_key: str
) -> dict | None:
    if parent_key not in parent_df.columns or child_key not in child_df.columns:
        return None

    n_parent_rows = len(parent_df)
    n_child_rows = len(child_df)

    parent_keys = parent_df[parent_key].dropna().unique()
    children_per_parent = child_df[child_key].value_counts()
    # reindex so parents with zero matching children are included as 0, not omitted
    counts = children_per_parent.reindex(parent_keys, fill_value=0)

    n_parents = len(counts)
    pct_zero_children = round(float((counts == 0).mean()) * 100, 2) if n_parents else None
    pct_more_than_one_child = round(float((counts > 1).mean()) * 100, 2) if n_parents else None

    return {
        "n_parent_rows": n_parent_rows,
        "n_child_rows": n_child_rows,
        "n_distinct_parents": n_parents,
        "avg_children_per_parent": round(float(counts.mean()), 4) if n_parents else None,
        "median_children_per_parent": float(counts.median()) if n_parents else None,
        "max_children_per_parent": int(counts.max()) if n_parents else None,
        "pct_parents_with_zero_children": pct_zero_children,
        "pct_parents_with_more_than_one_child": pct_more_than_one_child,
    }


def check_relationship_cardinality(dfs: dict[str, pd.DataFrame]) -> dict:
    frames = _cardinality_frames(dfs)
    results = {}
    for rel_name, parent_table, parent_key, child_table, child_key in RELATIONSHIPS:
        if parent_table not in frames or child_table not in frames:
            continue
        result = compute_relationship_cardinality(
            frames[parent_table], parent_key, frames[child_table], child_key
        )
        if result is not None:
            results[rel_name] = result
    return results


def validate_date_column(series: pd.Series) -> dict:
    n_total = len(series)
    n_null = int(series.isna().sum())
    parsed = pd.to_datetime(series, errors="coerce")
    # a value "fails to parse" if it was non-null in the source but became null after
    # parsing; pre-existing nulls are not parse failures
    n_failed_parse = int(parsed.isna().sum() - n_null)
    n_failed_parse = max(n_failed_parse, 0)
    n_parseable = n_total - n_null - n_failed_parse

    return {
        "n_total": n_total,
        "n_parseable": n_parseable,
        "n_failed_parse": n_failed_parse,
        "failed_parse_rate": round(n_failed_parse / n_total, 4) if n_total else None,
        "min": str(parsed.min()) if n_parseable else None,
        "max": str(parsed.max()) if n_parseable else None,
    }


def check_date_quality(dfs: dict[str, pd.DataFrame]) -> dict:
    results = {}
    for table, df in dfs.items():
        date_cols = detect_date_columns(df)
        if not date_cols:
            continue
        results[table] = {col: validate_date_column(df[col]) for col in date_cols}
    return results


def print_table_summary(name: str, profile: dict, key_validation: dict | None) -> None:
    print(f"\n=== {name} ===")
    print(f"rows: {profile['n_rows']:,}  cols: {profile['n_cols']}")
    if key_validation is not None:
        print(
            f"candidate key: {key_validation.get('key_columns')}  "
            f"columns_exist={key_validation.get('columns_exist')}  "
            f"duplicate_key_rows={key_validation.get('n_duplicate_key_rows')}  "
            f"unique_key_combinations={key_validation.get('n_unique_key_combinations')}  "
            f"uniqueness_confirmed={key_validation.get('uniqueness_confirmed')}"
        )
    print(f"fully duplicate rows: {profile['duplicate_rows']}")
    print(f"{'column':30} {'dtype':12} {'null_rate':10} {'n_unique':10}")
    for col, cp in profile["columns"].items():
        print(f"{col:30} {cp['dtype']:12} {str(cp['null_rate']):10} {cp['n_unique']:10}")


def print_referential_summary(ri_results: list[dict]) -> None:
    print("\n=== Foreign-Key Quality ===")
    for r in ri_results:
        print(
            f"{r['child_table']}.{r['child_column']} -> {r['parent_table']}.{r['parent_column']}:\n"
            f"    distinct_child_keys={r['n_distinct_child_keys']} distinct_parent_keys={r['n_distinct_parent_keys']}\n"
            f"    orphan_keys={r['n_orphan_keys']} (rate={r['orphan_key_rate']})  "
            f"orphan_rows={r['n_orphan_rows']} (rate={r['orphan_row_rate']})\n"
            f"    null_fk={r['n_null_fk']} (rate={r['null_fk_rate']})"
        )
        if r["n_orphan_keys"]:
            print(f"    sample orphans: {r['sample_orphans']}")


def print_cardinality_summary(cardinality_results: dict) -> None:
    print("\n=== Relationship Cardinality ===")
    for rel_name, r in cardinality_results.items():
        print(
            f"{rel_name}:\n"
            f"    parent_rows={r['n_parent_rows']:,} child_rows={r['n_child_rows']:,} distinct_parents={r['n_distinct_parents']:,}\n"
            f"    avg_children/parent={r['avg_children_per_parent']}  median={r['median_children_per_parent']}  max={r['max_children_per_parent']}\n"
            f"    pct_zero_children={r['pct_parents_with_zero_children']}%  pct_more_than_one_child={r['pct_parents_with_more_than_one_child']}%"
        )


def print_date_quality_summary(date_results: dict) -> None:
    print("\n=== Date Validation ===")
    for table, cols in date_results.items():
        print(f"-- {table} --")
        for col, r in cols.items():
            print(
                f"    {col:35} parseable={r['n_parseable']:>8}  failed={r['n_failed_parse']:>6} "
                f"(rate={r['failed_parse_rate']})  min={r['min']}  max={r['max']}"
            )


def main() -> None:
    dfs = load_tables()

    profiles = {name: profile_table(name, df) for name, df in dfs.items()}
    key_validations = validate_candidate_keys(dfs)
    ri_results = check_referential_integrity(dfs)
    cardinality_results = check_relationship_cardinality(dfs)
    date_results = check_date_quality(dfs)

    for name, profile in profiles.items():
        print_table_summary(name, profile, key_validations.get(name))

    print_referential_summary(ri_results)
    print_cardinality_summary(cardinality_results)
    print_date_quality_summary(date_results)

    output = {
        "tables": profiles,
        "candidate_keys": key_validations,
        "foreign_keys": ri_results,
        "relationship_cardinality": cardinality_results,
        "date_quality": date_results,
    }
    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nMachine-readable summary written to {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
