"""
step3c_validate_engine.py — runs the Step 3C materiality/anomaly engine
against the November 2017 revenue case (task §11) and a real sparse-history
product (task §12), both computed live via kpi.engine.KPIEngine and
anomaly.engine.detect(), runs the full Step 3C test suite, and writes
reports/step3c_validation.json.

Nothing in the JSON's "november_2017" or "sparse_entity" sections is a
hardcoded constant -- both are computed live against data/processed/*.parquet,
same discipline as scripts/step3b_validate_engine.py.
"""

from __future__ import annotations

import calendar
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from anomaly import engine as anomaly_engine  # noqa: E402
from anomaly.models import AnomalyRequest, BaselineLevel, PeriodObservation  # noqa: E402
from kpi.engine import KPIEngine  # noqa: E402
from kpi.models import KPIRequest  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_baselines.py", "tests/test_statistics.py",
         "tests/test_materiality.py", "tests/test_anomaly_engine.py", "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
            "failed_tests": failed, "all_passed": proc.returncode == 0}


def build_november_2017_case(kpi_engine: KPIEngine) -> dict:
    hist = []
    for m in range(1, 11):
        last_day = calendar.monthrange(2017, m)[1]
        r = kpi_engine.compute(KPIRequest(kpi_id="revenue", start_date=f"2017-{m:02d}-01",
                                           end_date=f"2017-{m:02d}-{last_day:02d}", override_analytical_window=True))
        hist.append(PeriodObservation(period=f"2017-{m:02d}", value=r.value, sample_size=r.sample_size))

    nov = kpi_engine.compute(KPIRequest(kpi_id="revenue", start_date="2017-11-01", end_date="2017-11-30",
                                         override_analytical_window=True))
    level = BaselineLevel(level="global", label="all_products_all_regions", history=hist)
    return {"observed": nov, "history": hist, "level": level}


def build_sparse_entity_case(kpi_engine: KPIEngine) -> dict | None:
    data = kpi_engine.data
    items = data.get("fact_order_items")[["order_id", "product_id", "price"]]
    orders = data.get("fact_orders")[["order_id", "purchase_timestamp"]]
    merged = items.merge(orders, on="order_id", how="inner")
    merged["month"] = merged["purchase_timestamp"].dt.to_period("M").astype(str)

    row_counts = merged.groupby("product_id").size()
    month_counts = merged.groupby("product_id")["month"].nunique()
    candidates = row_counts[(row_counts == 2) & (month_counts == 2)]
    if len(candidates) == 0:
        return None
    product_id = candidates.index[0]

    entity_rows = merged[merged["product_id"] == product_id].sort_values("purchase_timestamp")
    entity_monthly = entity_rows.groupby("month")["price"].agg(["sum", "size"]).sort_index()
    entity_history = [PeriodObservation(period=m, value=float(r["sum"]), sample_size=int(r["size"]))
                       for m, r in entity_monthly.iloc[:-1].iterrows()]
    observed_period = entity_monthly.index[-1]
    observed_value = float(entity_monthly.iloc[-1]["sum"])

    dim_product = data.get("dim_product")[["product_id", "category_name_en"]]
    with_cat = merged.merge(dim_product, on="product_id", how="left")
    category = with_cat.loc[with_cat["product_id"] == product_id, "category_name_en"].iloc[0]
    cat_rows = with_cat[(with_cat["category_name_en"] == category) & (with_cat["month"] < observed_period)]
    cat_monthly = cat_rows.groupby("month")["price"].agg(["sum", "size"]).sort_index()
    category_history = [PeriodObservation(period=m, value=float(r["sum"]), sample_size=int(r["size"]))
                         for m, r in cat_monthly.iterrows()]

    global_rows = merged[merged["month"] < observed_period]
    glob_monthly = global_rows.groupby("month")["price"].agg(["sum", "size"]).sort_index()
    global_history = [PeriodObservation(period=m, value=float(r["sum"]), sample_size=int(r["size"]))
                       for m, r in glob_monthly.iterrows()]

    levels = [
        BaselineLevel(level="entity", label=f"product:{product_id}", history=entity_history),
        BaselineLevel(level="category", label=f"category:{category}", history=category_history),
        BaselineLevel(level="global", label="all_products_all_regions", history=global_history),
    ]
    return {
        "product_id": str(product_id), "category": category, "observed_period": observed_period,
        "observed_value": observed_value, "levels": levels,
    }


def main():
    kpi_engine = KPIEngine()
    registry = SemanticRegistry.load()
    registry.validate()

    # -- November 2017 (task §11) ------------------------------------------
    nov_case = build_november_2017_case(kpi_engine)
    nov_req = AnomalyRequest(
        kpi_id="revenue", period="2017-11", observed_value=nov_case["observed"].value,
        observed_sample_size=nov_case["observed"].sample_size, observed_coverage=nov_case["observed"].coverage,
        levels=[nov_case["level"]],
    )
    nov_result = anomaly_engine.detect(registry, nov_req)

    # -- Sparse entity (task §12) -------------------------------------------
    sparse_case = build_sparse_entity_case(kpi_engine)
    sparse_result = None
    sparse_summary = None
    if sparse_case is not None:
        sparse_req = AnomalyRequest(
            kpi_id="revenue", period=sparse_case["observed_period"], observed_value=sparse_case["observed_value"],
            observed_sample_size=1, observed_coverage=0.01, levels=sparse_case["levels"],
        )
        sparse_result = anomaly_engine.detect(registry, sparse_req)
        sparse_summary = {
            "product_id": sparse_case["product_id"], "category": sparse_case["category"],
            "observed_period": sparse_case["observed_period"], "observed_value": sparse_case["observed_value"],
            "result": sparse_result.to_dict(),
        }

    test_results = run_tests()

    result = {
        "step": "3C",
        "scope": "Materiality and anomaly detection engine (deterministic/statistical) over the Step 3A/3B "
                 "governed KPI contracts. No PVM, causal inference, RAG, LLM, agents, recommendations, or "
                 "frontend exist in this module.",
        "baseline_strategies_implemented": [
            "previous_period", "rolling_mean", "rolling_median", "rolling_std", "ewma", "seasonal",
        ],
        "statistical_methods_implemented": ["z_score", "robust_z_score (median/MAD)", "percentile_rank"],
        "historical_sufficiency": {
            "fallback_ladder": ["entity", "category", "regional", "global"],
            "gate": "A level is usable only if it has >=3 non-null historical periods AND its total "
                    "underlying observations (sum of sample_size across periods) meets the KPI contract's "
                    "own materiality.minimum_observations. Never fabricates a baseline from an insufficient "
                    "level; a level failing every rung returns INSUFFICIENT_DATA.",
        },
        "materiality_decision_model": {
            "dimensions": ["magnitude", "statistical_abnormality", "business_impact"],
            "combination": "median of the three dimensions' tiers (0=NORMAL..3=CRITICAL) -- requires at "
                            "least two independent dimensions to agree before elevating the verdict; NOT a "
                            "product/multiplication of the three.",
            "caps": ["baseline_confidence in (LOW, NONE) caps the verdict at WATCH",
                     "low current-period sample size / coverage caps the verdict at WATCH"],
            "disagreement_rule": "If independent baseline methods' magnitude tiers span >= 2 tiers "
                                  "(e.g. one says NORMAL, another says MATERIAL), verdict = BASELINE_DISAGREEMENT "
                                  "-- the engine does not pick a winner. Exempt: when the primary baseline is "
                                  "'seasonal', a season-naive baseline (previous_period) is EXPECTED to diverge "
                                  "for a genuine seasonal peak, so that divergence alone does not trigger this rule.",
        },
        "november_2017": {
            "revenue_october": nov_case["history"][-1].value,
            "revenue_november_observed": nov_result.observed_value,
            "baseline_method": nov_result.baseline.baseline_method,
            "baseline_value": nov_result.baseline.baseline_value,
            "baseline_confidence": nov_result.baseline.baseline_confidence,
            "movement_absolute": nov_result.movement.absolute,
            "movement_percentage": nov_result.movement.percentage,
            "z_score": nov_result.statistical_signals.z_score,
            "robust_z_score": nov_result.statistical_signals.robust_z_score,
            "verdict": nov_result.materiality.verdict,
            "score": nov_result.materiality.score,
            "reasons": nov_result.materiality.reasons,
            "full_result": nov_result.to_dict(),
        },
        "sparse_entity_real_data": sparse_summary,
        "test_results": test_results,
        "cache_stats": kpi_engine.cache.stats(),
    }

    out_path = REPO_ROOT / "reports" / "step3c_validation.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2, default=str)

    print(f"November 2017 verdict: {nov_result.materiality.verdict} (score={nov_result.materiality.score})")
    if sparse_result is not None:
        print(f"Sparse entity verdict: {sparse_result.materiality.verdict}, "
              f"baseline_level={sparse_result.baseline.baseline_level}, "
              f"confidence={sparse_result.baseline.baseline_confidence}")
    print(f"Tests: {test_results['n_passed']} passed, {test_results['n_failed']} failed")
    print(f"\nWritten: {out_path}")


if __name__ == "__main__":
    main()
