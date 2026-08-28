"""Shared pytest fixtures for the Step 2 canonical-layer test suite.

Loads each canonical parquet table and the raw CSVs at most once per test session
(session-scoped fixtures) since some raw tables are large (geolocation ~61MB,
orders ~17MB). Tests must never write to data/raw/ or data/processed/ -- fixtures
here are read-only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lib.raw_loader import load_raw_tables, PROCESSED_DIR  # noqa: E402
from kpi.engine import KPIEngine  # noqa: E402

CANONICAL_TABLES = [
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
]


@pytest.fixture(scope="session")
def canonical():
    missing = [t for t in CANONICAL_TABLES if not (PROCESSED_DIR / f"{t}.parquet").exists()]
    if missing:
        pytest.fail(
            f"Missing canonical table(s): {missing}. Run "
            f"`python scripts/step2_04_build_canonical.py` before running tests."
        )
    return {t: pd.read_parquet(PROCESSED_DIR / f"{t}.parquet") for t in CANONICAL_TABLES}


@pytest.fixture(scope="session")
def raw():
    return load_raw_tables()


@pytest.fixture(scope="session")
def engine() -> KPIEngine:
    """Step 3B: a fresh KPIEngine, shared across the whole test session (its
    internal cache is safe to share since none of these tests mutate canonical
    data)."""
    return KPIEngine()


# ---------------------------------------------------------------------------
# Step 4: Evidence Fabric fixtures
# ---------------------------------------------------------------------------
#
# The review pipeline (language/PII/safety detection + embedding) is real,
# not mocked, but running it over the FULL 99,224-row review corpus takes a
# couple of minutes (mostly langdetect). Test fixtures instead scope the
# pipeline to the October-November 2017 investigation window (~12K review
# rows) -- exactly the scope Step 4's November 2017 evidence package needs
# anyway, and a real, non-synthetic slice of the corpus, just bounded for
# test speed. A production build over the full corpus is what
# scripts/step4_validate_engine.py runs. See docs/EVIDENCE_FABRIC.md.

_EVIDENCE_TEST_MONTHS = ("2017-10", "2017-11")


@pytest.fixture(scope="session")
def review_corpus(canonical):
    """One evidence.review_ingestion.ReviewOrderJoinRow per review in the
    October-November 2017 window, real canonical data."""
    from evidence.review_ingestion import build_review_order_join

    fact_reviews, fact_orders = canonical["fact_reviews"], canonical["fact_orders"]
    merged_months = fact_reviews.merge(
        fact_orders[["order_id", "purchase_timestamp"]], on="order_id", how="left")
    month = merged_months["purchase_timestamp"].dt.strftime("%Y-%m")
    in_window = fact_reviews[month.isin(_EVIDENCE_TEST_MONTHS)].reset_index(drop=True)

    return build_review_order_join(
        in_window, fact_orders, canonical["fact_order_items"], canonical["dim_product"], canonical["dim_seller"],
    )


@pytest.fixture(scope="session")
def review_evidence(review_corpus):
    """CUSTOMER_REVIEW EvidenceObjects for every review in the test window
    (including those with no text -- category/PII/safety fields degrade
    gracefully to their "nothing to detect" defaults for those rows)."""
    from evidence.review_ingestion import build_review_evidence

    return [build_review_evidence(row) for row in review_corpus]


@pytest.fixture(scope="session")
def built_vector_index(review_corpus):
    """A real FlatCosineIndex built from the October-November 2017 review
    text, using the disk embedding cache so repeated test sessions don't
    re-embed from scratch."""
    from evidence.embeddings import EmbeddingCache, embed_reviews_batch
    from evidence.language import detect_language
    from evidence.safety import classify_safety
    from evidence.vector_index import FlatCosineIndex, VectorIndexMetadata

    text_rows = [r for r in review_corpus if r.text]
    cache = EmbeddingCache()
    vectors = embed_reviews_batch([r.text for r in text_rows], cache)
    cache.save()

    metadata = [
        VectorIndexMetadata(
            review_row_id=r.review_row_id, review_id=r.review_id, order_id=r.order_id, month=r.month,
            category=r.category, seller=r.seller, customer_state=r.customer_state, seller_state=r.seller_state,
            review_score=r.review_score, language=detect_language(r.text).language,
            security_status=classify_safety(r.text).security_status,
        )
        for r in text_rows
    ]
    index = FlatCosineIndex.build(vectors, metadata)
    return index, text_rows, cache
