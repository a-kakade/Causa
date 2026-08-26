"""
step2_05_validation_report.py — runs the full Step 2 test suite and compiles
reports/step2_validation.json: canonical row counts, dropped/transformed records,
test pass/fail results, and pointers to every upstream analysis JSON. This is the
machine-readable backing for STEP2_VALIDATION.md -- run this LAST, after
step2_01..04.

Usage:
    python scripts/step2_05_validation_report.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed_match = re.search(r"(\d+) passed", output)
    n_failed_match = re.search(r"(\d+) failed", output)
    n_passed = int(n_passed_match.group(1)) if n_passed_match else 0
    n_failed = int(n_failed_match.group(1)) if n_failed_match else 0
    return {
        "returncode": proc.returncode,
        "n_passed": n_passed,
        "n_failed": n_failed,
        "failed_tests": failed,
        "all_passed": proc.returncode == 0,
        "raw_summary_tail": output.strip().splitlines()[-8:],
    }


def load_json(name: str) -> dict | None:
    path = REPORTS_DIR / name
    if not path.exists():
        return None
    return json.load(open(path))


def main():
    test_results = run_tests()

    window = load_json("step2_window_analysis.json")
    revenue = load_json("step2_revenue_reconciliation.json")
    dedup = load_json("step2_review_dedup_comparison.json")
    build = load_json("step2_build_summary.json")

    validation = {
        "step": 2,
        "test_results": test_results,
        "analytical_window_decision": {
            "start": window["first_reliable_month"] if window else None,
            "end": window["last_reliable_month"] if window else None,
            "method": window["method"] if window else None,
            "excluded_months": window["unreliable_months"] if window else None,
        },
        "canonical_row_counts": build["canonical_row_counts"] if build else None,
        "raw_row_counts": build["raw_row_counts"] if build else None,
        "row_count_reconciliation": build["row_count_reconciliation"] if build else None,
        "transformed_records": build["transformed_records"] if build else None,
        "revenue_reconciliation_summary": revenue["reconciliation_item_gmv_vs_payment_total"] if revenue else None,
        "review_dedup_strategies_summary": {
            k: {
                "mean_score": v["mean_score"], "text_coverage_pct": v["text_coverage_pct"],
                "bias": v["bias_vs_simple_average_of_all_reviews_for_that_order"]["mean_signed_bias"],
            }
            for k, v in dedup["strategies"].items()
        } if dedup else None,
        "source_reports": [
            "reports/step2_window_analysis.json",
            "reports/step2_revenue_reconciliation.json",
            "reports/step2_review_dedup_comparison.json",
            "reports/step2_build_summary.json",
        ],
    }

    out_path = REPORTS_DIR / "step2_validation.json"
    with open(out_path, "w") as f:
        json.dump(validation, f, indent=2, default=str)

    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed")
    if test_results["failed_tests"]:
        print("FAILED:", test_results["failed_tests"])
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
