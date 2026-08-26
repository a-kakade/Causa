"""
semantic_registry.py — STEP 3A: the KPI semantic layer's Python entry point.

Loads config/kpis.yaml, validates every contract against
schemas/kpi_contract.schema.json, and exposes read-only accessors. This module
performs NO KPI calculation whatsoever -- there is no aggregation, no pandas
groupby, no reading of data/processed/*.parquet anywhere in this file. Its only
job is to load, validate, and answer questions ABOUT the contracts (e.g. "what
table does Revenue come from", "does AOV support a seller dimension") so that a
future engine (Step 3B+) or an LLM layer has one governed place to ask, instead of
inventing KPI definitions.

Usage:
    from kpi.semantic_registry import SemanticRegistry
    registry = SemanticRegistry.load()
    registry.validate()                       # raises on any contract violation
    kpi = registry.get("revenue")
    kpi["formula"]                             # "SUM(order_items.price) ..."
    registry.list_kpi_ids()
    registry.get_dimension(kpi_id="orders", dimension_name="seller")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "config" / "kpis.yaml"
SCHEMA_PATH = REPO_ROOT / "schemas" / "kpi_contract.schema.json"

VALID_CANONICAL_TABLES = {
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
}


class SemanticRegistryError(Exception):
    """Raised when a KPI contract fails validation. Never raised for a calculation
    error -- this module doesn't calculate anything."""


class SemanticRegistry:
    def __init__(self, kpis: list[dict[str, Any]], schema: dict[str, Any], raw_config: dict[str, Any]):
        self._kpis: dict[str, dict[str, Any]] = {k["kpi_id"]: k for k in kpis}
        self._schema = schema
        self._raw_config = raw_config

    # -- loading -----------------------------------------------------------

    @classmethod
    def load(cls, config_path: Path = CONFIG_PATH, schema_path: Path = SCHEMA_PATH) -> "SemanticRegistry":
        with open(schema_path) as f:
            schema = json.load(f)
        with open(config_path) as f:
            raw_config = yaml.safe_load(f)
        kpis = raw_config.get("kpis", [])
        return cls(kpis=kpis, schema=schema, raw_config=raw_config)

    # -- validation ----------------------------------------------------------

    def validate(self) -> None:
        """Validates every contract against the JSON Schema, then runs the
        cross-contract governance rules this task requires (Revenue must use
        order_items.price, Repeat Purchase must use customer_unique_id, Delivery
        must exclude invalid timestamps, Review must follow REVIEW_GOVERNANCE.md)
        that a generic JSON Schema cannot express. Raises SemanticRegistryError
        with every violation found (not just the first), so a broken contract is
        never silently accepted."""
        errors: list[str] = []

        if not self._kpis:
            raise SemanticRegistryError("No KPIs loaded from config/kpis.yaml -- registry is empty.")

        seen_ids = set()
        for kpi in self._kpis.values():
            kpi_id = kpi.get("kpi_id", "<missing kpi_id>")
            if kpi_id in seen_ids:
                errors.append(f"Duplicate kpi_id: {kpi_id!r}")
            seen_ids.add(kpi_id)

            try:
                jsonschema.validate(instance=kpi, schema=self._schema)
            except jsonschema.ValidationError as e:
                errors.append(f"[{kpi_id}] schema violation: {e.message} (path: {list(e.absolute_path)})")
                continue  # skip semantic checks on a structurally invalid contract

            errors.extend(self._semantic_checks(kpi))

        # aggregation_variants integrity (schema can't express "exactly one is_default")
        for kpi in self._kpis.values():
            variants = kpi.get("aggregation_variants")
            if variants:
                defaults = [v for v in variants if v.get("is_default")]
                if len(defaults) != 1:
                    errors.append(
                        f"[{kpi['kpi_id']}] aggregation_variants must have exactly one is_default=true, "
                        f"found {len(defaults)}"
                    )

        if errors:
            raise SemanticRegistryError(
                f"{len(errors)} KPI contract violation(s) found:\n  - " + "\n  - ".join(errors)
            )

    def _semantic_checks(self, kpi: dict[str, Any]) -> list[str]:
        errs = []
        kpi_id = kpi["kpi_id"]

        # source tables must be real canonical tables
        for t in kpi["source_tables"]:
            if t not in VALID_CANONICAL_TABLES:
                errs.append(f"[{kpi_id}] source_tables references unknown canonical table {t!r}")

        # every dimension's source_table must also be a real canonical table
        for dim in kpi["dimensions"]:
            if dim["source_table"] not in VALID_CANONICAL_TABLES:
                errs.append(f"[{kpi_id}] dimension {dim['name']!r} references unknown table {dim['source_table']!r}")
            if not dim["supported"] and "unsupported_reason" not in dim:
                errs.append(f"[{kpi_id}] dimension {dim['name']!r} is unsupported but has no unsupported_reason")

        # ratio KPIs must declare a ratio block
        if kpi["aggregation"] in ("RATIO", "DERIVED_RATIO") and "ratio" not in kpi:
            errs.append(f"[{kpi_id}] aggregation={kpi['aggregation']} requires a 'ratio' block")

        # task-specific governance rules --------------------------------------
        if kpi_id == "revenue":
            cols = " ".join(kpi["source_columns"])
            if "order_items.price" not in cols and "item_price_total" not in cols:
                errs.append(f"[{kpi_id}] must explicitly source from order_items.price / item_price_total")
            if any("payment_value" in c for c in kpi["source_columns"]):
                errs.append(f"[{kpi_id}] must NOT source revenue from payment_value")

        if kpi_id == "repeat_purchase_rate":
            cols = " ".join(kpi["source_columns"])
            if "customer_unique_id" not in cols:
                errs.append(f"[{kpi_id}] must explicitly use customer_unique_id")
            if kpi["base_grain"].split()[0].lower() != "customer_unique_id":
                errs.append(f"[{kpi_id}] base_grain must be customer_unique_id-based, got {kpi['base_grain']!r}")

        if kpi_id in ("avg_delivery_days", "on_time_delivery_rate"):
            has_dq_filter = any(
                f["source_column"] == "fact_orders.delivery_data_quality_flag" and f["applied_by_default"]
                for f in kpi["filters"]
            )
            if not has_dq_filter:
                errs.append(f"[{kpi_id}] must apply a mandatory default filter on delivery_data_quality_flag")

        if kpi_id == "avg_review_score":
            if "review_governance_reference" not in kpi:
                errs.append(f"[{kpi_id}] must cite review_governance_reference (REVIEW_GOVERNANCE.md)")
            variants = kpi.get("aggregation_variants", [])
            variant_ids = {v["variant_id"] for v in variants}
            if "order_level_representative" not in variant_ids or "review_level_average" not in variant_ids:
                errs.append(f"[{kpi_id}] must declare both an order-level and a review-level aggregation variant")

        for driver in kpi.get("drivers", []):
            if driver.get("is_causal_claim") is not False:
                errs.append(f"[{kpi_id}] driver {driver.get('driver_name')!r} must have is_causal_claim=false")

        if kpi.get("materiality", {}).get("implemented") is not False:
            errs.append(f"[{kpi_id}] materiality.implemented must be false -- no anomaly engine exists yet")

        return errs

    # -- read-only accessors ---------------------------------------------------

    def list_kpi_ids(self) -> list[str]:
        return list(self._kpis.keys())

    def get(self, kpi_id: str) -> dict[str, Any]:
        if kpi_id not in self._kpis:
            raise KeyError(f"Unknown kpi_id {kpi_id!r}. Known: {self.list_kpi_ids()}")
        return self._kpis[kpi_id]

    def get_dimension(self, kpi_id: str, dimension_name: str) -> dict[str, Any] | None:
        for dim in self.get(kpi_id)["dimensions"]:
            if dim["name"] == dimension_name:
                return dim
        return None

    def supports_dimension(self, kpi_id: str, dimension_name: str) -> bool:
        dim = self.get_dimension(kpi_id, dimension_name)
        return bool(dim and dim["supported"])

    def get_lineage_chain(self, kpi_id: str) -> list[dict[str, str]]:
        return self.get(kpi_id)["lineage"]["chain"]

    def get_security_classification(self, kpi_id: str) -> str:
        return self.get(kpi_id)["security"]["kpi_classification"]

    def kpis_by_category(self, category: str) -> list[str]:
        return [k for k, v in self._kpis.items() if v["category"] == category]

    def to_dict(self) -> dict[str, Any]:
        """Full registry as a plain dict, for reporting/serialization only."""
        return {"version": self._raw_config.get("version"), "kpis": list(self._kpis.values())}


def main():
    """CLI entry point: load, validate, and print a one-line-per-KPI summary.
    Does not compute anything."""
    registry = SemanticRegistry.load()
    registry.validate()
    print(f"Loaded and validated {len(registry.list_kpi_ids())} KPI contracts:\n")
    for kpi_id in registry.list_kpi_ids():
        kpi = registry.get(kpi_id)
        n_dims_supported = sum(1 for d in kpi["dimensions"] if d["supported"])
        print(f"  {kpi_id:24} [{kpi['category']:10}] grain={kpi['base_grain'].split(' ')[0]:20} "
              f"dims_supported={n_dims_supported}/{len(kpi['dimensions'])} "
              f"security={kpi['security']['kpi_classification']}")
    print("\nAll contracts valid. No KPI values were computed.")


if __name__ == "__main__":
    main()
