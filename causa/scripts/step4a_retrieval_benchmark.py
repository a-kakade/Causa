"""
step4a_retrieval_benchmark.py — Step 4A retrieval failure analysis and
multi-method benchmark.

Runs the same evaluation set as step4_retrieval_eval.py against:

  1. BM25-only (lexical baseline)
  2. BM25 + query expansion
  3. Dense E5-small (existing, validated)
  4. Hybrid RRF (BM25 + E5-small)
  5. Hybrid RRF + query expansion

Outputs:
  reports/step4a_retrieval_benchmark.json   — full per-query results
  reports/step4a_length_analysis.json       — results by review length bucket
  reports/step4a_language_analysis.json     — results by detected language

Also emits a comparison table to stdout.

Invoke:
    .venv/bin/python scripts/step4a_retrieval_benchmark.py

This script does NOT modify any existing source files and is read-only
with respect to data/processed/*.parquet and the vector index/cache.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lib.raw_loader import PROCESSED_DIR  # noqa: E402

from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from evidence import retrieval as retrieval_module, structured_adapter as adapter  # noqa: E402
from evidence.bm25_retriever import BM25Index  # noqa: E402
from evidence.dense_retriever import DenseRetriever, E5EmbeddingProvider  # noqa: E402
from evidence.engine import build_review_index  # noqa: E402
from evidence.hybrid_retriever import HybridRetriever, LexicalRetriever  # noqa: E402
from evidence.retriever_interface import (  # noqa: E402
    MIN_BM25_SCORE_FLOOR, MIN_DENSE_SCORE_FLOOR, MIN_HYBRID_SCORE_FLOOR, RetrievalInsufficient,
)
from evidence.schema import EvidenceQuery  # noqa: E402

CANONICAL_TABLES = [
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
]
EVAL_SET_PATH = REPO_ROOT / "data" / "evidence" / "eval" / "retrieval_eval_set.json"


# ── Metrics ────────────────────────────────────────────────────────────────

def precision_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    top = retrieved[:k]
    if not top:
        return 0.0
    return sum(1 for r in top if r in relevant) / len(top)


def mrr(retrieved: list[int], relevant: set[int]) -> float:
    for rank, r in enumerate(retrieved, start=1):
        if r in relevant:
            return 1.0 / rank
    return 0.0


def recall_at_k(retrieved: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(retrieved[:k])
    return len(top & relevant) / len(relevant)


# ── Review metadata for sub-analyses ──────────────────────────────────────

def length_bucket(text: str) -> str:
    tokens = text.split()
    n = len(tokens)
    if n <= 3:
        return "1-3_tokens"
    elif n <= 10:
        return "4-10_tokens"
    elif n <= 25:
        return "11-25_tokens"
    else:
        return "25+_tokens"


# ── Score normalizers (for RETRIEVAL_INSUFFICIENT checks) ─────────────────

def check_insufficient(results: list[tuple[int, float]], method: str,
                        n_candidates: int, n_total: int,
                        score_floor: float) -> bool:
    """Returns True if the retrieval result is RETRIEVAL_INSUFFICIENT."""
    if not results:
        return True
    best_score = results[0][1]
    return best_score < score_floor


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("Loading eval set...")
    with open(EVAL_SET_PATH) as f:
        eval_set = json.load(f)

    print("Loading canonical tables...")
    canonical = {t: pd.read_parquet(PROCESSED_DIR / f"{t}.parquet") for t in CANONICAL_TABLES}
    registry = SemanticRegistry.load()
    registry.validate()

    print("Building review index (uses embedding cache)...")
    t_build_start = time.perf_counter()
    review_corpus, review_evidence, evidence_by_row_id, dense_index, cache = build_review_index(canonical)
    t_build = time.perf_counter() - t_build_start
    print(f"  Index built in {t_build:.1f}s — {len(dense_index)} vectors")

    # Build BM25 index over the same corpus
    print("Building BM25 index...")
    t_bm25_start = time.perf_counter()
    # text_rows order matches dense_index metadata order
    text_rows = [r for r in review_corpus if r.text]
    bm25_index = BM25Index.build([r.text for r in text_rows])
    t_bm25 = time.perf_counter() - t_bm25_start
    print(f"  BM25 built in {t_bm25:.3f}s — {bm25_index.stats()}")

    # Build provider and retrievers
    provider = E5EmbeddingProvider.from_config()
    dense_retriever = DenseRetriever(index=dense_index, provider=provider)
    lexical_retriever = LexicalRetriever(bm25_index=bm25_index)
    hybrid_retriever = HybridRetriever(lexical=lexical_retriever, dense=dense_retriever)

    # Position → review_row_id map (for eval)
    pos_to_row_id = {i: m.review_row_id for i, m in enumerate(dense_index.metadata)}
    # review_row_id → text (for length/language analysis)
    row_id_to_text = {r.review_row_id: r.text for r in text_rows}
    row_id_to_lang = {
        r.review_row_id: (ev.metadata.get("language") or "UNKNOWN")
        for r, ev in zip(text_rows, [evidence_by_row_id[r.review_row_id] for r in text_rows])
    }

    # Methods to benchmark
    METHODS = [
        ("bm25",          "BM25 (no expansion)"),
        ("bm25_expand",   "BM25 + query expansion"),
        ("dense_e5small", "Dense E5-small"),
        ("hybrid",        "Hybrid RRF (BM25 + E5-small)"),
        ("hybrid_expand", "Hybrid RRF + query expansion"),
    ]

    # Results accumulator: method → list of per-query metric dicts
    all_results: dict[str, list[dict]] = {m: [] for m, _ in METHODS}

    print("\nRunning benchmark...")
    for cat_entry in eval_set["categories"]:
        category = cat_entry["category"]
        for q in cat_entry["queries"]:
            query_id = q["query_id"]
            semantic_query = q.get("semantic_query", "") or ""
            structured_filters = q.get("structured_filters", {})
            expected_row_ids = set(q["expected_relevant_review_row_ids"])

            # Apply structured filter to get candidate positions
            evidence_query = EvidenceQuery(
                investigation_id="step4a_benchmark",
                question=q["question"],
                structured_filters=structured_filters,
                semantic_query=semantic_query,
                top_k=10,
                requester_clearance="INTERNAL",
            )
            from evidence import retrieval as ret_mod
            candidate_positions = ret_mod.apply_structured_filters(
                dense_index, evidence_query, "INTERNAL"
            )
            n_candidates = len(candidate_positions)
            n_total = len(dense_index)

            # --- BM25 ---
            t0 = time.perf_counter()
            bm25_scored = bm25_index.query(semantic_query, k=10,
                                            candidate_positions=candidate_positions if candidate_positions else None,
                                            expand=False)
            bm25_lat = (time.perf_counter() - t0) * 1000
            bm25_row_ids = [pos_to_row_id[p] for p, _ in bm25_scored]

            # --- BM25 + expansion ---
            t0 = time.perf_counter()
            bm25_exp_scored = bm25_index.query(semantic_query, k=10,
                                                candidate_positions=candidate_positions if candidate_positions else None,
                                                expand=True)
            bm25_exp_lat = (time.perf_counter() - t0) * 1000
            bm25_exp_row_ids = [pos_to_row_id[p] for p, _ in bm25_exp_scored]

            # --- Dense E5-small ---
            t0 = time.perf_counter()
            dense_scored = dense_retriever.retrieve(semantic_query, k=10,
                                                     candidate_positions=candidate_positions if candidate_positions else None)
            dense_lat = (time.perf_counter() - t0) * 1000
            dense_row_ids = [pos_to_row_id[p] for p, _ in dense_scored]

            # --- Hybrid RRF ---
            t0 = time.perf_counter()
            hybrid_scored = hybrid_retriever.retrieve(semantic_query, k=10,
                                                       candidate_positions=candidate_positions if candidate_positions else None,
                                                       expand_query=False)
            hybrid_lat = (time.perf_counter() - t0) * 1000
            hybrid_row_ids = [pos_to_row_id[p] for p, _ in hybrid_scored]

            # --- Hybrid + expansion ---
            t0 = time.perf_counter()
            hybrid_exp_scored = hybrid_retriever.retrieve(semantic_query, k=10,
                                                           candidate_positions=candidate_positions if candidate_positions else None,
                                                           expand_query=True)
            hybrid_exp_lat = (time.perf_counter() - t0) * 1000
            hybrid_exp_row_ids = [pos_to_row_id[p] for p, _ in hybrid_exp_scored]

            method_results = {
                "bm25":          (bm25_row_ids,     bm25_lat,     bm25_scored),
                "bm25_expand":   (bm25_exp_row_ids, bm25_exp_lat, bm25_exp_scored),
                "dense_e5small": (dense_row_ids,    dense_lat,    dense_scored),
                "hybrid":        (hybrid_row_ids,   hybrid_lat,   hybrid_scored),
                "hybrid_expand": (hybrid_exp_row_ids, hybrid_exp_lat, hybrid_exp_scored),
            }

            for method_key, (row_ids, lat, scored) in method_results.items():
                p5  = precision_at_k(row_ids, expected_row_ids, 5)
                p10 = precision_at_k(row_ids, expected_row_ids, 10)
                r10 = recall_at_k(row_ids, expected_row_ids, 10)
                m   = mrr(row_ids, expected_row_ids)
                best_score = scored[0][1] if scored else 0.0

                all_results[method_key].append({
                    "category": category,
                    "query_id": query_id,
                    "semantic_query": semantic_query,
                    "expected_count": len(expected_row_ids),
                    "candidates_after_filter": n_candidates,
                    "retrieved_count": len(row_ids),
                    "p5": p5,
                    "p10": p10,
                    "recall10": r10,
                    "mrr": m,
                    "best_score": round(float(best_score), 4),
                    "latency_ms": round(lat, 2),
                    "retrieved_row_ids": row_ids,
                    "expected_row_ids": list(expected_row_ids),
                })

    # ── Aggregate metrics ─────────────────────────────────────────────────

    def _mean(rows, key):
        vals = [r[key] for r in rows]
        return round(sum(vals) / len(vals), 4) if vals else 0.0

    summary_table = {}
    for method_key, label in METHODS:
        rows = all_results[method_key]
        summary_table[method_key] = {
            "label": label,
            "mean_p5": _mean(rows, "p5"),
            "mean_p10": _mean(rows, "p10"),
            "mean_recall10": _mean(rows, "recall10"),
            "mean_mrr": _mean(rows, "mrr"),
            "mean_latency_ms": _mean(rows, "latency_ms"),
            "n_queries": len(rows),
        }

    # ── Length analysis ───────────────────────────────────────────────────
    # For each expected review_row_id, bucket by token length and aggregate
    # whether each method actually retrieved it in top-10.

    length_analysis = {}
    for method_key, _ in METHODS:
        bucket_hits: dict[str, list[int]] = {}
        bucket_total: dict[str, int] = {}
        for row in all_results[method_key]:
            expected = row["expected_row_ids"]
            retrieved_set = set(row["retrieved_row_ids"])
            for rid in expected:
                text = row_id_to_text.get(rid, "")
                bucket = length_bucket(text)
                bucket_total[bucket] = bucket_total.get(bucket, 0) + 1
                bucket_hits.setdefault(bucket, []).append(1 if rid in retrieved_set else 0)
        length_analysis[method_key] = {
            b: {
                "total": bucket_total.get(b, 0),
                "recall": round(sum(bucket_hits.get(b, [])) / max(1, bucket_total.get(b, 0)), 4),
            }
            for b in ["1-3_tokens", "4-10_tokens", "11-25_tokens", "25+_tokens"]
        }

    # ── Language analysis ─────────────────────────────────────────────────
    language_analysis = {}
    for method_key, _ in METHODS:
        lang_hits: dict[str, list[int]] = {}
        lang_total: dict[str, int] = {}
        for row in all_results[method_key]:
            expected = row["expected_row_ids"]
            retrieved_set = set(row["retrieved_row_ids"])
            for rid in expected:
                lang = row_id_to_lang.get(rid, "UNKNOWN")
                lang_total[lang] = lang_total.get(lang, 0) + 1
                lang_hits.setdefault(lang, []).append(1 if rid in retrieved_set else 0)
        language_analysis[method_key] = {
            lang: {
                "total": lang_total.get(lang, 0),
                "recall": round(sum(lang_hits.get(lang, [])) / max(1, lang_total.get(lang, 0)), 4),
            }
            for lang in sorted(lang_total)
        }

    # ── Save outputs ──────────────────────────────────────────────────────
    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)

    benchmark_report = {
        "note": "Step 4A multi-method retrieval benchmark over the same eval set as step4_retrieval_eval.py.",
        "bm25_stats": bm25_index.stats(),
        "index_size": len(dense_index),
        "build_time_s": round(t_build, 2),
        "bm25_build_time_s": round(t_bm25, 4),
        "summary_table": summary_table,
        "per_query_results": all_results,
    }

    with open(reports_dir / "step4a_retrieval_benchmark.json", "w") as f:
        json.dump(benchmark_report, f, indent=2, default=str)

    with open(reports_dir / "step4a_length_analysis.json", "w") as f:
        json.dump(length_analysis, f, indent=2)

    with open(reports_dir / "step4a_language_analysis.json", "w") as f:
        json.dump(language_analysis, f, indent=2)

    # ── Print comparison table ─────────────────────────────────────────────
    print()
    print("=" * 85)
    print(f"{'Method':<35} {'P@5':>6} {'P@10':>6} {'R@10':>6} {'MRR':>6} {'Lat(ms)':>9}")
    print("-" * 85)
    for method_key, label in METHODS:
        s = summary_table[method_key]
        print(f"{label:<35} {s['mean_p5']:>6.4f} {s['mean_p10']:>6.4f} "
              f"{s['mean_recall10']:>6.4f} {s['mean_mrr']:>6.4f} {s['mean_latency_ms']:>9.1f}")
    print("=" * 85)

    print()
    print("Length analysis (recall@10 for expected docs, by token bucket):")
    print(f"{'Bucket':<20}", end="")
    for mk, lbl in METHODS:
        print(f"  {mk[:12]:<12}", end="")
    print()
    for bucket in ["1-3_tokens", "4-10_tokens", "11-25_tokens", "25+_tokens"]:
        print(f"{bucket:<20}", end="")
        for mk, _ in METHODS:
            val = length_analysis[mk].get(bucket, {}).get("recall", 0.0)
            n = length_analysis[mk].get(bucket, {}).get("total", 0)
            print(f"  {val:.3f}({n:2d})  ", end="")
        print()

    print()
    print("Language analysis (recall@10, by detected language):")
    for lang in ["PT", "EN", "OTHER", "UNKNOWN"]:
        print(f"  {lang}: ", end="")
        for mk, _ in METHODS:
            val = language_analysis[mk].get(lang, {}).get("recall", 0.0)
            n = language_analysis[mk].get(lang, {}).get("total", 0)
            print(f"{mk}={val:.3f}({n}) ", end="")
        print()

    print()
    print(f"Reports written to:")
    print(f"  {reports_dir / 'step4a_retrieval_benchmark.json'}")
    print(f"  {reports_dir / 'step4a_length_analysis.json'}")
    print(f"  {reports_dir / 'step4a_language_analysis.json'}")


if __name__ == "__main__":
    main()
