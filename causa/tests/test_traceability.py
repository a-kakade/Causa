"""Traceability tests (Step 4 §27/§28).

Reconstructs Evidence ID -> Review ID -> Order ID -> canonical record -> raw
source for a real review, and Evidence ID -> KPI lineage chain for a real
structured evidence object. Also checks the November package build is
reproducible (same evidence_ids, same graph shape) across two independent
runs.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from evidence import structured_adapter as adapter  # noqa: E402

OCT_2017 = ("2017-10-01", "2017-10-31", "2017-10")
NOV_2017 = ("2017-11-01", "2017-11-30", "2017-11")


@pytest.fixture(scope="module")
def registry() -> SemanticRegistry:
    r = SemanticRegistry.load()
    r.validate()
    return r


# ---------------------------------------------------------------------------
# Review evidence -> review_id -> order_id -> canonical row -> raw row
# ---------------------------------------------------------------------------

def test_review_evidence_traces_to_canonical_and_raw_row(review_corpus, review_evidence, canonical, raw):
    picked = next(row for row in review_corpus if row.text)
    ev = next(e for e in review_evidence if e.metadata["review_id"] == picked.review_id
              and e.dimensions["order_id"] == picked.order_id)

    # evidence_id -> review_id / order_id (carried on the evidence object itself)
    review_id = ev.metadata["review_id"]
    order_id = ev.dimensions["order_id"]
    assert review_id == picked.review_id
    assert order_id == picked.order_id

    # review_id/order_id -> canonical fact_reviews.parquet row
    fact_reviews = canonical["fact_reviews"]
    canonical_rows = fact_reviews[(fact_reviews["review_id"] == review_id) & (fact_reviews["order_id"] == order_id)]
    assert len(canonical_rows) >= 1
    canonical_row = canonical_rows.iloc[0]
    assert int(canonical_row["review_score"]) == int(ev.value.value)

    # canonical row -> raw CSV row (data/raw/olist/olist_order_reviews_dataset.csv)
    raw_reviews = raw["order_reviews"]
    raw_rows = raw_reviews[(raw_reviews["review_id"] == review_id) & (raw_reviews["order_id"] == order_id)]
    assert len(raw_rows) >= 1
    assert int(raw_rows.iloc[0]["review_score"]) == int(ev.value.value)

    # lineage on the evidence object points back to exactly this chain
    lineage_refs = " ".join(item["reference"] for item in ev.lineage)
    assert "fact_reviews.parquet" in lineage_refs
    assert "olist_order_reviews_dataset.csv" in lineage_refs


def test_review_evidence_order_id_matches_raw_orders_table(review_evidence, raw):
    ev = next(e for e in review_evidence if e.dimensions.get("customer_state"))
    order_id = ev.dimensions["order_id"]
    raw_orders = raw["orders"]
    assert (raw_orders["order_id"] == order_id).any()


# ---------------------------------------------------------------------------
# Structured evidence -> KPI lineage chain (task §27)
# ---------------------------------------------------------------------------

def test_structured_evidence_traces_to_kpi_lineage_chain(engine, registry):
    from kpi.models import KPIRequest
    result = engine.compute(KPIRequest(kpi_id="revenue", start_date=NOV_2017[0], end_date=NOV_2017[1]))
    ev = adapter.kpi_result_to_evidence(result, registry)
    lineage_chain = registry.get_lineage_chain("revenue")
    assert ev.lineage == lineage_chain
    # the lineage chain itself must ultimately point at a raw table column
    layers = [item["layer"] for item in lineage_chain]
    assert "canonical_table_field" in layers or any("raw" in item["reference"] for item in lineage_chain)


# ---------------------------------------------------------------------------
# Reproducibility (task §28: "the graph.")
# ---------------------------------------------------------------------------

def test_november_revenue_movement_evidence_id_reproducible_across_runs(engine, registry):
    cmp1 = engine.compare_periods("revenue", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
    cmp2 = engine.compare_periods("revenue", NOV_2017[0], NOV_2017[1], OCT_2017[0], OCT_2017[1])
    ev1 = adapter.comparison_result_to_evidence(cmp1, registry)
    ev2 = adapter.comparison_result_to_evidence(cmp2, registry)
    assert ev1.evidence_id == ev2.evidence_id
    assert ev1.value.value == ev2.value.value == pytest.approx(346051.94, abs=0.01)


def test_review_evidence_id_reproducible_across_runs(review_corpus):
    from evidence.review_ingestion import build_review_evidence
    row = next(r for r in review_corpus if r.text)
    ev1 = build_review_evidence(row)
    ev2 = build_review_evidence(row)
    assert ev1.evidence_id == ev2.evidence_id
