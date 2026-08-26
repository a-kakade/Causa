"""
step3d_validate_engine.py — runs the Step 3D driver decomposition engine
against the October->November 2017 revenue movement (task §2/§16), computed
live via kpi.engine.KPIEngine + drivers.engine.decompose() against
data/processed/*.parquet, runs the full Step 3D test suite, and writes
reports/step3d_validation.json.

Nothing in the JSON is a hardcoded constant -- every number is computed live,
same discipline as scripts/step3b_validate_engine.py and
scripts/step3c_validate_engine.py.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from drivers import engine as driver_engine  # noqa: E402
from drivers.models import DriverDecompositionRequest  # noqa: E402
from drivers.ranking import rank_dimensions_by_contribution  # noqa: E402
from kpi.engine import KPIEngine  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

OCT_2017 = ("2017-10-01", "2017-10-31", "2017-10")
NOV_2017 = ("2017-11-01", "2017-11-30", "2017-11")

REQUIRED_PVM = {"volume": 417227.65, "price": 4674.63, "mix": -75850.34}
REQUIRED_REVENUE = {"october": 664219.43, "november": 1010271.37, "change": 346051.94}


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_pvm.py", "tests/test_contributions.py",
         "tests/test_driver_engine.py", "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
            "failed_tests": failed, "all_passed": proc.returncode == 0}


def _seg_summary(contributions, n=10):
    return [
        {"segment_value": c.segment_value, "previous_value": round(c.previous_value, 2),
         "current_value": round(c.current_value, 2), "absolute_change": round(c.absolute_change, 2),
         "percentage_change": c.percentage_change,
         "share_of_total_movement_pct": None if c.share_of_total_movement is None else round(c.share_of_total_movement, 2),
         "rank": c.rank, "sample_size": c.sample_size, "history_periods": c.history_periods,
         "confidence": c.confidence}
        for c in contributions[:n]
    ]


def main():
    kpi_engine = KPIEngine()
    registry = SemanticRegistry.load()
    registry.validate()

    request = DriverDecompositionRequest(
        kpi_id="revenue",
        period_current_start=NOV_2017[0], period_current_end=NOV_2017[1], period_current_label=NOV_2017[2],
        period_previous_start=OCT_2017[0], period_previous_end=OCT_2017[1], period_previous_label=OCT_2017[2],
        override_analytical_window=True, requester_clearance="INTERNAL",
        segment_dimensions=["product_category", "seller", "customer_state", "seller_state"],
        top_n=10,
    )
    result = driver_engine.decompose(kpi_engine, registry, request)
    tree = driver_engine.build_contribution_tree(result)
    dimension_ranking = rank_dimensions_by_contribution(result.segment_contributions)

    by_driver = {d.driver: d.contribution_value for d in result.drivers}
    pvm_checks = {
        name: {"computed": by_driver[name], "required": REQUIRED_PVM[name],
               "matches": abs(by_driver[name] - REQUIRED_PVM[name]) < 0.01}
        for name in REQUIRED_PVM
    }
    # bridge.revenue_previous/current are the authoritative October/November
    # totals PVM reconciled against -- recomputed once more here, directly and
    # independently of `result`, so this report's revenue_checks section is
    # legible on its own rather than reaching back into `result`'s internals.
    from drivers.engine import _load_period_items
    from drivers.pvm import compute_pvm_bridge
    items_prev = _load_period_items(kpi_engine.data, OCT_2017[0], OCT_2017[1], True, None)
    items_curr = _load_period_items(kpi_engine.data, NOV_2017[0], NOV_2017[1], True, None)
    bridge = compute_pvm_bridge(items_prev, items_curr)
    revenue_checks = {
        "october": {"computed": round(bridge.revenue_previous, 2), "required": REQUIRED_REVENUE["october"],
                    "matches": abs(bridge.revenue_previous - REQUIRED_REVENUE["october"]) < 0.01},
        "november": {"computed": round(bridge.revenue_current, 2), "required": REQUIRED_REVENUE["november"],
                     "matches": abs(bridge.revenue_current - REQUIRED_REVENUE["november"]) < 0.01},
        "change": {"computed": round(result.total_change["absolute"], 2), "required": REQUIRED_REVENUE["change"],
                   "matches": abs(result.total_change["absolute"] - REQUIRED_REVENUE["change"]) < 0.01},
    }

    all_matches = result.reconciliation.reconciled and all(c["matches"] for c in pvm_checks.values()) \
        and all(c["matches"] for c in revenue_checks.values())

    november_investigation_context = {
        "revenue_pct_change": result.total_change["percentage"],
        "orders": result.concurrent_kpis["orders"].to_dict(),
        "aov": result.concurrent_kpis["aov"].to_dict(),
        "freight_revenue": result.concurrent_kpis["freight_revenue"].to_dict(),
        "avg_delivery_days": result.concurrent_kpis["avg_delivery_days"].to_dict(),
        "avg_review_score": result.concurrent_kpis["avg_review_score"].to_dict(),
        "pvm": {d.driver: d.contribution_value for d in result.drivers},
        "category_contribution_top10": _seg_summary(result.segment_contributions["product_category"]),
        "seller_contribution_top10": _seg_summary(result.segment_contributions["seller"]),
        "customer_state_contribution_top10": _seg_summary(result.segment_contributions["customer_state"]),
        "seller_state_contribution_top10": _seg_summary(result.segment_contributions["seller_state"]),
        "dimension_ranking": dimension_ranking,
        "note": "Evidence package only -- no causal conclusion is drawn here or anywhere in this module. "
                "This is deterministic input for a future Agentic Investigation Engine, not built in Step 3D.",
    }

    test_results = run_tests()

    report = {
        "step": "3D",
        "scope": "Driver decomposition engine (deterministic PVM + segment contribution) over the Step 3B "
                 "canonical KPI computation. No causal inference, RAG, LLM, agents, or recommendations exist "
                 "in this module.",
        "pvm_methodology": {
            "formula": "Delta Revenue = Volume Effect + Price Effect + Mix Effect",
            "volume_effect": "(Qty_new_total - Qty_old_total) * overall_avg_price_old",
            "price_effect": "sum_over_category(Qty_new_cat * (Price_new_cat - Price_old_cat))",
            "mix_effect": "Delta Revenue - Volume Effect - Price Effect (residual, exact by construction)",
            "grain": "product_category (dim_product.category_name_en, NULL normalized to 'uncategorized')",
            "reference": "docs/INVESTIGATION_SCENARIOS.md §2; re-verified against data/processed/*.parquet "
                         "before this module was written.",
        },
        "revenue_checks": revenue_checks,
        "pvm_checks": pvm_checks,
        "pvm_checksum": {
            "sum_of_effects": round(sum(by_driver.values()), 2),
            "actual_change": round(result.total_change["absolute"], 2),
            "error": result.reconciliation.error,
            "tolerance": result.reconciliation.tolerance,
            "reconciled": result.reconciliation.reconciled,
        },
        "all_required_values_match": all_matches,
        "segment_reconciliation": result.data_quality.segment_reconciliation,
        "dimension_ranking": dimension_ranking,
        "november_investigation_context": november_investigation_context,
        "contribution_tree_sample": tree,
        "full_result": result.to_dict(),
        "test_results": test_results,
        "cache_stats": kpi_engine.cache.stats(),
    }

    out_path = REPO_ROOT / "reports" / "step3d_validation.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"All required Nov 2017 PVM/revenue values match: {all_matches}")
    print(f"PVM checksum error: {result.reconciliation.error}")
    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
