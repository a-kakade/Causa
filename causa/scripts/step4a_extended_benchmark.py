"""
step4a_extended_benchmark.py — Step 4A extended evaluation with HF auth.

This script runs the evaluations that were blocked by the expired HF token:

  1. E5-base model comparison vs. E5-small and BM25
  2. E5-large model comparison (if memory allows)
  3. Cross-encoder reranker on top of BM25+expansion candidates
  4. Cross-encoder reranker on top of Hybrid RRF candidates

Models evaluated:
  - intfloat/multilingual-e5-base   (~278M params, 768-dim)
  - intfloat/multilingual-e5-large  (~560M params, 1024-dim) — optional
  - amberoad/bert-multilingual-passage-reranking-msmarco (cross-encoder)

The HF_TOKEN environment variable must be set before running:

    export HF_TOKEN=hf_...
    .venv/bin/python scripts/step4a_extended_benchmark.py

All results are appended to (or create):
    reports/step4a_extended_benchmark.json
    reports/step4a_model_comparison.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

HF_TOKEN = os.environ.get("HF_TOKEN", "")

from lib.raw_loader import PROCESSED_DIR  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402
from evidence import retrieval as retrieval_module, structured_adapter as adapter  # noqa: E402
from evidence.bm25_retriever import BM25Index  # noqa: E402
from evidence.dense_retriever import DenseRetriever, E5EmbeddingProvider  # noqa: E402
from evidence.engine import build_review_index  # noqa: E402
from evidence.hybrid_retriever import HybridRetriever, LexicalRetriever  # noqa: E402
from evidence.schema import EvidenceQuery  # noqa: E402

CANONICAL_TABLES = [
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
]
EVAL_SET_PATH = REPO_ROOT / "data" / "evidence" / "eval" / "retrieval_eval_set.json"


# ── Metrics (same as step4a_retrieval_benchmark.py) ─────────────────────

def precision_at_k(retrieved, relevant, k):
    top = retrieved[:k]
    return sum(1 for r in top if r in relevant) / len(top) if top else 0.0

def recall_at_k(retrieved, relevant, k):
    if not relevant: return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)

def mrr(retrieved, relevant):
    for rank, r in enumerate(retrieved, start=1):
        if r in relevant:
            return 1.0 / rank
    return 0.0

def compute_metrics(row_ids, expected_set):
    return {
        "p5":  precision_at_k(row_ids, expected_set, 5),
        "p10": precision_at_k(row_ids, expected_set, 10),
        "r10": recall_at_k(row_ids, expected_set, 10),
        "mrr": mrr(row_ids, expected_set),
    }

def mean_metrics(rows):
    keys = ["p5", "p10", "r10", "mrr", "latency_ms"]
    return {k: round(sum(r[k] for r in rows) / len(rows), 4) for k in keys if rows}


# ── Cross-encoder reranker ───────────────────────────────────────────────

class CrossEncoderReranker:
    """Reranks BM25 or Hybrid candidates using a multilingual cross-encoder.

    Takes (query, [passage_texts]) pairs and returns re-scored rankings.
    Model is downloaded lazily and cached in HF local cache.
    """

    def __init__(self, model_name: str, max_length: int = 256):
        self.model_name = model_name
        self.max_length = max_length
        self._model = None

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder(
                self.model_name,
                max_length=self.max_length,
                token=HF_TOKEN or None,
            )
        return self._model

    def rerank(
        self,
        query: str,
        candidates: list[tuple[int, float]],  # [(doc_idx, score), ...]
        texts: list[str],  # indexed by doc_idx
    ) -> list[tuple[int, float]]:
        """Re-score candidates and return sorted by cross-encoder score."""
        if not candidates:
            return []
        model = self._get_model()
        pairs = [(query, texts[doc_idx]) for doc_idx, _ in candidates]
        scores = model.predict(pairs)
        # Some cross-encoders (e.g. amberoad/bert-multilingual-passage-
        # reranking-msmarco) are 2-class classifiers that return
        # (n, 2) logits [not_relevant, relevant] instead of a single
        # relevance scalar. Reduce to a 1-D relevance score via softmax
        # over the "relevant" class (index 1) so downstream sorting works
        # the same way for both scalar and classification-style rerankers.
        if scores.ndim == 2:
            exp = np.exp(scores - scores.max(axis=1, keepdims=True))
            probs = exp / exp.sum(axis=1, keepdims=True)
            scores = probs[:, 1]
        reranked = sorted(
            zip([doc_idx for doc_idx, _ in candidates], scores.tolist()),
            key=lambda p: -p[1],
        )
        return reranked

    @property
    def method_name(self) -> str:
        short = self.model_name.split("/")[-1]
        return f"cross_encoder_{short}"


# ── Main ────────────────────────────────────────────────────────────────

def main():
    if not HF_TOKEN:
        print("ERROR: HF_TOKEN environment variable not set.")
        sys.exit(1)

    print(f"HF_TOKEN: {HF_TOKEN[:8]}...{HF_TOKEN[-4:]}")

    print("\nLoading eval set...")
    with open(EVAL_SET_PATH) as f:
        eval_set = json.load(f)

    print("Loading canonical tables...")
    canonical = {t: pd.read_parquet(PROCESSED_DIR / f"{t}.parquet") for t in CANONICAL_TABLES}
    registry = SemanticRegistry.load()
    registry.validate()

    print("Building review index (uses embedding cache)...")
    t0 = time.perf_counter()
    review_corpus, review_evidence, evidence_by_row_id, dense_index, cache = build_review_index(canonical)
    t_build = time.perf_counter() - t0
    print(f"  Dense index built in {t_build:.1f}s — {len(dense_index)} vectors")

    text_rows = [r for r in review_corpus if r.text]
    corpus_texts = [r.text for r in text_rows]

    print("Building BM25 index...")
    bm25_index = BM25Index.build(corpus_texts)
    print(f"  BM25: {bm25_index.stats()}")

    # Base retriever setup
    e5_small_provider = E5EmbeddingProvider.from_config()
    dense_small = DenseRetriever(index=dense_index, provider=e5_small_provider)
    lexical = LexicalRetriever(bm25_index=bm25_index)
    hybrid = HybridRetriever(lexical=lexical, dense=dense_small)

    pos_to_row_id = {i: m.review_row_id for i, m in enumerate(dense_index.metadata)}

    # ── Step 1: Try cross-encoder models ─────────────────────────────────
    ce_candidates = [
        "amberoad/bert-multilingual-passage-reranking-msmarco",
        "cross-encoder/ms-marco-MiniLM-L-6-v2",
        "cross-encoder/ms-marco-MiniLM-L-12-v2",
    ]
    available_ce = []
    print("\nProbing cross-encoder models...")
    for model_id in ce_candidates:
        try:
            from sentence_transformers import CrossEncoder
            m = CrossEncoder(model_id, max_length=128, token=HF_TOKEN or None)
            # Quick test
            score = m.predict([("test query", "test passage")])
            print(f"  ✅ {model_id}")
            available_ce.append(model_id)
            del m
        except Exception as e:
            print(f"  ❌ {model_id}: {e}")

    # ── Step 2: E5 model comparison ───────────────────────────────────────
    e5_models = [
        ("intfloat/multilingual-e5-small", 384, "E5-small (117M)"),
        ("intfloat/multilingual-e5-base", 768, "E5-base (~278M)"),
    ]
    # E5-large is very large (~560M). Attempt it but skip if OOM.
    try:
        import torch
        if torch.cuda.is_available() or True:  # try on CPU
            e5_models.append(("intfloat/multilingual-e5-large", 1024, "E5-large (~560M)"))
    except ImportError:
        pass

    all_results = {}

    for model_id, dim, label in e5_models:
        print(f"\nEvaluating {label}...")
        try:
            provider = E5EmbeddingProvider(
                model_name=model_id,
                dimension=dim,
                query_prefix="query: ",
                passage_prefix="passage: ",
            )
            # Test embed speed
            t0 = time.perf_counter()
            _ = provider.embed_query("atraso na entrega, demora")
            t_embed = (time.perf_counter() - t0) * 1000

            # Re-embed all 5019 passages (or use existing cache for small)
            print(f"  Embedding {len(corpus_texts)} passages with {label}...")
            t_batch = time.perf_counter()
            passage_vecs = provider.embed_passages_batch(corpus_texts, batch_size=64)
            t_batch = time.perf_counter() - t_batch
            print(f"  Batch embed done in {t_batch:.1f}s")

            # Build a temporary FlatCosineIndex for this model
            from evidence.vector_index import FlatCosineIndex
            temp_meta = dense_index.metadata  # same metadata order
            temp_index = FlatCosineIndex.__new__(FlatCosineIndex)
            temp_index.vectors = passage_vecs
            temp_index.metadata = temp_meta
            # Ensure L2-normalized (embed_passages_batch already normalizes)
            norms = np.linalg.norm(passage_vecs, axis=1, keepdims=True)
            temp_index.vectors = passage_vecs / np.maximum(norms, 1e-8)

            temp_dense = DenseRetriever(index=temp_index, provider=provider)

            method_key = f"dense_{model_id.split('/')[-1]}"
            method_rows = []

            for cat_entry in eval_set["categories"]:
                for q in cat_entry["queries"]:
                    semantic_query = q.get("semantic_query", "") or ""
                    expected_set = set(q["expected_relevant_review_row_ids"])

                    evidence_query = EvidenceQuery(
                        investigation_id="step4a_extended",
                        question=q["question"],
                        structured_filters=q.get("structured_filters", {}),
                        semantic_query=semantic_query,
                        top_k=10,
                        requester_clearance="INTERNAL",
                    )
                    candidate_positions = retrieval_module.apply_structured_filters(
                        dense_index, evidence_query, "INTERNAL"
                    )

                    t_q = time.perf_counter()
                    scored = temp_dense.retrieve(
                        semantic_query, k=10,
                        candidate_positions=candidate_positions or None,
                    )
                    lat = (time.perf_counter() - t_q) * 1000
                    row_ids = [pos_to_row_id[p] for p, _ in scored]

                    m = compute_metrics(row_ids, expected_set)
                    method_rows.append({**m, "latency_ms": round(lat, 2)})

            summary = mean_metrics(method_rows)
            all_results[method_key] = {"label": label, **summary}
            print(f"  {label}: P@5={summary['p5']:.4f} P@10={summary['p10']:.4f} "
                  f"MRR={summary['mrr']:.4f} lat={summary['latency_ms']:.1f}ms")
            del temp_index, temp_dense, passage_vecs

        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()
            all_results[f"dense_{model_id.split('/')[-1]}"] = {
                "label": label, "error": str(e),
                "p5": None, "p10": None, "r10": None, "mrr": None, "latency_ms": None,
            }

    # ── Step 3: Cross-encoder reranking ──────────────────────────────────
    # Rerank BM25+expansion top-50 candidates using the best available CE
    for ce_model_id in available_ce[:1]:  # use first available
        print(f"\nCross-encoder reranking with {ce_model_id}...")
        try:
            reranker = CrossEncoderReranker(ce_model_id, max_length=256)
            # Warm up
            _ = reranker._get_model()
            print(f"  Model loaded.")

            # BM25-expand candidates → CE reranked top-10
            method_key_bm25_ce = f"bm25_expand+ce"
            method_key_hybrid_ce = f"hybrid+ce"
            rows_bm25_ce = []
            rows_hybrid_ce = []

            for cat_entry in eval_set["categories"]:
                for q in cat_entry["queries"]:
                    semantic_query = q.get("semantic_query", "") or ""
                    expected_set = set(q["expected_relevant_review_row_ids"])

                    evidence_query = EvidenceQuery(
                        investigation_id="step4a_extended",
                        question=q["question"],
                        structured_filters=q.get("structured_filters", {}),
                        semantic_query=semantic_query,
                        top_k=10,
                        requester_clearance="INTERNAL",
                    )
                    candidate_positions = retrieval_module.apply_structured_filters(
                        dense_index, evidence_query, "INTERNAL"
                    )

                    # BM25+expand → top-50 → CE reranker → top-10
                    pool = bm25_index.query(semantic_query, k=50,
                                            candidate_positions=candidate_positions or None,
                                            expand=True)
                    t0 = time.perf_counter()
                    reranked_bm25 = reranker.rerank(semantic_query, pool, corpus_texts)[:10]
                    lat_bm25 = (time.perf_counter() - t0) * 1000
                    row_ids_bm25 = [pos_to_row_id[p] for p, _ in reranked_bm25]
                    m1 = compute_metrics(row_ids_bm25, expected_set)
                    rows_bm25_ce.append({**m1, "latency_ms": round(lat_bm25, 2)})

                    # Hybrid RRF → top-50 → CE reranker → top-10
                    hybrid_pool = hybrid.retrieve(semantic_query, k=50,
                                                  candidate_positions=candidate_positions or None,
                                                  expand_query=True)
                    t0 = time.perf_counter()
                    reranked_hybrid = reranker.rerank(semantic_query, hybrid_pool, corpus_texts)[:10]
                    lat_hybrid = (time.perf_counter() - t0) * 1000
                    row_ids_hybrid = [pos_to_row_id[p] for p, _ in reranked_hybrid]
                    m2 = compute_metrics(row_ids_hybrid, expected_set)
                    rows_hybrid_ce.append({**m2, "latency_ms": round(lat_hybrid, 2)})

            s1 = mean_metrics(rows_bm25_ce)
            s2 = mean_metrics(rows_hybrid_ce)
            all_results[method_key_bm25_ce] = {
                "label": f"BM25+expand → CE ({ce_model_id.split('/')[-1]})",
                **s1,
            }
            all_results[method_key_hybrid_ce] = {
                "label": f"Hybrid RRF+expand → CE ({ce_model_id.split('/')[-1]})",
                **s2,
            }
            print(f"  BM25+expand→CE: P@5={s1['p5']:.4f} MRR={s1['mrr']:.4f}")
            print(f"  Hybrid+CE:      P@5={s2['p5']:.4f} MRR={s2['mrr']:.4f}")

        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback; traceback.print_exc()

    # ── Print final comparison ────────────────────────────────────────────
    # Reference values from step4a_retrieval_benchmark.py
    reference = {
        "bm25_expand":   {"label": "BM25+expansion (Step 4A)",   "p5": 0.1333, "p10": 0.0833, "r10": 0.1486, "mrr": 0.3889, "latency_ms": 1.0},
        "dense_e5_small": {"label": "Dense E5-small (Step 4A)",   "p5": 0.0000, "p10": 0.0000, "r10": 0.0000, "mrr": 0.0000, "latency_ms": 1284.0},
    }

    print()
    print("=" * 100)
    print(f"{'Method':<50} {'P@5':>6} {'P@10':>6} {'R@10':>6} {'MRR':>6} {'Lat(ms)':>9}")
    print("-" * 100)
    for k, s in reference.items():
        p5 = s.get("p5", 0.0) or 0.0
        p10 = s.get("p10", 0.0) or 0.0
        r10 = s.get("r10", 0.0) or 0.0
        mrr_v = s.get("mrr", 0.0) or 0.0
        lat = s.get("latency_ms", 0.0) or 0.0
        print(f"  {s['label']:<48} {p5:>6.4f} {p10:>6.4f} {r10:>6.4f} {mrr_v:>6.4f} {lat:>9.1f}")
    print("  ---")
    for k, s in all_results.items():
        if "error" in s:
            print(f"  {s.get('label', k):<48}  FAILED: {s['error']}")
            continue
        p5 = s.get("p5", 0.0) or 0.0
        p10 = s.get("p10", 0.0) or 0.0
        r10 = s.get("r10", 0.0) or 0.0
        mrr_v = s.get("mrr", 0.0) or 0.0
        lat = s.get("latency_ms", 0.0) or 0.0
        print(f"  {s.get('label', k):<48} {p5:>6.4f} {p10:>6.4f} {r10:>6.4f} {mrr_v:>6.4f} {lat:>9.1f}")
    print("=" * 100)

    # ── Save ─────────────────────────────────────────────────────────────
    reports_dir = REPO_ROOT / "reports"
    reports_dir.mkdir(exist_ok=True)
    report = {
        "note": "Step 4A extended benchmark — E5 model comparison + cross-encoder reranking. HF auth required.",
        "available_cross_encoders": available_ce,
        "results": all_results,
    }
    out_path = reports_dir / "step4a_extended_benchmark.json"
    with open(out_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReport written to: {out_path}")


if __name__ == "__main__":
    main()
