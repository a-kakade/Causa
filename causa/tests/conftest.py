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
