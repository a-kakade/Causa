"""
test_product_categories.py

Tests for data_pipeline/preprocessing/product_categories.py. Uses small synthetic
DataFrames/dicts only — does not require the real Olist dataset to be present, and
never touches data/raw/olist/.

Usage:
    python -m pytest tests/test_product_categories.py -v
    # or, without pytest:
    python tests/test_product_categories.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

# Allow running this file directly (`python tests/test_product_categories.py`) without
# the package being installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_pipeline.preprocessing.product_categories import (
    OUTPUT_COLUMNS,
    PRODUCTS_CATEGORY_COL,
    SOURCE_NULL_CATEGORY,
    SOURCE_OFFICIAL,
    SOURCE_OVERRIDE,
    TRANSLATION_EN_COL,
    TRANSLATION_PT_COL,
    UNCATEGORIZED_LABEL,
    build_translation_lookup,
    enrich_categories,
    profile_category_enrichment,
    resolve_category,
    validate_full_coverage,
)


def make_products(categories: list) -> pd.DataFrame:
    return pd.DataFrame({PRODUCTS_CATEGORY_COL: categories, "product_id": [f"p{i}" for i in range(len(categories))]})


CATEGORY_TRANSLATION = pd.DataFrame(
    {
        TRANSLATION_PT_COL: ["beleza_saude", "automotivo", "bebes"],
        TRANSLATION_EN_COL: ["health_beauty", "auto", "baby"],
    }
)

OVERRIDES = {
    "pc_gamer": "gaming_pc",
    "portateis_cozinha_e_preparadores_de_alimentos": "kitchen_portables_and_food_preparators",
}


# ---- resolve_category (single-value precedence logic) --------------------------

def test_resolve_official_translation_used_when_available():
    lookup = build_translation_lookup(CATEGORY_TRANSLATION)
    label, source = resolve_category("beleza_saude", lookup, OVERRIDES)
    assert label == "health_beauty"
    assert source == SOURCE_OFFICIAL


def test_resolve_override_used_when_missing_from_official_table():
    lookup = build_translation_lookup(CATEGORY_TRANSLATION)
    label, source = resolve_category("pc_gamer", lookup, OVERRIDES)
    assert label == "gaming_pc"
    assert source == SOURCE_OVERRIDE


def test_resolve_second_override_used_when_missing_from_official_table():
    lookup = build_translation_lookup(CATEGORY_TRANSLATION)
    label, source = resolve_category(
        "portateis_cozinha_e_preparadores_de_alimentos", lookup, OVERRIDES
    )
    assert label == "kitchen_portables_and_food_preparators"
    assert source == SOURCE_OVERRIDE


def test_resolve_null_category_falls_back_to_uncategorized():
    lookup = build_translation_lookup(CATEGORY_TRANSLATION)
    label, source = resolve_category(np.nan, lookup, OVERRIDES)
    assert label == UNCATEGORIZED_LABEL
    assert source == SOURCE_NULL_CATEGORY


def test_resolve_official_takes_precedence_over_override_when_both_exist():
    # if a category exists in both the official table and overrides, official wins
    lookup = build_translation_lookup(CATEGORY_TRANSLATION)
    overrides_with_conflict = {**OVERRIDES, "beleza_saude": "SHOULD_NOT_BE_USED"}
    label, source = resolve_category("beleza_saude", lookup, overrides_with_conflict)
    assert label == "health_beauty"
    assert source == SOURCE_OFFICIAL


def test_resolve_unresolvable_category_returns_unresolved_marker():
    lookup = build_translation_lookup(CATEGORY_TRANSLATION)
    label, source = resolve_category("totally_unknown_category", lookup, OVERRIDES)
    assert label is None
    assert source == "unresolved"


# ---- enrich_categories (full pipeline, dataframe-level) -------------------------

def test_enrich_preserves_original_portuguese_value():
    products = make_products(["beleza_saude", "pc_gamer", None])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    assert enriched["product_category_name_pt"].tolist()[0] == "beleza_saude"
    assert enriched["product_category_name_pt"].tolist()[1] == "pc_gamer"
    assert pd.isna(enriched["product_category_name_pt"].tolist()[2])


def test_enrich_never_drops_a_row():
    products = make_products(["beleza_saude", "pc_gamer", None, "automotivo", "bebes"])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    assert len(enriched) == len(products)
    # same row order/index preserved so it can be reattached to `products`
    assert list(enriched.index) == list(products.index)


def test_enrich_output_schema_matches_spec():
    products = make_products(["beleza_saude"])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    assert list(enriched.columns) == OUTPUT_COLUMNS


def test_enrich_mixed_batch_resolves_each_row_independently():
    products = make_products(["beleza_saude", "pc_gamer", None, "portateis_cozinha_e_preparadores_de_alimentos"])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)

    assert enriched.loc[0, "product_category_name_en"] == "health_beauty"
    assert enriched.loc[0, "category_translation_source"] == SOURCE_OFFICIAL

    assert enriched.loc[1, "product_category_name_en"] == "gaming_pc"
    assert enriched.loc[1, "category_translation_source"] == SOURCE_OVERRIDE

    assert enriched.loc[2, "product_category_name_en"] == UNCATEGORIZED_LABEL
    assert enriched.loc[2, "category_translation_source"] == SOURCE_NULL_CATEGORY

    assert enriched.loc[3, "product_category_name_en"] == "kitchen_portables_and_food_preparators"
    assert enriched.loc[3, "category_translation_source"] == SOURCE_OVERRIDE


def test_enrich_does_not_mutate_raw_input():
    products = make_products(["beleza_saude", None])
    products_copy = products.copy(deep=True)
    translation_copy = CATEGORY_TRANSLATION.copy(deep=True)

    enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)

    pd.testing.assert_frame_equal(products, products_copy)
    pd.testing.assert_frame_equal(CATEGORY_TRANSLATION, translation_copy)


# ---- profile_category_enrichment (coverage reporting) -----------------------------

def test_profile_reports_expected_counts():
    products = make_products(
        ["beleza_saude", "beleza_saude", "pc_gamer", None, None, "automotivo"]
    )
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    profile = profile_category_enrichment(enriched)

    assert profile.total_products == 6
    assert profile.products_with_category == 4
    assert profile.products_without_category == 2
    assert profile.translated_via_official == 3  # 2x beleza_saude + automotivo
    assert profile.translated_via_override == 1  # pc_gamer
    assert profile.untranslated_categories == 0


def test_profile_coverage_rate_is_share_of_categorized_products_translated():
    products = make_products(["beleza_saude", "pc_gamer", None])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    profile = profile_category_enrichment(enriched)
    # 2 of 2 non-null-category products were translated (official + override) -> 1.0
    assert profile.translation_coverage_rate == 1.0


def test_profile_coverage_rate_reflects_unresolved_categories():
    products = make_products(["beleza_saude", "totally_unknown_category"])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    profile = profile_category_enrichment(enriched)
    assert profile.untranslated_categories == 1
    assert profile.translation_coverage_rate == 0.5


def test_profile_all_null_categories_gives_zero_products_with_category():
    products = make_products([None, None])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    profile = profile_category_enrichment(enriched)
    assert profile.products_with_category == 0
    assert profile.products_without_category == 2
    assert profile.translation_coverage_rate == 0.0


# ---- validate_full_coverage (requirement #7) ---------------------------------------

def test_validate_passes_when_every_category_resolves():
    products = make_products(["beleza_saude", "pc_gamer", None, "bebes"])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    result = validate_full_coverage(enriched)
    assert result["passed"] is True
    assert result["every_row_has_valid_source"] is True
    assert result["every_row_has_english_label"] is True


def test_validate_raises_when_a_category_is_unresolved():
    products = make_products(["beleza_saude", "totally_unknown_category"])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    try:
        validate_full_coverage(enriched)
        raised = False
    except AssertionError:
        raised = True
    assert raised, "expected validate_full_coverage to raise when a category is unresolved"


def test_validate_raises_when_english_label_is_missing():
    products = make_products(["beleza_saude"])
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    broken = enriched.copy()
    broken.loc[0, "product_category_name_en"] = None
    try:
        validate_full_coverage(broken)
        raised = False
    except AssertionError:
        raised = True
    assert raised, "expected validate_full_coverage to raise on a null English label"


# ---- full-dataset-shaped scenario: exactly the real findings ----------------------

def test_end_to_end_matches_known_real_dataset_findings_shape():
    """Simulates the real-world shape (minus the exact 32,951-row scale): 610 nulls
    proportionally represented, plus the two known missing categories, resolve with
    complete coverage.
    """
    products = make_products(
        ["beleza_saude"] * 5
        + ["pc_gamer"] * 2
        + ["portateis_cozinha_e_preparadores_de_alimentos"] * 2
        + [None] * 3
    )
    enriched = enrich_categories(products, CATEGORY_TRANSLATION, OVERRIDES)
    validation = validate_full_coverage(enriched)
    profile = profile_category_enrichment(enriched)

    assert validation["passed"] is True
    assert profile.total_products == 12
    assert profile.products_without_category == 3
    assert profile.translated_via_official == 5
    assert profile.translated_via_override == 4
    assert profile.untranslated_categories == 0
    assert (enriched["product_category_name_en"] == UNCATEGORIZED_LABEL).sum() == 3


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
