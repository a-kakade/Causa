"""
product_categories.py

Builds a deterministic English-translation enrichment for
`products.product_category_name`. This module is preprocessing only — no agents, LLM
functionality, frontend, or KPI logic live here.

Why this exists
----------------
`products.product_category_name` is in Portuguese. The official Olist
`category_translation` table (`product_category_name_translation.csv`) supplies
English translations for 71 categories, but the real data has two gaps:

  - 610 products have a null `product_category_name`.
  - 2 non-null Portuguese categories used by products are absent from the official
    translation table: `pc_gamer` and `portateis_cozinha_e_preparadores_de_alimentos`.

Every product must still resolve to a category label — silently dropping products
with unresolved categories is explicitly disallowed. This module resolves every
non-null category through a strict, ordered precedence and falls back to an explicit
"Uncategorized" label for nulls, never leaving a product without labels.

Resolution precedence for `product_category_name_en` (see docs/PRODUCT_CATEGORY_POLICY.md):
  1. Official translation — `category_translation` (source: "official").
  2. Curated override — `data/reference/product_category_overrides.yaml`
     (source: "override").
  3. Null category — `Uncategorized` (source: "null_category").

If a non-null Portuguese category resolves through none of the three paths above, this
module raises rather than silently emitting an unresolved/blank label — see
`validate_full_coverage`.

Pipeline stages (see `build_product_category_enrichment` for the orchestrating entry
point):
  1. `load_products` / `load_category_translation` / `load_overrides` — read the raw
     CSVs and the curated override YAML. Read-only; the raw CSVs are never modified.
  2. `enrich_categories` — resolves `product_category_name_en` and
     `category_translation_source` for every product via the precedence above.
  3. `profile_category_enrichment` — coverage reporting (requirement #6).
  4. `validate_full_coverage` — confirms every non-null category resolved via an
     official translation, an override, or Uncategorized (requirement #7).

Output columns (one row per product, joined onto `products`):
  - `product_category_name_pt` — the original Portuguese category, preserved exactly
    as-is (including null, which is preserved as null, not overwritten).
  - `product_category_name_en` — the resolved English label, always populated.
  - `category_translation_source` — one of "official", "override", "null_category",
    recording exactly how the English label was resolved.

Translation logic (the override table and precedence rule) lives entirely in this
module and the YAML file it reads — never hard-code translations into
application/agent code; import and call this module's functions instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RAW_PRODUCTS_PATH = REPO_ROOT / "data" / "raw" / "olist" / "olist_products_dataset.csv"
RAW_CATEGORY_TRANSLATION_PATH = REPO_ROOT / "data" / "raw" / "olist" / "product_category_name_translation.csv"
OVERRIDES_PATH = REPO_ROOT / "data" / "reference" / "product_category_overrides.yaml"

PRODUCTS_CATEGORY_COL = "product_category_name"
TRANSLATION_PT_COL = "product_category_name"
TRANSLATION_EN_COL = "product_category_name_english"

UNCATEGORIZED_LABEL = "Uncategorized"

SOURCE_OFFICIAL = "official"
SOURCE_OVERRIDE = "override"
SOURCE_NULL_CATEGORY = "null_category"

OUTPUT_COLUMNS = [
    "product_category_name_pt",
    "product_category_name_en",
    "category_translation_source",
]


def load_products(path: Path = RAW_PRODUCTS_PATH) -> pd.DataFrame:
    """Read the raw products CSV, unmodified. Read-only: never writes to `path`."""
    return pd.read_csv(path)


def load_category_translation(path: Path = RAW_CATEGORY_TRANSLATION_PATH) -> pd.DataFrame:
    """Read the raw category translation CSV, unmodified. Read-only."""
    return pd.read_csv(path)


def load_overrides(path: Path = OVERRIDES_PATH) -> dict[str, str]:
    """Read the curated override mapping from YAML.

    Returns a plain {portuguese_category: english_label} dict. Missing file or an
    empty/missing `overrides` key both resolve to an empty mapping rather than an
    error, so the pipeline degrades gracefully if no overrides are needed yet.
    """
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return dict(data.get("overrides") or {})


def build_translation_lookup(category_translation: pd.DataFrame) -> dict[str, str]:
    """Build the {portuguese -> english} lookup from the official translation table."""
    return dict(
        zip(
            category_translation[TRANSLATION_PT_COL],
            category_translation[TRANSLATION_EN_COL],
        )
    )


def resolve_category(
    category_pt: object,
    official_lookup: dict[str, str],
    overrides: dict[str, str],
) -> tuple[str, str]:
    """Resolve a single Portuguese category value to (english_label, source).

    Precedence: official translation -> curated override -> Uncategorized (null only).
    """
    if pd.isna(category_pt):
        return UNCATEGORIZED_LABEL, SOURCE_NULL_CATEGORY

    if category_pt in official_lookup:
        return official_lookup[category_pt], SOURCE_OFFICIAL

    if category_pt in overrides:
        return overrides[category_pt], SOURCE_OVERRIDE

    # A non-null category that matches neither the official table nor an override is
    # an unresolved gap — surfaced explicitly rather than silently mapped to anything.
    return None, "unresolved"


def enrich_categories(
    products: pd.DataFrame,
    category_translation: pd.DataFrame,
    overrides: dict[str, str],
) -> pd.DataFrame:
    """Produce the enrichment output: one row per product, in the same row order as
    `products`, with the three output columns.

    Never drops a row: every product in the input appears exactly once in the output,
    regardless of whether its category is null, officially translated, overridden, or
    unresolved (requirement #5 — never silently drop products).
    """
    official_lookup = build_translation_lookup(category_translation)

    categories_pt = products[PRODUCTS_CATEGORY_COL]
    resolved = categories_pt.map(lambda c: resolve_category(c, official_lookup, overrides))

    enriched = pd.DataFrame(
        {
            "product_category_name_pt": categories_pt,
            "product_category_name_en": [r[0] for r in resolved],
            "category_translation_source": [r[1] for r in resolved],
        },
        index=products.index,
    )

    return enriched[OUTPUT_COLUMNS]


@dataclass
class CategoryEnrichmentProfile:
    """Coverage report (requirement #6)."""

    total_products: int
    products_with_category: int
    products_without_category: int
    translated_via_official: int
    translated_via_override: int
    untranslated_categories: int
    translation_coverage_rate: float

    def as_dict(self) -> dict:
        return {
            "total_products": self.total_products,
            "products_with_category": self.products_with_category,
            "products_without_category": self.products_without_category,
            "translated_via_official": self.translated_via_official,
            "translated_via_override": self.translated_via_override,
            "untranslated_categories": self.untranslated_categories,
            "translation_coverage_rate": self.translation_coverage_rate,
        }


def profile_category_enrichment(enriched: pd.DataFrame) -> CategoryEnrichmentProfile:
    """Report the requirement #6 statistics: total, with/without category, translated
    vs. untranslated, and coverage rate.

    "Translation coverage" here means the share of products with a non-null category
    that resolved through an official translation or a curated override (i.e.
    genuinely translated, as opposed to falling back to Uncategorized or being
    unresolved).
    """
    total_products = len(enriched)
    source_counts = enriched["category_translation_source"].value_counts()

    n_official = int(source_counts.get(SOURCE_OFFICIAL, 0))
    n_override = int(source_counts.get(SOURCE_OVERRIDE, 0))
    n_null = int(source_counts.get(SOURCE_NULL_CATEGORY, 0))
    n_unresolved = int(source_counts.get("unresolved", 0))

    products_with_category = total_products - n_null
    products_without_category = n_null
    translated = n_official + n_override
    untranslated = n_unresolved  # categories that are non-null but resolved to neither path

    coverage_rate = round(translated / products_with_category, 4) if products_with_category else 0.0

    return CategoryEnrichmentProfile(
        total_products=total_products,
        products_with_category=products_with_category,
        products_without_category=products_without_category,
        translated_via_official=n_official,
        translated_via_override=n_override,
        untranslated_categories=untranslated,
        translation_coverage_rate=coverage_rate,
    )


def validate_full_coverage(enriched: pd.DataFrame) -> dict:
    """Validate that every non-null category resolved to an English translation, an
    explicit override, or Uncategorized (requirement #7). Raises AssertionError if any
    row is "unresolved" or has a null English label — fails loudly rather than letting
    a silently-unresolved category pass through.
    """
    valid_sources = {SOURCE_OFFICIAL, SOURCE_OVERRIDE, SOURCE_NULL_CATEGORY}
    source_values = set(enriched["category_translation_source"].unique())
    unresolved_sources = source_values - valid_sources

    n_unresolved_rows = int((~enriched["category_translation_source"].isin(valid_sources)).sum())
    n_null_english = int(enriched["product_category_name_en"].isna().sum())
    n_rows = len(enriched)

    result = {
        "n_rows": n_rows,
        "unresolved_sources_found": sorted(unresolved_sources),
        "n_unresolved_rows": n_unresolved_rows,
        "n_null_english_labels": n_null_english,
        "every_row_has_valid_source": n_unresolved_rows == 0,
        "every_row_has_english_label": n_null_english == 0,
        "passed": n_unresolved_rows == 0 and n_null_english == 0,
    }

    assert n_unresolved_rows == 0, (
        f"{n_unresolved_rows} product(s) have a non-null category with no official "
        f"translation and no override: {unresolved_sources}. Add a curated override "
        f"in {OVERRIDES_PATH.name} before proceeding."
    )
    assert n_null_english == 0, "product_category_name_en contains nulls after enrichment"

    return result


@dataclass
class ProductCategoryEnrichmentResult:
    """Full output of the pipeline: the enrichment table plus every report needed to
    trust (or scrutinize) it."""

    enrichment: pd.DataFrame
    profile: CategoryEnrichmentProfile
    validation: dict


def build_product_category_enrichment(
    products_path: Path = RAW_PRODUCTS_PATH,
    category_translation_path: Path = RAW_CATEGORY_TRANSLATION_PATH,
    overrides_path: Path = OVERRIDES_PATH,
) -> ProductCategoryEnrichmentResult:
    """End-to-end pipeline: load raw data + overrides -> enrich -> profile -> validate.

    Does not modify any raw CSV.
    """
    products = load_products(products_path)
    category_translation = load_category_translation(category_translation_path)
    overrides = load_overrides(overrides_path)

    enriched = enrich_categories(products, category_translation, overrides)
    profile = profile_category_enrichment(enriched)
    validation = validate_full_coverage(enriched)

    return ProductCategoryEnrichmentResult(
        enrichment=enriched,
        profile=profile,
        validation=validation,
    )


def _print_summary(result: ProductCategoryEnrichmentResult) -> None:
    print("=== Product Category Enrichment: coverage profile ===")
    for k, v in result.profile.as_dict().items():
        print(f"  {k}: {v}")

    print("\n=== Product Category Enrichment: validation ===")
    for k, v in result.validation.items():
        print(f"  {k}: {v}")

    print("\n=== Product Category Enrichment: source breakdown ===")
    print(result.enrichment["category_translation_source"].value_counts().to_string())

    print("\n=== Product Category Enrichment: preview ===")
    print(result.enrichment.head(5).to_string(index=False))
    print(f"\ntotal enrichment rows: {len(result.enrichment):,}")


if __name__ == "__main__":
    result = build_product_category_enrichment()
    _print_summary(result)
