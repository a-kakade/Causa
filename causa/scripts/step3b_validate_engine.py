"""
step3b_validate_engine.py — runs the Step 3B engine against the exact October/
November 2017 validation numbers required by the task spec, runs the full Step
3B test suite, and writes reports/step3b_validation.json.

Every number in the "november_2017_validation" section below is computed live
by KPIEngine against data/processed/*.parquet -- none are hardcoded constants
copied from a prior step's report.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kpi.engine import KPIEngine  # noqa: E402
from kpi.models import KPIRequest  # noqa: E402

OCT_2017 = ("2017-10-01", "2017-10-31")
NOV_2017 = ("2017-11-01", "2017-11-30")


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_kpi_engine.py", "tests/test_kpi_dimensions.py",
         "tests/test_kpi_results.py", "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
            "failed_tests": failed, "all_passed": proc.returncode == 0}


def main():
    engine = KPIEngine()

    oct_revenue = engine.compute(KPIRequest(kpi_id="revenue", start_date=OCT_2017[0], end_date=OCT_2017[1]))
    nov_revenue = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    oct_orders = engine.compute(KPIRequest(kpi_id="orders", start_date=OCT_2017[0], end_date=OCT_2017[1]))
    nov_orders = engine.compute(KPIRequest(kpi_id="orders", start_date=NOV_2017[0], end_date=NOV_2017[1]))

    revenue_cmp = engine.compare_periods("revenue", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
    orders_cmp = engine.compare_periods("orders", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])

    november_2017_validation = {
        "revenue": {
            "october_value": round(oct_revenue.value, 2),
            "october_expected": 664219.43,
            "october_matches": round(oct_revenue.value, 2) == 664219.43,
            "november_value": round(nov_revenue.value, 2),
            "november_expected": 1010271.37,
            "november_matches": round(nov_revenue.value, 2) == 1010271.37,
            "change_value": round(revenue_cmp.absolute_change, 2),
            "change_expected": 346051.94,
            "change_matches": round(revenue_cmp.absolute_change, 2) == 346051.94,
            "pct_change_value": round(revenue_cmp.percentage_change, 1),
            "pct_change_expected": 52.1,
            "pct_change_matches": round(revenue_cmp.percentage_change, 1) == 52.1,
        },
        "orders": {
            "october_value": oct_orders.value,
            "october_expected": 4631,
            "october_matches": oct_orders.value == 4631.0,
            "november_value": nov_orders.value,
            "november_expected": 7544,
            "november_matches": nov_orders.value == 7544.0,
            "pct_change_value": round(orders_cmp.percentage_change, 1),
            "pct_change_expected": 62.9,
            "pct_change_matches": round(orders_cmp.percentage_change, 1) == 62.9,
        },
    }
    all_validation_checks_pass = all(
        v for section in november_2017_validation.values()
        for k, v in section.items() if k.endswith("_matches")
    )

    # sample of every other KPI, computed live, for the report
    kpi_samples = {}
    for kpi_id in ["aov", "avg_delivery_days", "avg_review_score", "freight_revenue",
                   "review_volume", "on_time_delivery_rate", "quantity_sold", "repeat_purchase_rate"]:
        kwargs = {} if kpi_id == "repeat_purchase_rate" else {"start_date": NOV_2017[0], "end_date": NOV_2017[1]}
        r = engine.compute(KPIRequest(kpi_id=kpi_id, **kwargs))
        kpi_samples[kpi_id] = {
            "value": r.value, "sample_size": r.sample_size, "coverage": r.coverage,
            "data_quality": r.data_quality, "warnings": r.warnings,
        }

    test_results = run_tests()

    result = {
        "step": "3B",
        "scope": "Deterministic KPI computation engine implementing the Step 3A contracts. "
                 "No anomaly detection, PVM, causal inference, RAG, agents, or recommendations.",
        "november_2017_validation": november_2017_validation,
        "all_validation_checks_pass": all_validation_checks_pass,
        "note": "Every value above is computed live by src/kpi/engine.py against "
                "data/processed/*.parquet -- none are hardcoded.",
        "kpi_samples_november_2017": kpi_samples,
        "cache_stats": engine.cache.stats(),
        "test_results": test_results,
    }

    out_path = REPO_ROOT / "reports" / "step3b_validation.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"All Nov 2017 validation checks pass: {all_validation_checks_pass}")
    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
