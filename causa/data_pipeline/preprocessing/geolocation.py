"""
geolocation.py

Builds a derived, validated geolocation dimension from the raw Olist geolocation
table (`olist_geolocation_dataset.csv`). This module is preprocessing only — no
agents, LLM pipelines, frontend, or KPI logic live here, and it does not join the
result into `customers` or `sellers`; it only prepares a standalone dimension keyed
by ZIP code prefix.

Why this exists
----------------
`geolocation_zip_code_prefix` is NOT unique in the raw table: many lat/lng samples
(and, in some cases, disagreeing city/state labels) share the same prefix. Both
`customers.customer_zip_code_prefix` and `sellers.seller_zip_code_prefix` are meant to
join against a zip-prefix key, so a one-row-per-prefix dimension is needed before any
such join can happen. This module builds that dimension without silently discarding
disagreement — every ambiguous prefix is aggregated using an explicit, documented rule
AND flagged so downstream consumers can decide how much to trust it.

Pipeline stages (see `build_geolocation_dimension` for the orchestrating entry point):
  1. `load_raw_geolocation`       — read the raw CSV, untouched.
  2. `profile_raw_geolocation`    — pre-aggregation profiling (dup rows, prefix
                                     cardinality, multi-city/state counts, coordinate
                                     spread/outliers).
  3. `aggregate_geolocation`      — one canonical row per ZIP prefix: median lat/lng,
                                     mode city, mode state, plus an ambiguity report.
  4. `validate_geolocation_dimension` — confirms the output key is unique and the
                                     row count matches distinct prefixes.

Aggregation rule (documented in full in docs/GEOLOCATION_POLICY.md):
  - latitude / longitude: median per prefix (robust to the long tail of outlier
    coordinates observed in this dataset; unlike mean, unaffected by a single bad
    sample far from the rest).
  - city / state: mode (most frequent value) per prefix, ties broken deterministically
    by sorting candidates alphabetically and taking the first — never by row order,
    so output is stable across re-runs and re-orderings of the input.
  - `is_ambiguous` is True whenever a prefix has more than one distinct city OR more
    than one distinct state in the raw data, regardless of how the tie was broken.
    Ambiguity is never silently resolved into a false sense of certainty.

Raw data handling: this module only reads the raw CSV via pandas; it never opens the
source file in write mode and never mutates the DataFrame loaded from it in place.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_GEOLOCATION_PATH = REPO_ROOT / "data" / "raw" / "olist" / "olist_geolocation_dataset.csv"

RAW_ZIP_COL = "geolocation_zip_code_prefix"
RAW_LAT_COL = "geolocation_lat"
RAW_LNG_COL = "geolocation_lng"
RAW_CITY_COL = "geolocation_city"
RAW_STATE_COL = "geolocation_state"

# Output schema, in order.
OUTPUT_COLUMNS = [
    "zip_code_prefix",
    "latitude",
    "longitude",
    "city",
    "state",
    "source_row_count",
    "is_ambiguous",
]

# Degrees of lat/lng standard deviation above which a prefix's coordinate spread is
# flagged as a notable outlier when profiling (roughly >11km of spread; see
# docs/GEOLOCATION_POLICY.md for the derivation). This threshold is used only for the
# profiling report (step 7) — it does not affect the aggregation itself.
COORDINATE_SPREAD_OUTLIER_THRESHOLD_DEGREES = 0.1

PROVENANCE = {
    "derived_from": "data/raw/olist/olist_geolocation_dataset.csv",
    "aggregation": "one row per geolocation_zip_code_prefix",
    "coordinate_rule": "median(geolocation_lat), median(geolocation_lng) per prefix",
    "categorical_rule": "mode(geolocation_city), mode(geolocation_state) per prefix; "
    "ties broken alphabetically for determinism",
    "note": "Derived dimension only. The raw source file is never modified. Not yet "
    "joined to customers/sellers.",
}


@dataclass
class GeolocationProfile:
    """Pre-aggregation profiling results (requirement #7)."""

    n_raw_rows: int
    n_exact_duplicate_rows: int
    exact_duplicate_rate: float
    n_distinct_prefixes: int
    n_prefixes_multi_city: int
    n_prefixes_multi_city_normalized: int
    n_prefixes_multi_state: int
    coordinate_spread_outlier_threshold_degrees: float
    n_prefixes_with_coordinate_outliers: int
    max_lat_std_degrees: float
    max_lng_std_degrees: float
    rows_per_prefix_min: int
    rows_per_prefix_median: float
    rows_per_prefix_max: int

    def as_dict(self) -> dict:
        return {
            "n_raw_rows": self.n_raw_rows,
            "n_exact_duplicate_rows": self.n_exact_duplicate_rows,
            "exact_duplicate_rate": self.exact_duplicate_rate,
            "n_distinct_prefixes": self.n_distinct_prefixes,
            "n_prefixes_multi_city": self.n_prefixes_multi_city,
            "n_prefixes_multi_city_normalized": self.n_prefixes_multi_city_normalized,
            "n_prefixes_multi_state": self.n_prefixes_multi_state,
            "coordinate_spread_outlier_threshold_degrees": self.coordinate_spread_outlier_threshold_degrees,
            "n_prefixes_with_coordinate_outliers": self.n_prefixes_with_coordinate_outliers,
            "max_lat_std_degrees": self.max_lat_std_degrees,
            "max_lng_std_degrees": self.max_lng_std_degrees,
            "rows_per_prefix_min": self.rows_per_prefix_min,
            "rows_per_prefix_median": self.rows_per_prefix_median,
            "rows_per_prefix_max": self.rows_per_prefix_max,
        }


@dataclass
class AmbiguityReport:
    """Explicit record of every ZIP prefix where the raw data disagreed with itself
    (requirement #8/#9) — produced alongside the aggregate, never hidden inside it.
    """

    n_ambiguous_prefixes: int
    n_multi_city_prefixes: int
    n_multi_state_prefixes: int
    ambiguous_prefixes: pd.DataFrame = field(repr=False)

    def as_dict(self) -> dict:
        return {
            "n_ambiguous_prefixes": self.n_ambiguous_prefixes,
            "n_multi_city_prefixes": self.n_multi_city_prefixes,
            "n_multi_state_prefixes": self.n_multi_state_prefixes,
        }


def load_raw_geolocation(path: Path = RAW_GEOLOCATION_PATH) -> pd.DataFrame:
    """Read the raw geolocation CSV, unmodified. Read-only: never writes to `path`."""
    return pd.read_csv(path)


def _fold_city_name(city: str) -> str:
    """Lowercase + accent-fold a city name, for *diagnostic comparison only*.

    Used exclusively to measure how much of the raw "multi-city per prefix" signal is
    caused by case/accent variants of the same name (e.g. "sao paulo" vs "são
    paulo") rather than genuinely different places. This folded form is NEVER used to
    choose the output `city` value — the aggregation step always operates on the raw
    strings, so `is_ambiguous` reflects the data exactly as-is.
    """
    s = str(city).strip().lower()
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def profile_raw_geolocation(df: pd.DataFrame) -> GeolocationProfile:
    """Profile the raw geolocation table before any aggregation (requirement #7).

    Reports duplicate rows, distinct ZIP prefixes, prefixes with disagreeing
    city/state, and coordinate spread/outliers — all computed on the raw data, prior
    to collapsing anything down to one row per prefix.
    """
    n_raw_rows = len(df)
    n_dupes = int(df.duplicated().sum())

    by_prefix = df.groupby(RAW_ZIP_COL)
    n_distinct_prefixes = by_prefix.ngroups

    n_multi_city = int((by_prefix[RAW_CITY_COL].nunique() > 1).sum())
    n_multi_state = int((by_prefix[RAW_STATE_COL].nunique() > 1).sum())

    # Diagnostic only (see _fold_city_name docstring): how many "multi-city" prefixes
    # remain multi-city after folding case/accents, vs. how many are just spelling
    # variants of the same name.
    folded_city = df[RAW_CITY_COL].map(_fold_city_name)
    n_multi_city_normalized = int(
        (df.assign(_city_folded=folded_city).groupby(RAW_ZIP_COL)["_city_folded"].nunique() > 1).sum()
    )

    lat_std = by_prefix[RAW_LAT_COL].std().fillna(0.0)
    lng_std = by_prefix[RAW_LNG_COL].std().fillna(0.0)
    is_outlier = (lat_std > COORDINATE_SPREAD_OUTLIER_THRESHOLD_DEGREES) | (
        lng_std > COORDINATE_SPREAD_OUTLIER_THRESHOLD_DEGREES
    )

    rows_per_prefix = by_prefix.size()

    return GeolocationProfile(
        n_raw_rows=n_raw_rows,
        n_exact_duplicate_rows=n_dupes,
        exact_duplicate_rate=round(n_dupes / n_raw_rows, 4) if n_raw_rows else 0.0,
        n_distinct_prefixes=n_distinct_prefixes,
        n_prefixes_multi_city=n_multi_city,
        n_prefixes_multi_city_normalized=n_multi_city_normalized,
        n_prefixes_multi_state=n_multi_state,
        coordinate_spread_outlier_threshold_degrees=COORDINATE_SPREAD_OUTLIER_THRESHOLD_DEGREES,
        n_prefixes_with_coordinate_outliers=int(is_outlier.sum()),
        max_lat_std_degrees=round(float(lat_std.max()), 6) if n_distinct_prefixes else 0.0,
        max_lng_std_degrees=round(float(lng_std.max()), 6) if n_distinct_prefixes else 0.0,
        rows_per_prefix_min=int(rows_per_prefix.min()) if n_distinct_prefixes else 0,
        rows_per_prefix_median=float(rows_per_prefix.median()) if n_distinct_prefixes else 0.0,
        rows_per_prefix_max=int(rows_per_prefix.max()) if n_distinct_prefixes else 0,
    )


def _mode_deterministic(series: pd.Series) -> str:
    """Most frequent value in `series`; ties broken alphabetically so the result is
    deterministic regardless of input row order (requirement: deterministic output).
    """
    counts = series.value_counts()
    top_count = counts.iloc[0]
    tied_candidates = sorted(counts[counts == top_count].index)
    return tied_candidates[0]


def build_ambiguity_report(df: pd.DataFrame) -> AmbiguityReport:
    """Identify every ZIP prefix where the raw rows disagree on city and/or state
    (requirements #8/#9). This is computed independently of the aggregate so the
    ambiguity signal cannot be lost or silently smoothed over during aggregation.
    """
    by_prefix = df.groupby(RAW_ZIP_COL)
    city_nunique = by_prefix[RAW_CITY_COL].nunique()
    state_nunique = by_prefix[RAW_STATE_COL].nunique()

    multi_city_prefixes = set(city_nunique[city_nunique > 1].index)
    multi_state_prefixes = set(state_nunique[state_nunique > 1].index)
    ambiguous_prefixes = multi_city_prefixes | multi_state_prefixes

    rows = []
    for prefix in sorted(ambiguous_prefixes):
        group = df[df[RAW_ZIP_COL] == prefix]
        rows.append(
            {
                "zip_code_prefix": prefix,
                "n_source_rows": len(group),
                "n_distinct_cities": int(group[RAW_CITY_COL].nunique()),
                "distinct_cities": sorted(group[RAW_CITY_COL].unique().tolist()),
                "n_distinct_states": int(group[RAW_STATE_COL].nunique()),
                "distinct_states": sorted(group[RAW_STATE_COL].unique().tolist()),
                "chosen_city": _mode_deterministic(group[RAW_CITY_COL]),
                "chosen_state": _mode_deterministic(group[RAW_STATE_COL]),
            }
        )

    report_df = pd.DataFrame(
        rows,
        columns=[
            "zip_code_prefix",
            "n_source_rows",
            "n_distinct_cities",
            "distinct_cities",
            "n_distinct_states",
            "distinct_states",
            "chosen_city",
            "chosen_state",
        ],
    )

    return AmbiguityReport(
        n_ambiguous_prefixes=len(ambiguous_prefixes),
        n_multi_city_prefixes=len(multi_city_prefixes),
        n_multi_state_prefixes=len(multi_state_prefixes),
        ambiguous_prefixes=report_df,
    )


def aggregate_geolocation(df: pd.DataFrame) -> tuple[pd.DataFrame, AmbiguityReport]:
    """Collapse the raw geolocation table to exactly one canonical row per ZIP prefix.

    - latitude / longitude: median per prefix.
    - city / state: mode per prefix (deterministic tie-break, see `_mode_deterministic`).
    - source_row_count: how many raw rows fed into this prefix's aggregate.
    - is_ambiguous: True if the raw rows disagreed on city and/or state for this prefix.

    Returns the aggregated DataFrame together with the full ambiguity report so callers
    always see both — the aggregate alone never has to be trusted blindly.
    """
    ambiguity = build_ambiguity_report(df)
    ambiguous_prefix_set = set(ambiguity.ambiguous_prefixes["zip_code_prefix"])

    by_prefix = df.groupby(RAW_ZIP_COL)

    agg = by_prefix.agg(
        latitude=(RAW_LAT_COL, "median"),
        longitude=(RAW_LNG_COL, "median"),
        source_row_count=(RAW_ZIP_COL, "size"),
    )
    agg["city"] = by_prefix[RAW_CITY_COL].apply(_mode_deterministic)
    agg["state"] = by_prefix[RAW_STATE_COL].apply(_mode_deterministic)

    agg = agg.reset_index().rename(columns={RAW_ZIP_COL: "zip_code_prefix"})
    agg["is_ambiguous"] = agg["zip_code_prefix"].isin(ambiguous_prefix_set)
    agg["source_row_count"] = agg["source_row_count"].astype(int)

    agg = agg[OUTPUT_COLUMNS].sort_values("zip_code_prefix").reset_index(drop=True)

    return agg, ambiguity


def validate_geolocation_dimension(agg: pd.DataFrame, profile: GeolocationProfile) -> dict:
    """Validate the aggregated dimension: unique key, expected row count, and no nulls
    in required columns. Raises AssertionError on any violation — this function is
    meant to fail loudly rather than let a broken dimension pass silently.
    """
    n_rows = len(agg)
    n_unique_keys = agg["zip_code_prefix"].nunique()
    key_is_unique = n_rows == n_unique_keys
    matches_distinct_prefix_count = n_rows == profile.n_distinct_prefixes
    has_required_columns = list(agg.columns) == OUTPUT_COLUMNS
    no_nulls_in_key = agg["zip_code_prefix"].isna().sum() == 0
    no_nulls_in_coords = agg[["latitude", "longitude"]].isna().sum().sum() == 0

    result = {
        "n_rows": n_rows,
        "n_unique_keys": int(n_unique_keys),
        "key_is_unique": bool(key_is_unique),
        "matches_distinct_prefix_count": bool(matches_distinct_prefix_count),
        "has_required_columns": bool(has_required_columns),
        "no_nulls_in_key": bool(no_nulls_in_key),
        "no_nulls_in_coordinates": bool(no_nulls_in_coords),
        "passed": bool(
            key_is_unique
            and matches_distinct_prefix_count
            and has_required_columns
            and no_nulls_in_key
            and no_nulls_in_coords
        ),
    }

    assert key_is_unique, "zip_code_prefix is not unique in the aggregated dimension"
    assert matches_distinct_prefix_count, (
        "aggregated row count does not match the number of distinct prefixes in the raw data"
    )
    assert has_required_columns, f"output columns do not match expected schema {OUTPUT_COLUMNS}"
    assert no_nulls_in_key, "zip_code_prefix contains nulls"
    assert no_nulls_in_coords, "latitude/longitude contain nulls"

    return result


@dataclass
class GeolocationDimensionResult:
    """Full output of the pipeline: the dimension itself plus every report needed to
    trust (or scrutinize) it."""

    dimension: pd.DataFrame
    profile: GeolocationProfile
    ambiguity: AmbiguityReport
    validation: dict
    provenance: dict = field(default_factory=lambda: dict(PROVENANCE))


def build_geolocation_dimension(path: Path = RAW_GEOLOCATION_PATH) -> GeolocationDimensionResult:
    """End-to-end pipeline: load raw data -> profile -> aggregate -> validate.

    Does not modify the raw CSV and does not join the result into customers/sellers.
    """
    raw = load_raw_geolocation(path)
    profile = profile_raw_geolocation(raw)
    dimension, ambiguity = aggregate_geolocation(raw)
    validation = validate_geolocation_dimension(dimension, profile)

    return GeolocationDimensionResult(
        dimension=dimension,
        profile=profile,
        ambiguity=ambiguity,
        validation=validation,
    )


def _print_summary(result: GeolocationDimensionResult) -> None:
    print("=== Geolocation: raw profile ===")
    for k, v in result.profile.as_dict().items():
        print(f"  {k}: {v}")

    print("\n=== Geolocation: ambiguity report ===")
    for k, v in result.ambiguity.as_dict().items():
        print(f"  {k}: {v}")
    if result.ambiguity.n_ambiguous_prefixes:
        print("  sample ambiguous prefixes:")
        print(result.ambiguity.ambiguous_prefixes.head(5).to_string(index=False))

    print("\n=== Geolocation: validation ===")
    for k, v in result.validation.items():
        print(f"  {k}: {v}")

    print("\n=== Geolocation: dimension preview ===")
    print(result.dimension.head(5).to_string(index=False))
    print(f"\ntotal dimension rows: {len(result.dimension):,}")


if __name__ == "__main__":
    result = build_geolocation_dimension()
    _print_summary(result)
