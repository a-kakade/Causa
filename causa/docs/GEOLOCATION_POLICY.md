# Geolocation Dimension — Aggregation Policy

Status: implemented and validated against the dataset in `data/raw/olist/` (profiled
2026-08-26) via `data_pipeline/preprocessing/geolocation.py`. This document explains
*why* the geolocation dimension is built the way it is. It does not cover joining the
dimension into `customers`/`sellers` — that is explicitly out of scope for this
milestone.

## Problem

`olist_geolocation_dataset.csv` is not a clean dimension table: `geolocation_zip_code_prefix`
is not unique. It carries many lat/lng samples per prefix (mean ~52.6 rows/prefix,
up to 1,146 for a single prefix), and a meaningful minority of prefixes even disagree
on city or state. Both `customers.customer_zip_code_prefix` and
`sellers.seller_zip_code_prefix` are meant to join against a zip-prefix key, so a
one-row-per-prefix dimension has to exist before either join can happen — and it has to
be built in a way that doesn't quietly discard the disagreement in the source data.

## Pipeline

`data_pipeline/preprocessing/geolocation.py` — `build_geolocation_dimension()`:

1. `load_raw_geolocation` — reads the raw CSV via pandas. Read-only; never opens the
   source file for writing and never mutates the loaded DataFrame in place.
2. `profile_raw_geolocation` — profiles the raw data *before* any aggregation:
   duplicate rows, distinct ZIP prefixes, prefixes with more than one distinct
   city/state, coordinate spread, and rows-per-prefix distribution.
3. `aggregate_geolocation` — collapses to exactly one row per ZIP prefix using the
   rule below, and returns an `AmbiguityReport` alongside the aggregate.
4. `validate_geolocation_dimension` — asserts the output key is unique, the row count
   matches the number of distinct raw prefixes, the schema matches, and there are no
   nulls in the key or coordinate columns. Raises `AssertionError` on any violation —
   it fails loudly rather than silently shipping a broken dimension.

Run it directly with:

```bash
python data_pipeline/preprocessing/geolocation.py
```

This prints the profile, ambiguity report, and validation result to stdout. It does
not write any output file — the derived dimension is returned in-memory
(`GeolocationDimensionResult.dimension`) for the caller to persist, join, or inspect
as needed in a later milestone.

## Output schema

One row per `zip_code_prefix`:

| Column | Type | Description |
|---|---|---|
| `zip_code_prefix` | int | The ZIP prefix key — unique in the output, validated. |
| `latitude` | float | Median latitude across all raw rows for this prefix. |
| `longitude` | float | Median longitude across all raw rows for this prefix. |
| `city` | string | Most frequent (mode) city name for this prefix among raw rows. |
| `state` | string | Most frequent (mode) state code for this prefix among raw rows. |
| `source_row_count` | int | How many raw rows fed into this prefix's aggregate. |
| `is_ambiguous` | bool | True if the raw rows disagreed on city and/or state for this prefix. |

Provenance metadata (`GeolocationDimensionResult.provenance`) records that this table
is a derived aggregation of `data/raw/olist/olist_geolocation_dataset.csv`, and states
the exact aggregation rule, so the derivation is traceable without needing to read the
source code.

## Aggregation rule and why

- **Latitude / longitude → median, not mean.** The raw data has real coordinate
  outliers (max per-prefix lat/lng standard deviation observed: 41.95° / 34.27° —
  clearly a bad sample far from the rest, since 1° ≈ 111km and Brazil itself only
  spans ~39° of latitude). Median is robust to a single outlier sample in a way mean
  is not, and is the more defensible choice for a "typical location" of a prefix.
- **City / state → mode (most frequent value).** The single most common value among a
  prefix's raw rows is the most defensible "representative" label, given that no
  ground-truth authority table is available to resolve disagreement.
- **Tie-breaking is deterministic, not row-order-dependent.** When two or more values
  are tied for most frequent, the tie is broken by sorting the tied candidates
  alphabetically and taking the first (`_mode_deterministic`). This guarantees the
  same output regardless of how the raw rows happen to be ordered — verified by
  `test_aggregate_is_deterministic_regardless_of_row_order`.
- **Ambiguity is never silently resolved into false certainty.** `is_ambiguous` is
  `True` whenever a prefix's raw rows disagreed on city and/or state, *even though* a
  single value was still chosen for the `city`/`state` columns (a one-row-per-prefix
  output requires picking something). The full detail behind an ambiguous choice — all
  candidate values, not just the winner — is preserved separately in the
  `AmbiguityReport` returned alongside the dimension (`build_ambiguity_report`), so a
  downstream consumer can always see what was collapsed and by how much.

## What counts as "ambiguous" — and an important caveat found during profiling

A prefix is flagged `is_ambiguous = True` if it has more than one distinct **raw**
city string or more than one distinct state. On the real dataset this flags **8,559 of
19,015 prefixes (45.0%)** — at first glance a strikingly high ambiguity rate.

Profiling traced the cause: **8,007 of those 8,556 multi-city prefixes (93.6%) are not
genuinely different places** — they are case/accent spelling variants of the exact same
city name (e.g. `"sao paulo"` vs. `"são paulo"`, both valid UTF-8, differing only in
diacritics/casing). Folding case and accents for comparison purposes only
(`_prefixes_multi_city_normalized` in the profile — a diagnostic figure, computed
solely for this report) drops the multi-city count from 8,556 down to **549** — the
portion of prefixes with truly distinct city names (e.g. a prefix spanning both "sao
paulo" and a genuinely different neighboring municipality like "sao bernardo do
campo").

**This normalization is diagnostic only and does NOT change the aggregation.** The
`city` and `is_ambiguous` output columns are still computed from the raw,
un-normalized strings, per requirement #8 ("do not silently choose a value for
ambiguous prefixes" — normalizing away spelling variants before flagging ambiguity
would itself be a silent, unrequested data-cleaning decision). The gap between the raw
and normalized multi-city counts is reported so a future milestone can decide,
explicitly, whether to normalize city names as a preprocessing step — that decision is
out of scope here.

State disagreement is much rarer and not explained by spelling variants: only **8
prefixes (0.04%)** have more than one distinct state code, which is a stronger true-
ambiguity signal than the city figure.

## Observed aggregation statistics (this dataset, profiled 2026-08-26)

| Metric | Value |
|---|---|
| Raw rows | 1,000,163 |
| Exact duplicate rows | 261,831 (26.18%) |
| Distinct ZIP prefixes | 19,015 |
| Prefixes with >1 distinct city (raw strings) | 8,556 (45.0%) |
| Prefixes with >1 distinct city (case/accent-folded, diagnostic only) | 549 (2.9%) |
| Prefixes with >1 distinct state | 8 (0.04%) |
| Prefixes flagged `is_ambiguous` (city OR state) | 8,559 (45.0%) |
| Rows per prefix — min / median / max | 1 / 29 / 1,146 |
| Prefixes with coordinate spread > 0.1° lat or lng (~11km) | 506 |
| Max per-prefix lat standard deviation | 41.95° |
| Max per-prefix lng standard deviation | 34.27° |
| Output dimension rows | 19,015 (one per distinct prefix) |
| Output key uniqueness | Confirmed — validated, zero duplicates |

## Explicitly out of scope for this module

- Joining the dimension to `customers` or `sellers` (their prefix columns are not
  touched here at all).
- Deciding whether/how to normalize city name spelling (flagged above as a future
  decision, not made here).
- Any KPI, geospatial-distance, or region-rollup logic.
- Any change to the raw CSV — it is read-only input and is never modified. Verified by
  `test_aggregate_does_not_mutate_raw_input` and by checksum comparison of the raw file
  before/after running the pipeline.
