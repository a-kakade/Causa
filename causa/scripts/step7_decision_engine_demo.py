"""
step7_decision_engine_demo.py — runs the Decision & Action Intelligence
Engine against two deterministic demo scenarios (delivery_delay, aov_decline),
runs the Step 7 pytest suite, and writes reports/step7_validation.json.

No canonical data dependency: unlike Steps 3-6, Step 7's DriverSignal input
is either hand-authored (as here) or bridged from a real upstream Step 5/6
result (src/decision/bridge.py) -- the engine itself never reads
data/processed/*.parquet directly. This script demonstrates the
hand-authored path with the exact demo values the task specification
requires.

Every REQUIRED_VALUE_CHECKS entry below is used ONLY as a post-hoc assertion
against the real, live-computed DecisionResult -- never fed into
src/decision/'s own logic, matching the discipline every prior step's
validation script establishes.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from decision.explanation import narrate  # noqa: E402
from decision.models import DriverSignal  # noqa: E402
from decision.ontology import DecisionOntology, DecisionScoringConfig  # noqa: E402
from decision.ranking import run_decision_pipeline  # noqa: E402

TEST_FILES = [
    "tests/test_decision_ontology.py", "tests/test_candidate_generator.py", "tests/test_constraint_engine.py",
    "tests/test_impact_estimator.py", "tests/test_confidence_engine.py", "tests/test_scoring.py",
    "tests/test_ranking.py", "tests/test_monitoring.py", "tests/test_decision_bridge.py",
    "tests/test_decision_explanation.py", "tests/test_decision_end_to_end.py", "tests/test_decision_provenance.py",
]

# ---------------------------------------------------------------------------
# Demo scenario 1 (task's own exact required values): Delivery Delay
# ---------------------------------------------------------------------------


def _delivery_delay_signal() -> DriverSignal:
    return DriverSignal(
        driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS", kpi_id="on_time_delivery_rate",
        period="2017-11", observed_change_pct=-0.08, addressable_population=12500,
        addressable_population_source="HISTORICAL_ESTIMATE", historical_estimated_effect=0.06,
        historical_effect_source="HISTORICAL_ESTIMATE", driver_confidence=0.78, source="MANUAL",
        business_context={"budget_available": True, "operational_capacity_available": True},
    )


# ---------------------------------------------------------------------------
# Demo scenario 2 (proves ontology extensibility beyond the one required
# driver): AOV Decline
# ---------------------------------------------------------------------------


def _aov_decline_signal() -> DriverSignal:
    return DriverSignal(
        driver="aov_decline", driver_category="PRICING_PRODUCT_MIX", kpi_id="aov", period="2017-11",
        observed_change_pct=-0.05, addressable_population=85000, addressable_population_source="HISTORICAL_ESTIMATE",
        historical_estimated_effect=12.5, historical_effect_source="HISTORICAL_ESTIMATE", driver_confidence=0.72,
        source="MANUAL",
        business_context={"budget_available": True, "inventory_units_available": 5000,
                           "authorized_owner_roles": ["Pricing Manager", "Commercial Manager", "Product Manager"]},
    )


REQUIRED_VALUE_CHECKS = {
    "delivery_delay": {
        "top_recommendation_present": True,
        "calculated_impact": 0.06 * 12500 * 0.78,
        "estimated_effect": 0.06,
        "addressable_population": 12500,
        "confidence": 0.78,
        "not_a_generic_string": True,
    },
}


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


_GENERIC_PHRASES = ("improve logistics", "improve delivery", "increase marketing", "do better", "fix the problem")


def main() -> None:
    t_start = time.time()
    ontology = DecisionOntology.load()
    ontology.validate()
    scoring = DecisionScoringConfig.load()
    scoring.validate()

    delivery_result = run_decision_pipeline(_delivery_delay_signal(), ontology, scoring)
    aov_result = run_decision_pipeline(_aov_decline_signal(), ontology, scoring)
    run_seconds = round(time.time() - t_start, 2)

    delivery_top = delivery_result.top_recommendation
    value_checks = {
        "delivery_delay": {
            "expected": REQUIRED_VALUE_CHECKS["delivery_delay"],
            "actual": {
                "top_recommendation_present": delivery_top is not None,
                "calculated_impact": delivery_top.expected_impact.calculated_impact if delivery_top else None,
                "estimated_effect": delivery_top.expected_impact.estimated_effect if delivery_top else None,
                "addressable_population": delivery_top.expected_impact.addressable_population if delivery_top else None,
                "confidence": delivery_top.expected_impact.confidence if delivery_top else None,
                "not_a_generic_string": bool(delivery_top) and not any(
                    p in delivery_top.possible_action.lower() for p in _GENERIC_PHRASES
                ),
            },
        },
    }
    dd_actual = value_checks["delivery_delay"]["actual"]
    dd_expected = value_checks["delivery_delay"]["expected"]
    value_checks["delivery_delay"]["match"] = (
        dd_actual["top_recommendation_present"] == dd_expected["top_recommendation_present"]
        and dd_actual["calculated_impact"] == dd_expected["calculated_impact"]
        and dd_actual["estimated_effect"] == dd_expected["estimated_effect"]
        and dd_actual["addressable_population"] == dd_expected["addressable_population"]
        and dd_actual["confidence"] == dd_expected["confidence"]
        and dd_actual["not_a_generic_string"] is True
    )
    value_checks["all_checks_pass"] = value_checks["delivery_delay"]["match"]
    value_checks["aov_decline_ontology_extensibility_proven"] = aov_result.top_recommendation is not None
    value_checks["multiple_candidates_generated_delivery_delay"] = delivery_result.all_candidates_evaluated > 1
    value_checks["multiple_candidates_generated_aov_decline"] = aov_result.all_candidates_evaluated > 1

    test_results = run_tests()

    delivery_narrative = narrate(delivery_result, llm_client=None)
    aov_narrative = narrate(aov_result, llm_client=None)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_seconds": run_seconds,
        "required_value_checks": value_checks,
        "results": {
            "delivery_delay": delivery_result.to_dict(),
            "aov_decline": aov_result.to_dict(),
        },
        "narratives": {
            "delivery_delay": delivery_narrative,
            "aov_decline": aov_narrative,
        },
        "tests": test_results,
    }

    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report_path = reports_dir / "step7_validation.json"
    report_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"Step 7 demo complete in {run_seconds}s. Report written to {report_path}")
    print(f"\n=== Delivery Delay top recommendation ===\n{delivery_narrative}\n")
    print(f"=== AOV Decline top recommendation ===\n{aov_narrative}\n")
    print(f"Required value checks all pass: {value_checks['all_checks_pass']}")
    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed "
          f"(all_passed={test_results['all_passed']})")

    if not value_checks["all_checks_pass"] or not test_results["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
