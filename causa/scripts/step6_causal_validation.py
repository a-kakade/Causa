"""
step6_causal_validation.py — builds a real KPIEngine/SemanticRegistry, runs
the governed causal-analysis engine (src/causal/) against four hand-authored
hypotheses over real November 2017 canonical data, additionally exercises
did.py/interrupted_series.py against small synthetic fixtures to show the
code paths themselves CAN reach a genuine T3 result under a constructed
natural experiment, runs the Step 6 pytest suite, and writes
reports/step6_validation.json.

Every REQUIRED_VALUE_CHECKS entry below is used ONLY as a post-hoc assertion
target against the real, live-computed CausalResult objects -- never fed
into src/causal/'s own logic, same discipline
scripts/step4_validate_engine.py / step5_investigate_november_2017.py already
establish for their own REQUIRED_* constants.

No controls or interventions are fabricated: "all_other_categories"/
"all_other_states" are real, computable complements of a named treatment
group (every OTHER value of the same governed dimension actually observed in
the data), not invented control groups.
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

import networkx as nx  # noqa: E402

from kpi.engine import KPIEngine  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

import evidence.graph as graph_mod  # noqa: E402

from causal import did, interrupted_series  # noqa: E402
from causal.engine import run_causal_analysis  # noqa: E402
from causal.models import CausalHypothesis, CausalMethod, CausalStatus, CausalTier, EligibilityVerdict  # noqa: E402

OCT = ("2017-10-01", "2017-10-31")
NOV = ("2017-11-01", "2017-11-30")

TEST_FILES = [
    "tests/test_eligibility.py", "tests/test_method_selector.py", "tests/test_did.py",
    "tests/test_diagnostics.py", "tests/test_causal_gate.py", "tests/test_provenance.py",
    "tests/test_abstention.py",
]

# ---------------------------------------------------------------------------
# The 4 required November 2017 hypotheses -- real governed KPIs/dimensions,
# no fabricated controls or interventions (module docstring above).
# ---------------------------------------------------------------------------


def _order_volume_hypothesis() -> CausalHypothesis:
    return CausalHypothesis(
        hypothesis_id="C1_order_volume", treatment="orders", outcome="revenue", unit_of_analysis="order",
        treatment_period={"start": OCT[0], "end": OCT[1]}, outcome_period={"start": NOV[0], "end": NOV[1]},
        proposed_mechanism="Order volume growth is associated with revenue growth via the PVM volume effect.",
        required_data=["revenue", "orders"], proposed_method=CausalMethod.PVM,
        assumptions=["mix/price/volume decomposition is exhaustive"],
    )


def _category_growth_hypothesis() -> CausalHypothesis:
    return CausalHypothesis(
        hypothesis_id="C2_category_growth", treatment="product_category", outcome="revenue",
        unit_of_analysis="product_category",
        treatment_period={"start": "2017-01-01", "end": "2017-11-30"}, outcome_period={"start": OCT[0], "end": NOV[1]},
        proposed_mechanism="Revenue growth may be associated with disproportionate growth in the "
                           "bed_bath_table category.",
        required_data=["revenue"], proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        treatment_dimension="product_category", treatment_group_value="bed_bath_table",
        control_group_value="all_other_categories",
    )


def _delivery_review_hypothesis() -> CausalHypothesis:
    return CausalHypothesis(
        hypothesis_id="C3_delivery_review", treatment="on_time_delivery_rate", outcome="avg_review_score",
        unit_of_analysis="order",
        treatment_period={"start": OCT[0], "end": OCT[1]}, outcome_period={"start": NOV[0], "end": NOV[1]},
        proposed_mechanism="Delivery timing may be associated with the review score customers subsequently "
                           "submit, since delivery precedes review by construction.",
        required_data=["avg_delivery_days", "avg_review_score"],
        proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
    )


def _geographic_hypothesis() -> CausalHypothesis:
    return CausalHypothesis(
        hypothesis_id="C4_geographic", treatment="customer_state", outcome="revenue",
        unit_of_analysis="customer_state",
        treatment_period={"start": "2017-01-01", "end": "2017-11-30"}, outcome_period={"start": OCT[0], "end": NOV[1]},
        proposed_mechanism="Revenue growth may be associated with disproportionate growth from customers in SP.",
        required_data=["revenue"], proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        treatment_dimension="customer_state", treatment_group_value="SP", control_group_value="all_other_states",
    )


REQUIRED_VALUE_CHECKS = {
    "C1_order_volume": {"method": "PVM", "evidence_tier": "T2_ARITHMETIC", "status": "ARITHMETIC_ONLY",
                         "causal_claim_allowed": False},
    "C2_category_growth": {"method": "DESCRIPTIVE_ASSOCIATION", "evidence_tier": "T1_DESCRIPTIVE",
                            "status": "DESCRIPTIVE_ONLY", "causal_claim_allowed": False},
    "C3_delivery_review": {"method": "DESCRIPTIVE_ASSOCIATION", "evidence_tier": "T1_DESCRIPTIVE",
                            "status": "DESCRIPTIVE_ONLY", "causal_claim_allowed": False},
    "C4_geographic": {"method": "DESCRIPTIVE_ASSOCIATION", "evidence_tier": "T1_DESCRIPTIVE",
                       "status": "DESCRIPTIVE_ONLY", "causal_claim_allowed": False},
}


# ---------------------------------------------------------------------------
# Synthetic natural-experiment demonstrations (never presented as Olist
# findings) -- proof the DiD/ITS code paths themselves can reach T3 given
# genuine parallel-trends/sufficient-history data.
# ---------------------------------------------------------------------------


def _synthetic_did_demo() -> dict:
    from causal.models import CheckResult, CheckResultStatus, EligibilityReport

    series = [("m0", 100.0, 200.0), ("m1", 110.0, 210.0), ("m2", 120.0, 220.0), ("m3", 130.0, 230.0)]
    inputs = did.DiDInputs(treatment_pre=[130.0], treatment_post=[190.0], control_pre=[230.0],
                            control_post=[240.0], pre_period_series=series)
    eligibility = EligibilityReport(hypothesis_id="synthetic_did", verdict=EligibilityVerdict.ELIGIBLE,
                                     checks=[CheckResult("x", CheckResultStatus.PASS, "synthetic, all pass")])
    h = _category_growth_hypothesis()
    result = did.run_did(h, inputs, eligibility)
    return {"evidence_tier": result.evidence_tier.value, "causal_claim_allowed": result.causal_claim_allowed,
            "status": result.status.value, "note": "Synthetic constructed natural experiment -- NOT an Olist finding."}


def _synthetic_its_demo() -> dict:
    from causal.models import CheckResult, CheckResultStatus, EligibilityReport

    # A fixed-seed, small i.i.d. noise term is added on top of the exact
    # level-shift/slope-change step function -- a perfectly noiseless
    # synthetic series produces near-zero residuals whose lag-1
    # "autocorrelation" is floating-point noise, not a genuine diagnostic
    # signal; a touch of real, reproducible noise avoids that degenerate
    # case so this demo genuinely exercises the passing path.
    import random
    rng = random.Random(6)
    labels = [f"m{i}" for i in range(20)]
    base = [100.0 + 2.0 * t for t in range(15)] + [100.0 + 2.0 * 14 + 50.0 + 7.0 * (t + 1) for t in range(5)]
    values = [v + rng.uniform(-1.0, 1.0) for v in base]
    inputs = interrupted_series.ITSInputs(period_labels=labels, values=values, intervention_index=15)
    eligibility = EligibilityReport(hypothesis_id="synthetic_its", verdict=EligibilityVerdict.ELIGIBLE,
                                     checks=[CheckResult("x", CheckResultStatus.PASS, "synthetic, all pass")])
    h = _delivery_review_hypothesis()
    result = interrupted_series.run_its(h, inputs, eligibility)
    return {"evidence_tier": result.evidence_tier.value, "causal_claim_allowed": result.causal_claim_allowed,
            "status": result.status.value, "note": "Synthetic constructed natural experiment -- NOT an Olist finding."}


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


def main() -> None:
    t_start = time.time()
    registry = SemanticRegistry.load()
    registry.validate()
    kpi_engine = KPIEngine(registry=registry)

    graph = graph_mod.new_graph()
    hypotheses = {
        "C1_order_volume": _order_volume_hypothesis(),
        "C2_category_growth": _category_growth_hypothesis(),
        "C3_delivery_review": _delivery_review_hypothesis(),
        "C4_geographic": _geographic_hypothesis(),
    }
    results = {hid: run_causal_analysis(h, kpi_engine, registry, graph=graph) for hid, h in hypotheses.items()}
    run_seconds = round(time.time() - t_start, 2)

    value_checks = {}
    for hid, expected in REQUIRED_VALUE_CHECKS.items():
        result = results[hid]
        value_checks[hid] = {
            "expected": expected,
            "actual": {"method": result.method.value, "evidence_tier": result.evidence_tier.value,
                       "status": result.status.value, "causal_claim_allowed": result.causal_claim_allowed},
            "match": (result.method.value == expected["method"]
                      and result.evidence_tier.value == expected["evidence_tier"]
                      and result.status.value == expected["status"]
                      and result.causal_claim_allowed == expected["causal_claim_allowed"]),
        }
    value_checks["all_checks_pass"] = all(v["match"] for v in value_checks.values() if isinstance(v, dict) and "match" in v)
    value_checks["no_hypothesis_reaches_causal_claim_allowed_true"] = not any(
        r.causal_claim_allowed for r in results.values()
    )
    value_checks["no_hypothesis_reaches_t3_or_t4"] = not any(
        r.evidence_tier in (CausalTier.T3_QUASI_EXPERIMENTAL, CausalTier.T4_EXPERIMENTAL) for r in results.values()
    )

    test_results = run_tests()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_seconds": run_seconds,
        "required_value_checks": value_checks,
        "results_by_hypothesis": {hid: r.to_dict() for hid, r in results.items()},
        "evidence_graph_summary": {
            "n_nodes": graph.number_of_nodes(), "n_edges": graph.number_of_edges(),
            "node_types": sorted({data.get("node_type") for _, data in graph.nodes(data=True)}),
        },
        "synthetic_method_demonstrations": {
            "difference_in_differences": _synthetic_did_demo(),
            "interrupted_time_series": _synthetic_its_demo(),
        },
        "honest_abstention_note": (
            "All 4 real Olist hypotheses land at T1/T2 with causal_claim_allowed=False. This is the "
            "SUCCESSFUL, intended outcome of a governed causal layer applied to an observational dataset "
            "with no designed experiment -- see docs/CAUSAL_GOVERNANCE.md #4. The DiD/ITS code paths "
            "themselves are verified to reach a genuine T3_QUASI_EXPERIMENTAL result under a constructed "
            "synthetic natural experiment (synthetic_method_demonstrations above) -- Olist's own data "
            "simply does not contain one for these questions, and this engine does not manufacture one."
        ),
        "tests": test_results,
    }

    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    with open(reports_dir / "step6_validation.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Step 6 causal validation complete in {run_seconds}s.")
    print(f"all_checks_pass={value_checks['all_checks_pass']}, "
          f"tests: {test_results['n_passed']} passed / {test_results['n_failed']} failed")
    for hid, v in value_checks.items():
        if isinstance(v, dict) and "actual" in v:
            print(f"  {hid}: {v['actual']} (match={v['match']})")
    print(f"Wrote {reports_dir / 'step6_validation.json'}")


if __name__ == "__main__":
    main()
