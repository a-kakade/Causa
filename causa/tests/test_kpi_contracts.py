"""Step 3A: KPI semantic contract validation tests.

These tests validate the GOVERNANCE of config/kpis.yaml -- structure, lineage,
grain declarations, and the task-specific rules for Revenue/Repeat
Purchase/Delivery/Review. They do NOT compute any KPI value and do NOT read
data/processed/*.parquet -- Step 3A produces definitions only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kpi.semantic_registry import SemanticRegistry, SemanticRegistryError  # noqa: E402

EXPECTED_KPI_IDS = {
    "revenue", "orders", "aov", "avg_delivery_days", "avg_review_score",
    "freight_revenue", "review_volume", "on_time_delivery_rate",
    "quantity_sold", "repeat_purchase_rate",
}
EXPECTED_PRIMARY = {"revenue", "orders", "aov", "avg_delivery_days", "avg_review_score"}
EXPECTED_SUPPORTING = {"freight_revenue", "review_volume", "on_time_delivery_rate",
                        "quantity_sold", "repeat_purchase_rate"}


@pytest.fixture(scope="session")
def registry():
    return SemanticRegistry.load()


def test_registry_loads_and_validates_cleanly(registry):
    """Schema + cross-contract governance validation must pass with zero errors."""
    registry.validate()  # raises SemanticRegistryError on any violation


def test_exactly_the_required_10_kpis_exist(registry):
    ids = set(registry.list_kpi_ids())
    assert ids == EXPECTED_KPI_IDS, (
        f"KPI set mismatch. Missing: {EXPECTED_KPI_IDS - ids}, Unexpected: {ids - EXPECTED_KPI_IDS}"
    )


def test_primary_vs_supporting_split_matches_brief(registry):
    assert set(registry.kpis_by_category("primary")) == EXPECTED_PRIMARY
    assert set(registry.kpis_by_category("supporting")) == EXPECTED_SUPPORTING


# --- Required check 1: every KPI has a definition -----------------------------

def test_every_kpi_has_a_definition(registry):
    for kpi_id in registry.list_kpi_ids():
        kpi = registry.get(kpi_id)
        assert kpi.get("business_definition"), f"{kpi_id} missing business_definition"
        assert kpi.get("formula"), f"{kpi_id} missing formula"
        assert kpi.get("business_purpose"), f"{kpi_id} missing business_purpose (every KPI needs a clear business purpose)"


# --- Required check 2: every KPI has source lineage ----------------------------

def test_every_kpi_has_source_lineage(registry):
    for kpi_id in registry.list_kpi_ids():
        chain = registry.get_lineage_chain(kpi_id)
        layers = [step["layer"] for step in chain]
        assert layers[0] == "kpi", f"{kpi_id} lineage chain must start at 'kpi'"
        assert "raw_table_column" in layers, f"{kpi_id} lineage chain must terminate at a raw_table_column"
        assert "canonical_table_field" in layers, f"{kpi_id} lineage chain must pass through a canonical_table_field"
        assert registry.get(kpi_id)["lineage"]["traceable_to_raw"] is True


# --- Required check 3: every KPI has a valid grain -----------------------------

def test_every_kpi_has_a_valid_grain(registry):
    valid_grain_prefixes = {"order", "review", "customer_unique_id"}
    for kpi_id in registry.list_kpi_ids():
        grain = registry.get(kpi_id)["base_grain"]
        assert grain and isinstance(grain, str) and len(grain) > 0, f"{kpi_id} missing base_grain"
        first_word = grain.split(" ")[0].split("(")[0]
        assert any(first_word.startswith(p) for p in valid_grain_prefixes), (
            f"{kpi_id} base_grain {grain!r} does not start with a recognized grain "
            f"({valid_grain_prefixes})"
        )


def test_orders_kpi_grain_matches_canonical_fact_orders(registry):
    """Regression guard: Orders must be declared at order grain, sourced from
    fact_orders -- not from an aggregate table that could silently change the
    population (e.g. agg_order_items, which excludes 775 orders)."""
    orders = registry.get("orders")
    assert orders["source_tables"] == ["fact_orders"]
    assert "fact_orders.order_id" in orders["source_columns"]


# --- Required check 4: every KPI has a time column -----------------------------

def test_every_kpi_has_a_time_column(registry):
    for kpi_id in registry.list_kpi_ids():
        time_col = registry.get(kpi_id)["time_column"]
        assert time_col is not None and len(time_col) > 0, f"{kpi_id} has no time_column declared"


def test_every_kpi_has_a_valid_time_window_referencing_analytical_window_doc(registry):
    for kpi_id in registry.list_kpi_ids():
        window = registry.get(kpi_id)["valid_time_window"]
        assert window["default_start"] == "2017-01"
        assert window["default_end"] == "2018-08"
        assert window["window_is_a_filter_not_a_deletion"] is True
        assert "ANALYTICAL_WINDOW" in window["source_doc"]


# --- Required check 5: every KPI has null behavior -----------------------------

def test_every_kpi_has_null_behavior(registry):
    for kpi_id in registry.list_kpi_ids():
        nb = registry.get(kpi_id)["null_behavior"]
        assert nb and len(nb) > 10, f"{kpi_id} null_behavior is missing or trivially short"


# --- Required check 6: every KPI has data-quality rules ------------------------

def test_every_kpi_has_data_quality_rules(registry):
    required_keys = {
        "required_fields", "minimum_observations", "missing_data_treatment",
        "invalid_data_treatment", "coverage_threshold_pct", "confidence_implications",
    }
    for kpi_id in registry.list_kpi_ids():
        dq = registry.get(kpi_id)["data_quality_requirements"]
        missing = required_keys - set(dq.keys())
        assert not missing, f"{kpi_id} data_quality_requirements missing keys: {missing}"
        assert len(dq["required_fields"]) >= 1, f"{kpi_id} declares zero required_fields"


# --- Required check 7: every KPI has declared dimensions -----------------------

def test_every_kpi_has_declared_dimensions(registry):
    for kpi_id in registry.list_kpi_ids():
        dims = registry.get(kpi_id)["dimensions"]
        assert len(dims) >= 1, f"{kpi_id} has zero declared dimensions"
        for dim in dims:
            if not dim["supported"]:
                assert dim.get("unsupported_reason"), (
                    f"{kpi_id} dimension {dim['name']!r} is marked unsupported without a reason -- "
                    f"'Do not claim a dimension is supported if the underlying grain makes the "
                    f"calculation invalid,' but an unsupported claim needs a reason too."
                )


def test_order_grain_kpis_do_not_overclaim_item_grain_dimensions(registry):
    """Regression guard for the core grain-safety rule: order-grain KPIs
    (COUNT DISTINCT order / MEAN over orders) must NOT claim seller/product/
    seller_state support, because an order can span multiple sellers/products
    (verified: ~9.86%% of orders are multi-item, per Step 1)."""
    order_grain_kpis = ["orders", "aov", "avg_delivery_days", "avg_review_score", "on_time_delivery_rate"]
    for kpi_id in order_grain_kpis:
        for dim_name in ("seller", "product", "product_category", "seller_state"):
            dim = registry.get_dimension(kpi_id, dim_name)
            if dim is not None:
                assert dim["supported"] is False, (
                    f"{kpi_id} incorrectly claims support for item-grain dimension {dim_name!r} -- "
                    f"this KPI is order-grain and multi-item orders make this invalid."
                )


def test_item_grain_kpis_correctly_support_item_dimensions(registry):
    """The inverse guard: item-grain KPIs (Revenue, Freight Revenue, Quantity
    Sold) CAN safely support seller/product dimensions -- summing/counting at
    item grain does not have the order-grain fan-out problem."""
    item_grain_kpis = ["revenue", "freight_revenue", "quantity_sold"]
    for kpi_id in item_grain_kpis:
        for dim_name in ("seller", "product", "product_category", "seller_state"):
            dim = registry.get_dimension(kpi_id, dim_name)
            assert dim is not None and dim["supported"] is True, (
                f"{kpi_id} should support item-grain dimension {dim_name!r} (it is safe at this KPI's grain)"
            )


# --- Required check 8: every KPI has declared drivers --------------------------

def test_every_kpi_has_declared_drivers(registry):
    for kpi_id in registry.list_kpi_ids():
        drivers = registry.get(kpi_id)["drivers"]
        assert len(drivers) >= 1, f"{kpi_id} has zero declared drivers"
        for d in drivers:
            assert d["is_causal_claim"] is False, (
                f"{kpi_id} driver {d['driver_name']!r} must explicitly disclaim causality -- drivers here "
                f"are analytical hypotheses, not causal claims (per this task's explicit instruction)."
            )
            assert d["relationship_type"] in (
                "deterministic_decomposition", "statistical_association", "qualitative_evidence"
            )


def test_revenue_driver_graph_matches_brief_exactly(registry):
    """The brief specifies Revenue's driver graph exactly: Volume, Price, Mix."""
    driver_names = {d["driver_name"] for d in registry.get("revenue")["drivers"]}
    assert driver_names == {"volume", "price", "mix"}, f"Revenue drivers {driver_names} != {{volume, price, mix}}"


def test_delivery_driver_graph_matches_brief_exactly(registry):
    """The brief specifies: carrier_days, fulfillment delay, estimated-vs-actual delay."""
    driver_names = {d["driver_name"] for d in registry.get("avg_delivery_days")["drivers"]}
    assert driver_names == {"carrier_days", "fulfillment_delay", "estimated_vs_actual_delay"}


def test_review_score_driver_graph_matches_brief_exactly(registry):
    """The brief specifies: score distribution, low-score share, review-text evidence."""
    driver_names = {d["driver_name"] for d in registry.get("avg_review_score")["drivers"]}
    assert driver_names == {"score_distribution", "low_score_share", "review_text_evidence"}


# --- Required check 9: Revenue explicitly uses order_items.price --------------

def test_revenue_explicitly_uses_order_items_price_not_payment_value(registry):
    rev = registry.get("revenue")
    cols = " ".join(rev["source_columns"])
    assert "price" in cols
    assert "payment_value" not in cols, "Revenue must NEVER source from payment_value"
    assert "order_items" in " ".join(rev["source_tables"]) or "agg_order_items" in rev["source_tables"]
    assert "order_payments" not in rev["source_tables"] and "fact_payments" not in rev["source_tables"], (
        "Revenue's source_tables must not include the payments fact -- per this task's explicit "
        "instruction not to join payment/review facts before calculating revenue."
    )
    assert "pre-aggregated" in rev["base_grain"] or "aggregated" in rev["business_definition"].lower(), (
        "Revenue's contract must document that order_items is aggregated to order grain BEFORE any join."
    )


def test_aov_numerator_is_revenue_not_average_item_price(registry):
    """'Do not average item prices' -- AOV must be Revenue/Orders, not MEAN(price)."""
    aov = registry.get("aov")
    assert aov["aggregation"] in ("RATIO", "DERIVED_RATIO")
    assert "ratio" in aov
    assert "revenue" in aov["ratio"]["numerator"].lower() or "item_price_total" in aov["ratio"]["numerator"]
    assert "zero_denominator_behavior" in aov["ratio"] and aov["ratio"]["zero_denominator_behavior"]


# --- Required check 10: Repeat Purchase explicitly uses customer_unique_id ----

def test_repeat_purchase_rate_uses_customer_unique_id_not_customer_id(registry):
    rp = registry.get("repeat_purchase_rate")
    assert "customer_unique_id" in rp["base_grain"]
    cols = " ".join(rp["source_columns"])
    assert "customer_unique_id" in cols, "Repeat Purchase Rate must source from customer_unique_id"
    definition = rp["business_definition"].lower()
    assert "customer_unique_id" in definition and "never" in definition, (
        "Repeat Purchase Rate's definition must explicitly warn against using customer_id"
    )


# --- Required check 11: Delivery explicitly excludes invalid/missing timestamps -

def test_avg_delivery_days_excludes_invalid_sequence_and_missing_dates(registry):
    kpi = registry.get("avg_delivery_days")
    dq_filter = next(f for f in kpi["filters"] if f["source_column"] == "fact_orders.delivery_data_quality_flag")
    assert dq_filter["applied_by_default"] is True
    assert dq_filter["default_value"] == "VALID"
    invalid_treatment = kpi["data_quality_requirements"]["invalid_data_treatment"].upper()
    assert "INVALID_SEQUENCE" in invalid_treatment
    assert "EXCLUDED" in invalid_treatment
    assert "166" in kpi["data_quality_requirements"]["invalid_data_treatment"], (
        "The exact INVALID_SEQUENCE exclusion count (166, per Step 2) must be exposed in the contract."
    )
    assert "0" in kpi["null_behavior"] and "NULL" in kpi["null_behavior"].upper(), (
        "null_behavior must confirm missing delivery dates are NULL, not 0"
    )


def test_on_time_delivery_rate_shares_the_same_valid_population_as_avg_delivery_days(registry):
    kpi = registry.get("on_time_delivery_rate")
    dq_filter = next(f for f in kpi["filters"] if f["source_column"] == "fact_orders.delivery_data_quality_flag")
    assert dq_filter["applied_by_default"] is True
    assert dq_filter["default_value"] == "VALID"


# --- Required check 12: Review KPI follows REVIEW_GOVERNANCE.md ---------------

def test_avg_review_score_follows_review_governance(registry):
    kpi = registry.get("avg_review_score")
    assert "review_governance_reference" in kpi
    assert "REVIEW_GOVERNANCE" in kpi["review_governance_reference"]

    variants = kpi["aggregation_variants"]
    variant_ids = {v["variant_id"] for v in variants}
    assert "order_level_representative" in variant_ids, "Must declare the order-level representative score"
    assert "review_level_average" in variant_ids, "Must declare the distinct review-level average score"

    default_variant = next(v for v in variants if v["is_default"])
    assert default_variant["variant_id"] == "order_level_representative"
    assert "latest_review_score" in default_variant["source"], (
        "Default variant must use latest_review_score -- the strategy ratified in REVIEW_GOVERNANCE.md"
    )
    assert sum(v["is_default"] for v in variants) == 1


def test_avg_review_score_does_not_silently_choose_highest_score(registry):
    """REVIEW_GOVERNANCE.md quantitatively rejected 'highest_review_score' (bias
    +0.3763, cherry-picking) -- this contract must not use it anywhere."""
    kpi = registry.get("avg_review_score")
    formula_and_variants = kpi["formula"] + " " + " ".join(v["formula"] for v in kpi["aggregation_variants"])
    assert "max" not in formula_and_variants.lower(), (
        "avg_review_score must not silently use MAX(review_score) (the rejected 'highest score' strategy)"
    )


def test_review_volume_also_references_review_governance(registry):
    kpi = registry.get("review_volume")
    assert "review_governance_reference" in kpi


# --- Materiality contract is configuration, not implementation -----------------

def test_materiality_is_declared_but_not_implemented_for_every_kpi(registry):
    required_keys = {
        "absolute_threshold", "relative_threshold", "statistical_threshold",
        "minimum_observations", "minimum_business_impact", "persistence_periods",
        "implemented", "note",
    }
    for kpi_id in registry.list_kpi_ids():
        mat = registry.get(kpi_id)["materiality"]
        assert required_keys <= set(mat.keys()), f"{kpi_id} materiality missing keys: {required_keys - set(mat.keys())}"
        assert mat["implemented"] is False, f"{kpi_id} materiality.implemented must be False -- Step 3A builds no anomaly engine"


# --- Security classification ---------------------------------------------------

def test_every_kpi_and_dimension_has_a_security_classification(registry):
    valid = {"PUBLIC_ANALYTICAL", "INTERNAL", "RESTRICTED"}
    for kpi_id in registry.list_kpi_ids():
        kpi = registry.get(kpi_id)
        assert kpi["security"]["kpi_classification"] in valid
        for dim in kpi["dimensions"]:
            assert dim["security_classification"] in valid, f"{kpi_id}.{dim['name']} missing/invalid security_classification"


def test_customer_and_seller_identifier_dimensions_are_not_public(registry):
    """No dimension carrying a customer or seller identifier should be classified
    PUBLIC_ANALYTICAL -- seller_id is INTERNAL (business-sensitive), and no KPI in
    this registry exposes a raw customer identifier as a dimension at all."""
    for kpi_id in registry.list_kpi_ids():
        seller_dim = registry.get_dimension(kpi_id, "seller")
        if seller_dim is not None:
            assert seller_dim["security_classification"] == "INTERNAL"
        for dim in registry.get(kpi_id)["dimensions"]:
            assert "customer_id" not in dim["source_column"] and "customer_unique_id" not in dim["source_column"], (
                f"{kpi_id} exposes a raw customer identifier ({dim['source_column']}) as a queryable "
                f"dimension -- must not be surfaced to a future LLM layer per this task's security rule."
            )


# --- Structural / schema-level sanity ------------------------------------------

def test_registry_rejects_a_broken_contract():
    """Regression guard on the validator itself: prove it actually catches
    violations rather than passing everything."""
    registry = SemanticRegistry.load()
    broken_kpi = dict(registry.get("revenue"))
    broken_kpi["source_columns"] = ["order_payments.payment_value"]  # inject the forbidden source
    broken_kpi = {**broken_kpi}
    registry._kpis["revenue"] = broken_kpi
    with pytest.raises(SemanticRegistryError):
        registry.validate()
