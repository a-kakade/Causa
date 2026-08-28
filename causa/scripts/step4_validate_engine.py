"""
step4_validate_engine.py — builds the real November 2017 Evidence Fabric
package (structured + unstructured evidence + graph), asserts it reproduces
the exact validated Step 3B/3C/3D numbers, runs the full Step 4 test suite,
and writes reports/step4_validation.json.

Every number in "required_value_checks" is computed live via the real
KPIEngine / anomaly.engine / drivers.engine and converted via
structured_adapter.py -- none are hardcoded into the evidence itself, only
used here as REQUIRED_* assertion targets, same discipline as
scripts/step3d_validate_engine.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lib.raw_loader import PROCESSED_DIR  # noqa: E402

from kpi.engine import KPIEngine  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from evidence.engine import build_november_2017_evidence_package  # noqa: E402
from evidence.models import EvidenceType  # noqa: E402

CANONICAL_TABLES = [
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
]

TEST_FILES = [
    "tests/test_evidence_schema.py", "tests/test_structured_adapter.py", "tests/test_review_pipeline.py",
    "tests/test_security.py", "tests/test_retrieval.py", "tests/test_reranking.py", "tests/test_graph.py",
    "tests/test_access_control.py", "tests/test_traceability.py",
]

REQUIRED_KPI_MOVEMENTS = {
    "revenue": 346051.94, "orders": None, "aov": None, "freight_revenue": None,
    "avg_delivery_days": None, "avg_review_score": None,
}
REQUIRED_KPI_PCT = {
    "revenue": 52.1, "orders": 62.9, "aov": -6.75, "freight_revenue": 60.69,
    "avg_delivery_days": 27.87, "avg_review_score": -5.16,
}
REQUIRED_PVM = {"volume": 417227.65, "price": 4674.63, "mix": -75850.34}


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TEST_FILES, "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
            "failed_tests": failed, "all_passed": proc.returncode == 0}


def _evidence_summary(evidence_list) -> list[dict]:
    return [ev.model_dump(mode="json") for ev in evidence_list]


def main():
    t_start = time.time()
    canonical = {t: pd.read_parquet(PROCESSED_DIR / f"{t}.parquet") for t in CANONICAL_TABLES}
    kpi_engine = KPIEngine()
    registry = SemanticRegistry.load()
    registry.validate()

    package = build_november_2017_evidence_package(canonical, kpi_engine, registry)
    build_seconds = round(time.time() - t_start, 2)

    # comparison_result_to_evidence carries no explicit kpi_id in `dimensions`
    # -- rebuild a kpi_id -> evidence map from `source.component` + `claim`
    # instead, since KPI_MOVEMENT evidence_id encodes kpi_id but isn't
    # itself the kpi_id string.
    movement_by_kpi_id = {}
    for ev in package.structured_evidence:
        if ev.evidence_type != EvidenceType.KPI_MOVEMENT:
            continue
        for kpi_id in REQUIRED_KPI_PCT:
            if ev.claim.startswith(kpi_id + " moved"):
                movement_by_kpi_id[kpi_id] = ev
                break

    kpi_checks = {}
    for kpi_id, required_pct in REQUIRED_KPI_PCT.items():
        ev = movement_by_kpi_id.get(kpi_id)
        computed_pct = ev.metadata["percentage_change"] if ev else None
        kpi_checks[kpi_id] = {
            "computed_pct_change": computed_pct, "required_pct_change": required_pct,
            "matches": computed_pct is not None and abs(computed_pct - required_pct) < 0.05,
        }
    revenue_change_ev = movement_by_kpi_id.get("revenue")
    revenue_absolute_check = {
        "computed": revenue_change_ev.value.value if revenue_change_ev else None,
        "required": REQUIRED_KPI_MOVEMENTS["revenue"],
        "matches": revenue_change_ev is not None and
        abs(revenue_change_ev.value.value - REQUIRED_KPI_MOVEMENTS["revenue"]) < 0.01,
    }

    by_driver = {ev.dimensions["driver"]: ev.value.value for ev in package.structured_evidence
                 if ev.evidence_type == EvidenceType.DRIVER_CONTRIBUTION}
    pvm_checks = {
        name: {"computed": by_driver.get(name), "required": REQUIRED_PVM[name],
               "matches": name in by_driver and abs(by_driver[name] - REQUIRED_PVM[name]) < 0.01}
        for name in REQUIRED_PVM
    }

    anomaly_signals = [ev for ev in package.structured_evidence if ev.evidence_type == EvidenceType.ANOMALY_SIGNAL]
    materiality_check = {
        "verdict": anomaly_signals[0].metadata["verdict"] if anomaly_signals else None,
        "expected_one_of": ["MATERIAL", "CRITICAL"],
        "matches": bool(anomaly_signals) and anomaly_signals[0].metadata["verdict"] in ("MATERIAL", "CRITICAL"),
    }

    all_matches = (
        all(c["matches"] for c in kpi_checks.values())
        and revenue_absolute_check["matches"]
        and all(c["matches"] for c in pvm_checks.values())
        and materiality_check["matches"]
    )

    review_language_counts: dict[str, int] = {}
    review_security_counts: dict[str, int] = {}
    review_pii_count = 0
    for ev in package.review_evidence:
        lang = ev.metadata.get("language", "UNKNOWN")
        review_language_counts[lang] = review_language_counts.get(lang, 0) + 1
        status = ev.security.security_status.value
        review_security_counts[status] = review_security_counts.get(status, 0) + 1
        if ev.security.pii_detected:
            review_pii_count += 1

    contradiction_summary = {
        category: {
            "previous_low_score_rate": check.previous_low_score_rate,
            "current_low_score_rate": check.current_low_score_rate,
            "n_previous": check.n_previous, "n_current": check.n_current,
            "z_score": check.z_score, "contradicts": check.contradicts,
        }
        for category, check in package.contradiction_checks.items()
    }

    report = {
        "step": "4",
        "scope": "Evidence Fabric: structured evidence adapters over Steps 3B/3C/3D, a governed "
                 "review-retrieval pipeline (untrusted-data classification, PII/injection screening, "
                 "structured-first retrieval, MMR reranking), a NetworkX evidence graph with access control, "
                 "and a complete November 2017 evidence package. No causal inference, no recommendations, "
                 "no LLM calls, no agents.",
        "kpi_movement_checks": kpi_checks,
        "revenue_absolute_change_check": revenue_absolute_check,
        "pvm_checks": pvm_checks,
        "materiality_check": materiality_check,
        "all_required_values_match": all_matches,
        "structured_evidence_count": len(package.structured_evidence),
        "structured_evidence_by_type": {
            et.value: sum(1 for ev in package.structured_evidence if ev.evidence_type == et)
            for et in EvidenceType if et.value in {ev.evidence_type.value for ev in package.structured_evidence}
        },
        "review_evidence_count": len(package.review_evidence),
        "review_language_distribution": review_language_counts,
        "review_security_status_distribution": review_security_counts,
        "review_pii_detected_count": review_pii_count,
        "retrieval": {
            name: {
                "n_results": len(results),
                "telemetry": vars(package.retrieval_telemetry[name]),
            }
            for name, results in package.retrieval_results.items()
        },
        "contradiction_checks": contradiction_summary,
        "graph_summary": {
            "n_nodes": package.graph.number_of_nodes(), "n_edges": package.graph.number_of_edges(),
            "node_types": sorted({attrs["node_type"] for _n, attrs in package.graph.nodes(data=True)}),
            "relationship_types": sorted({attrs["relationship_type"]
                                           for _u, _v, attrs in package.graph.edges(data=True)}),
        },
        "build_seconds": build_seconds,
        "full_structured_evidence": _evidence_summary(package.structured_evidence),
        "sample_review_evidence": _evidence_summary(package.review_evidence[:5]),
        "sample_retrieval_results": {
            name: [r.model_dump(mode="json") for r in results[:3]]
            for name, results in package.retrieval_results.items()
        },
        "test_results": run_tests(),
        "cache_stats": kpi_engine.cache.stats(),
    }

    out_path = REPO_ROOT / "reports" / "step4_validation.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"All required Nov 2017 evidence values match: {all_matches}")
    print(f"Structured evidence: {len(package.structured_evidence)}, review evidence: {len(package.review_evidence)}")
    print(f"Graph: {package.graph.number_of_nodes()} nodes, {package.graph.number_of_edges()} edges")
    print(f"Tests: {report['test_results']['n_passed']} passed, {report['test_results']['n_failed']} failed")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
