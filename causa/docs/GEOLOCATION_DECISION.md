# Geolocation Decision

## Raw state (re-confirmed, not re-litigated — see Step 1's `DATA_FOUNDATION_REPORT.md` §H/§C)

- 1,000,163 rows, 26.18% exact-duplicate rows.
- No usable single- or composite-column primary key exists — `geolocation_zip_code_prefix`
  alone has only 19,015 distinct values across 1,000,163 rows (many raw lat/lng
  samples per prefix), so it cannot be joined 1:1 to anything without a prior
  aggregation step.

## Does Causa actually need it?

**No — not for the canonical layer built in this step.** `dim_customer` already
carries `customer_state` and `customer_city` (0% null, clean, directly usable);
`dim_seller` already carries `seller_state` and `seller_city` (same). Every
segmentation, materiality, or persona scenario identified in the prior EDA
(`docs/INVESTIGATION_SCENARIOS.md` §5) operates at the **state** level, which these
existing fields already support with zero additional joins, zero aggregation risk,
and zero data-quality overhead. Zip-prefix or lat/lng-level geography was not
identified as a requirement for any KPI, driver, or scenario documented so far.

## Decision

**`geolocation` is NOT joined into the canonical layer in Step 2.** No
`dim_geolocation` table is produced. This is a deliberate exclusion, not an
oversight — re-stated here so a future step doesn't need to re-derive the
reasoning.

## If geolocation becomes necessary later

Should a future step require zip/city/lat-lng-level geography (e.g., a
delivery-distance calculation, or a city-level rather than state-level
segmentation), it must **not** be joined directly. The required aggregation step,
not implemented here, would be:

1. Group `geolocation` by `geolocation_zip_code_prefix`.
2. Reduce to one row per prefix — e.g., median `geolocation_lat`/`geolocation_lng`
   (robust to the exact-duplicate and near-duplicate noise), and the modal
   `geolocation_city`/`geolocation_state` for that prefix (a single prefix can
   span multiple recorded city-name spellings/casings, not audited in this pass).
3. Only then join the resulting `dim_geolocation` (1 row per zip prefix) to
   `dim_customer.customer_zip_code_prefix` / `dim_seller.seller_zip_code_prefix` —
   both of which are many-to-one against the reduced table, which is a safe join.
4. Explicitly document the reduction method chosen (median vs. mean vs. mode) in
   an updated version of this file, since different reductions could produce
   materially different lat/lng points for sprawling zip prefixes — this was not
   evaluated in Step 2 because the table was not built.

## Consequence of not building it now

Any future geography-dependent feature that needs finer-than-state granularity is
**blocked** until the aggregation above is implemented and documented. This is
recorded here explicitly so it is not rediscovered as a surprise later.
