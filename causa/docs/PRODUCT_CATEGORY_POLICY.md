# Product Category Enrichment — Translation Policy

Status: implemented and validated against the dataset in `data/raw/olist/` (profiled
2026-08-26) via `data_pipeline/preprocessing/product_categories.py`. This document
explains *why* category enrichment is built the way it is. It does not cover any KPI,
agent, or application-layer usage of the enriched category — that is explicitly out of
scope for this milestone.

## Problem

`products.product_category_name` is in Portuguese. The official Olist
`category_translation` table (`product_category_name_translation.csv`) supplies
English translations for 71 categories, but two gaps exist in the real data:

- **610 products** (1.85% of all products) have a **null** `product_category_name`.
- **2 non-null Portuguese categories** used by products are **absent** from the
  official translation table: `pc_gamer` and
  `portateis_cozinha_e_preparadores_de_alimentos`.

Every product must still resolve to some category label for downstream use — silently
dropping products with unresolved categories is explicitly disallowed.

## Pipeline

`data_pipeline/preprocessing/product_categories.py` — `build_product_category_enrichment()`:

1. `load_products` / `load_category_translation` / `load_overrides` — read the raw
   `products` and `category_translation` CSVs, and the curated override YAML. Read-only;
   the raw CSVs are never modified.
2. `enrich_categories` — resolves `product_category_name_en` and
   `category_translation_source` for every product, one row per product, same row
   order as the input `products` table (never drops a row).
3. `profile_category_enrichment` — coverage reporting (see below).
4. `validate_full_coverage` — asserts every non-null category resolved through an
   official translation, a curated override, or `Uncategorized`. Raises
   `AssertionError` on any violation — fails loudly rather than shipping an
   unresolved category silently.

Run it directly with:

```bash
python data_pipeline/preprocessing/product_categories.py
```

This prints the coverage profile, validation result, and a preview to stdout. It does
not write any output file — the enrichment table is returned in-memory
(`ProductCategoryEnrichmentResult.enrichment`) for a caller to persist or attach to
`products` in a later milestone.

## Output schema

One row per product (same order/index as `products`), never dropping a row:

| Column | Type | Description |
|---|---|---|
| `product_category_name_pt` | string or null | The original Portuguese category, preserved exactly as-is — including preserving null as null, never overwritten. |
| `product_category_name_en` | string | The resolved English label. Always populated — never null. |
| `category_translation_source` | string | How the English label was resolved: `"official"`, `"override"`, or `"null_category"`. |

## Resolution precedence

For each product's `product_category_name`, resolve `product_category_name_en` in
this strict order (`resolve_category`):

1. **Official translation** (`category_translation_source = "official"`) — looked up
   directly in `category_translation`, if the Portuguese category is present there.
2. **Curated override** (`category_translation_source = "override"`) — looked up in
   `data/reference/product_category_overrides.yaml`, used only when the category is
   absent from the official table.
3. **Null category** (`category_translation_source = "null_category"`) — the fallback
   label `Uncategorized`, used only when `product_category_name` itself is null.

If a **non-null** category matches neither the official table nor an override, it is
never silently mapped to anything (in particular, never silently mapped to
`Uncategorized`, which is reserved exclusively for true nulls) — it is surfaced as
`category_translation_source = "unresolved"` internally, and
`validate_full_coverage` raises an `AssertionError` naming the exact override file to
update. On the current dataset this never happens (see coverage stats below), but the
pipeline is built to fail loudly rather than assume no new gaps will ever appear as the
dataset is refreshed.

Official translation is checked **before** the override table, so if a category is
ever added to the official Olist table later, it silently and correctly takes
precedence over any override — the override table is purely a gap-filler, not a
permanent replacement for the official source.

## Curated overrides

Overrides live in `data/reference/product_category_overrides.yaml` — a human-curated
reference file, not derived data. It is the **only** place override translations are
defined; translation logic must never be hard-coded into application or agent code.
Any code that needs an English category label should call into this module rather than
reimplementing the lookup.

Current overrides (both gaps found in the real dataset):

| Portuguese | English override | Rationale |
|---|---|---|
| `pc_gamer` | `gaming_pc` | Direct rendering of the existing English loanword "PC gamer," in the same snake_case convention as the official table. |
| `portateis_cozinha_e_preparadores_de_alimentos` | `kitchen_portables_and_food_preparators` | Literal translation ("portables, kitchen, and food preparators"), same snake_case convention. |

Adding a new override requires: (1) adding the entry to the YAML file's `overrides`
map, and (2) adding a rationale note in the file's trailing comment block for
auditability. No code changes are needed — the pipeline picks up new entries
automatically on the next run.

## Coverage reporting (requirement #6)

`profile_category_enrichment` reports:

- `total_products` — total rows in `products`.
- `products_with_category` — products with a non-null `product_category_name`.
- `products_without_category` — products with a null `product_category_name`.
- `translated_via_official` — products whose category matched the official translation table.
- `translated_via_override` — products whose category matched a curated override.
- `untranslated_categories` — products with a non-null category that resolved to
  neither the official table nor an override (should be 0; a non-zero value means a
  new gap has appeared and needs an override added).
- `translation_coverage_rate` — share of **categorized** (non-null) products that were
  genuinely translated (official + override) rather than falling back to
  `Uncategorized` or remaining unresolved. Products with a null category are excluded
  from this rate's denominator since "coverage" is a translation-quality metric, not a
  completeness metric — completeness is instead guaranteed unconditionally by
  `validate_full_coverage` (every row gets a label, translated or not).

## Observed enrichment statistics (this dataset, profiled 2026-08-26)

| Metric | Value |
|---|---|
| Total products | 32,951 |
| Products with a category | 32,341 (98.15%) |
| Products without a category | 610 (1.85%) |
| Translated via official table | 32,328 |
| Translated via curated override | 13 (all from the 2 override categories) |
| Untranslated / unresolved | 0 |
| Translation coverage rate (of categorized products) | 100.00% |
| Full-dataset validation | Passed — every row has a valid source and a non-null English label |

## Explicitly out of scope for this module

- Attaching the enrichment output back onto `products` as persisted columns, or
  joining it into any other table.
- Any KPI, agent, LLM, or frontend logic that consumes the translated category.
- Deciding whether `Uncategorized` products should be excluded from category-based
  KPIs later — that is a downstream decision, not made here.
- Any change to the raw CSVs — both `olist_products_dataset.csv` and
  `product_category_name_translation.csv` are read-only input and are never modified.
  Verified by unit tests (`test_enrich_does_not_mutate_raw_input`) and by checksum
  comparison of both raw files before/after running the pipeline against the real
  dataset.
