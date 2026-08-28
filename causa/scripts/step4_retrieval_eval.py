"""
step4_retrieval_eval.py — runs the curated retrieval evaluation set (task
§23) against the real October-November 2017 vector index and writes
reports/retrieval_evaluation.json.

This is a small, manually curated ENGINEERING evaluation set -- not a
statistically representative benchmark (task §23 is explicit about this).
Reports Precision@5, Precision@10, MRR, candidate counts before/after
structured filtering, an irrelevant-retrieval-rate, and latency per query,
plus per-category and overall summaries.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lib.raw_loader import PROCESSED_DIR  # noqa: E402

from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from evidence import retrieval, structured_adapter as adapter  # noqa: E402
from evidence.engine import build_review_index  # noqa: E402
from evidence.schema import EvidenceQuery  # noqa: E402

CANONICAL_TABLES = [
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
]
EVAL_SET_PATH = REPO_ROOT / "data" / "evidence" / "eval" / "retrieval_eval_set.json"


def precision_at_k(retrieved_ids: list[str], expected_ids: set[str], k: int) -> float:
    top_k = retrieved_ids[:k]
    if not top_k:
        return 0.0
    return sum(1 for rid in top_k if rid in expected_ids) / len(top_k)


def mrr(retrieved_ids: list[str], expected_ids: set[str]) -> float:
    for rank, rid in enumerate(retrieved_ids, start=1):
        if rid in expected_ids:
            return 1.0 / rank
    return 0.0


def main():
    with open(EVAL_SET_PATH) as f:
        eval_set = json.load(f)

    canonical = {t: pd.read_parquet(PROCESSED_DIR / f"{t}.parquet") for t in CANONICAL_TABLES}
    registry = SemanticRegistry.load()
    registry.validate()

    _corpus, _review_evidence, evidence_by_row_id, index, cache = build_review_index(canonical)

    per_query = []
    for cat in eval_set["categories"]:
        category = cat["category"]
        for q in cat["queries"]:
            expected_row_ids = q["expected_relevant_review_row_ids"]
            expected_evidence_ids = {adapter.evidence_id_for("review", rid) for rid in expected_row_ids}

            query = EvidenceQuery(
                investigation_id="retrieval_eval", question=q["question"],
                structured_filters=q["structured_filters"], semantic_query=q.get("semantic_query"),
                top_k=10, requester_clearance="INTERNAL",
            )
            t0 = time.perf_counter()
            results, telemetry = retrieval.retrieve(query, index, registry, evidence_by_row_id)
            latency_ms = round((time.perf_counter() - t0) * 1000, 3)

            retrieved_ids = [r.evidence_id for r in results]
            p5 = precision_at_k(retrieved_ids, expected_evidence_ids, 5)
            p10 = precision_at_k(retrieved_ids, expected_evidence_ids, 10)
            reciprocal_rank = mrr(retrieved_ids, expected_evidence_ids)
            top10 = retrieved_ids[:10]
            irrelevant_rate = (
                sum(1 for rid in top10 if rid not in expected_evidence_ids) / len(top10) if top10 else None
            )

            per_query.append({
                "category": category, "query_id": q["query_id"], "question": q["question"],
                "expected_count": len(expected_evidence_ids),
                "retrieved_count": len(results),
                "precision_at_5": p5, "precision_at_10": p10, "mrr": reciprocal_rank,
                "irrelevant_retrieval_rate": irrelevant_rate,
                "candidates_before_filter": telemetry.candidates_before_filter,
                "candidates_after_filter": telemetry.candidates_after_filter,
                "latency_ms": latency_ms,
            })

    def _mean(key):
        values = [q[key] for q in per_query if q[key] is not None]
        return round(sum(values) / len(values), 4) if values else None

    per_category = {}
    for cat in eval_set["categories"]:
        name = cat["category"]
        rows = [q for q in per_query if q["category"] == name]
        per_category[name] = {
            "n_queries": len(rows),
            "mean_precision_at_5": round(sum(r["precision_at_5"] for r in rows) / len(rows), 4),
            "mean_precision_at_10": round(sum(r["precision_at_10"] for r in rows) / len(rows), 4),
            "mean_mrr": round(sum(r["mrr"] for r in rows) / len(rows), 4),
        }

    report = {
        "note": "Engineering evaluation set (Step 4 task §23) -- small, manually curated, NOT a "
                "statistically representative benchmark.",
        "eval_set_path": str(EVAL_SET_PATH.relative_to(REPO_ROOT)),
        "n_queries": len(per_query),
        "per_query": per_query,
        "per_category_summary": per_category,
        "overall": {
            "mean_precision_at_5": _mean("precision_at_5"),
            "mean_precision_at_10": _mean("precision_at_10"),
            "mean_mrr": _mean("mrr"),
            "mean_irrelevant_retrieval_rate": _mean("irrelevant_retrieval_rate"),
            "mean_latency_ms": _mean("latency_ms"),
        },
        "embedding_cache_stats": cache.stats(),
    }

    out_path = REPO_ROOT / "reports" / "retrieval_evaluation.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    print(f"Overall: P@5={report['overall']['mean_precision_at_5']}, "
          f"P@10={report['overall']['mean_precision_at_10']}, MRR={report['overall']['mean_mrr']}")
    print(f"Written: {out_path}")


if __name__ == "__main__":
    main()
