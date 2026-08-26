"""
step3a_validate_semantic_layer.py — loads + validates config/kpis.yaml against
schemas/kpi_contract.schema.json, runs tests/test_kpi_contracts.py, and writes
reports/kpi_semantic_validation.json.

This script computes NO KPI value. It only validates the governance layer.

Usage:
    python scripts/step3a_validate_semantic_layer.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kpi.semantic_registry import SemanticRegistry, SemanticRegistryError  # noqa: E402


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_kpi_contracts.py", "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {
        "returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
        "failed_tests": failed, "all_passed": proc.returncode == 0,
    }


def summarize_kpi(kpi: dict) -> dict:
    return {
        "kpi_id": kpi["kpi_id"],
        "name": kpi["name"],
        "category": kpi["category"],
        "base_grain": kpi["base_grain"],
        "aggregation": kpi["aggregation"],
        "source_tables": kpi["source_tables"],
        "dimensions_declared": len(kpi["dimensions"]),
        "dimensions_supported": sum(1 for d in kpi["dimensions"] if d["supported"]),
        "dimensions_unsupported": [d["name"] for d in kpi["dimensions"] if not d["supported"]],
        "drivers": [d["driver_name"] for d in kpi["drivers"]],
        "security_classification": kpi["security"]["kpi_classification"],
        "has_aggregation_variants": "aggregation_variants" in kpi,
        "unresolved_semantic_decisions": kpi.get("unresolved_semantic_decisions", []),
    }


def main():
    registry = SemanticRegistry.load()

    validation_error = None
    try:
        registry.validate()
        contracts_valid = True
    except SemanticRegistryError as e:
        contracts_valid = False
        validation_error = str(e)

    test_results = run_tests()

    result = {
        "step": "3A",
        "scope": "KPI semantic layer definitions only -- no KPI value calculation, "
                 "no anomaly detection, no PVM, no RAG/LLM, no agents.",
        "contracts_valid": contracts_valid,
        "validation_error": validation_error,
        "n_kpis": len(registry.list_kpi_ids()),
        "kpi_ids": registry.list_kpi_ids(),
        "primary_kpis": registry.kpis_by_category("primary"),
        "supporting_kpis": registry.kpis_by_category("supporting"),
        "kpi_summaries": [summarize_kpi(registry.get(k)) for k in registry.list_kpi_ids()],
        "test_results": test_results,
        "governing_documents": [
            "DATA_FOUNDATION_REPORT.md", "STEP2_VALIDATION.md",
            "docs/CANONICAL_DATA_MODEL.md", "docs/DATA_LINEAGE_V2.md",
            "docs/KPI_SEMANTICS_PREVIEW.md", "docs/REVIEW_GOVERNANCE.md",
            "docs/ANALYTICAL_WINDOW.md",
        ],
        "unresolved_semantic_decisions_by_kpi": {
            k: registry.get(k)["unresolved_semantic_decisions"]
            for k in registry.list_kpi_ids()
            if registry.get(k).get("unresolved_semantic_decisions")
        },
    }

    out_path = REPO_ROOT / "reports" / "kpi_semantic_validation.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"Contracts valid: {contracts_valid}")
    print(f"KPIs: {result['n_kpis']} ({len(result['primary_kpis'])} primary, {len(result['supporting_kpis'])} supporting)")
    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
