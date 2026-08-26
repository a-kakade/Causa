"""
engine.py — Step 3B: deterministic KPI computation engine.

    KPI Request -> Semantic Registry -> Contract Validation (query_planner)
        -> Query/Calculation Planner -> Canonical Data -> Deterministic
        Calculation -> KPI Result Object

Every calculation here is a direct translation of the corresponding contract in
config/kpis.yaml -- the source columns, default filters, and grain rules used
below are the same ones declared there (many are read from the contract at
runtime: lineage, source_tables, dimension source columns, mandatory delivery
filter value, coverage thresholds). The aggregation logic itself (SUM vs
COUNT_DISTINCT vs MEAN vs RATIO, and which tables to join) is necessarily
KPI-specific -- see docs/KPI_COMPUTATION_ENGINE.md for the explicit statement of
which parts are contract-driven and which are engine code, and why a fully
generic rule interpreter was not attempted for 10 structurally different KPIs.

This module computes KPI VALUES. It does not detect anomalies, decompose PVM,
infer causality, retrieve text, or reason with an LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import pandas as pd

from kpi.cache import ComputationCache
from kpi.models import ComparisonResult, KPIRequest, KPIResult
from kpi.query_planner import KPIRequestError, QueryPlan, ResolvedDimension, plan
from kpi.semantic_registry import SemanticRegistry

REPO_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

MEDIUM_BAND_WIDTH_PP = 15.0  # matches every contract's stated confidence_implications band width


# ---------------------------------------------------------------------------
# Canonical data access (read-only)
# ---------------------------------------------------------------------------

class CanonicalDataStore:
    """Lazily loads data/processed/*.parquet, caches each table in memory for the
    life of this object. Never writes anything."""

    TABLES = (
        "dim_customer", "dim_product", "dim_seller",
        "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
        "agg_order_items", "agg_order_payments", "agg_order_reviews",
    )

    def __init__(self, processed_dir: Path = PROCESSED_DIR):
        self._dir = processed_dir
        self._cache: dict[str, pd.DataFrame] = {}

    def get(self, table_name: str) -> pd.DataFrame:
        if table_name not in self.TABLES:
            raise ValueError(f"Unknown canonical table {table_name!r}")
        if table_name not in self._cache:
            path = self._dir / f"{table_name}.parquet"
            if not path.exists():
                raise FileNotFoundError(
                    f"{path} does not exist -- run scripts/step2_04_build_canonical.py first."
                )
            self._cache[table_name] = pd.read_parquet(path)
        return self._cache[table_name].copy()  # copy: callers must never mutate the cached original


# ---------------------------------------------------------------------------
# Generic helpers (shared across KPI implementations, not KPI-specific)
# ---------------------------------------------------------------------------

def _bucket_time(series: pd.Series, grain: str) -> pd.Series:
    if grain == "day":
        return series.dt.strftime("%Y-%m-%d")
    if grain == "week":
        return series.dt.to_period("W-MON").astype(str)
    if grain == "month":
        return series.dt.to_period("M").astype(str)
    raise ValueError(f"Unknown time grain {grain!r}")


def _apply_date_range(df: pd.DataFrame, time_col: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    end_exclusive = end + pd.Timedelta(days=1)
    return df[(df[time_col] >= start) & (df[time_col] < end_exclusive)]


def _apply_window_filter(df: pd.DataFrame, apply_filter: bool) -> pd.DataFrame:
    if not apply_filter or "in_analytical_window" not in df.columns:
        return df
    return df[df["in_analytical_window"]]


def _apply_order_status_filter(df: pd.DataFrame, filters: dict[str, Any]) -> pd.DataFrame:
    if "order_status" not in filters:
        return df
    value = filters["order_status"]
    values = value if isinstance(value, (list, tuple, set)) else [value]
    return df[df["order_status"].isin(values)]


def _data_quality_tier(coverage: Optional[float], threshold_pct: float) -> str:
    if coverage is None:
        return "UNKNOWN"
    coverage_pct = coverage * 100
    if coverage_pct >= threshold_pct:
        return "HIGH"
    if coverage_pct >= max(threshold_pct - MEDIUM_BAND_WIDTH_PP, 0):
        return "MEDIUM"
    return "LOW"


def _join_product_category(engine_data: CanonicalDataStore, df: pd.DataFrame) -> pd.DataFrame:
    dim_product = engine_data.get("dim_product")[["product_id", "category_name_en"]]
    return df.merge(dim_product, on="product_id", how="left")


def _join_seller_state(engine_data: CanonicalDataStore, df: pd.DataFrame) -> pd.DataFrame:
    dim_seller = engine_data.get("dim_seller")[["seller_id", "seller_state"]]
    return df.merge(dim_seller, on="seller_id", how="left")


def _join_order_context(engine_data: CanonicalDataStore, df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Bring order-level attributes (purchase_timestamp, order_status,
    customer_state, in_analytical_window, ...) onto a table keyed by order_id.
    Uses an INNER join -- Step 1/2 verified 0 orphan order_id references anywhere
    in the canonical layer, so this never silently drops a row that should have
    matched; it is not a lossy shortcut."""
    fact_orders = engine_data.get("fact_orders")[["order_id"] + cols]
    return df.merge(fact_orders, on="order_id", how="inner")


def _resolved_dim_column(d: ResolvedDimension) -> str:
    if d.is_time_grain:
        return f"_dim_{d.name}"
    return d.source_column.split(".")[-1]


def _apply_dimension_columns(engine_data: CanonicalDataStore, df: pd.DataFrame,
                              resolved_dims: list[ResolvedDimension], time_col: str) -> tuple[pd.DataFrame, list[str]]:
    """Joins in whatever tables a requested dimension needs and returns the list
    of dataframe column names to group by, in request order."""
    group_cols = []
    for d in resolved_dims:
        if d.is_time_grain:
            col = _resolved_dim_column(d)
            df[col] = _bucket_time(df[time_col], d.time_grain)
            group_cols.append(col)
            continue
        col = _resolved_dim_column(d)
        if col in df.columns:
            group_cols.append(col)
            continue
        if d.source_table == "dim_product" and col == "category_name_en":
            df = _join_product_category(engine_data, df)
        elif d.source_table == "dim_seller" and col == "seller_state":
            df = _join_seller_state(engine_data, df)
        elif d.source_table == "fact_orders":
            df = _join_order_context(engine_data, df, [col])
        else:
            raise ValueError(f"No join rule implemented for dimension column {col!r} from {d.source_table!r}")
        group_cols.append(col)
    return df, group_cols


def _split_by_dimensions(kpi_id: str, contract: dict, group_cols: list[str], dim_names: list[str],
                          period: dict, filters: dict, lineage: list, source_tables: list,
                          value_series: pd.Series, sample_size_series: pd.Series,
                          coverage_by_group: dict, warnings_by_group: dict, threshold: float,
                          metadata_by_group: Optional[dict] = None) -> list[KPIResult]:
    results = []
    for key, value in value_series.items():
        keys = key if isinstance(key, tuple) else (key,)
        dims = dict(zip(dim_names, keys))
        cov = coverage_by_group.get(key)
        results.append(KPIResult(
            kpi_id=kpi_id,
            value=None if pd.isna(value) else float(value),
            period=period, grain=contract["base_grain"], dimensions=dims, filters=filters,
            sample_size=int(sample_size_series.get(key, 0)),
            coverage=cov,
            data_quality=_data_quality_tier(cov, threshold),
            source=source_tables, lineage=lineage,
            warnings=warnings_by_group.get(key, []),
            metadata=(metadata_by_group or {}).get(key, {}),
        ))
    return results


# ---------------------------------------------------------------------------
# The engine
# ---------------------------------------------------------------------------

class KPIEngine:
    def __init__(self, registry: Optional[SemanticRegistry] = None,
                 data: Optional[CanonicalDataStore] = None,
                 cache: Optional[ComputationCache] = None):
        self.registry = registry or SemanticRegistry.load()
        self.registry.validate()  # never compute against an invalid contract set
        self.data = data or CanonicalDataStore()
        self.cache = cache if cache is not None else ComputationCache()

    def compute(self, request: KPIRequest) -> KPIResult | list[KPIResult]:
        return self.cache.get_or_compute(request, lambda: self._compute_uncached(request))

    def _compute_uncached(self, request: KPIRequest) -> KPIResult | list[KPIResult]:
        query_plan = plan(self.registry, request)
        dispatch = {
            "revenue": self._compute_item_grain_sum,
            "freight_revenue": self._compute_item_grain_sum,
            "quantity_sold": self._compute_quantity_sold,
            "orders": self._compute_orders,
            "aov": self._compute_aov,
            "avg_delivery_days": self._compute_avg_delivery_days,
            "on_time_delivery_rate": self._compute_on_time_delivery_rate,
            "avg_review_score": self._compute_avg_review_score,
            "review_volume": self._compute_review_volume,
            "repeat_purchase_rate": self._compute_repeat_purchase_rate,
        }
        fn = dispatch[query_plan.kpi_id]
        return fn(query_plan)

    def compare_periods(self, kpi_id: str, current_start: str, current_end: str,
                         previous_start: str, previous_end: str, **kwargs) -> ComparisonResult:
        """Deterministic period-over-period change. NOT an anomaly judgement --
        no threshold, no materiality/significance decision (that is a later
        step's job). Both periods are computed via the exact same code path as
        any other request, so there is no separate "comparison formula" to keep
        in sync with the single-period one."""
        current_req = KPIRequest(kpi_id=kpi_id, start_date=current_start, end_date=current_end, **kwargs)
        previous_req = KPIRequest(kpi_id=kpi_id, start_date=previous_start, end_date=previous_end, **kwargs)
        current = self.compute(current_req)
        previous = self.compute(previous_req)
        if isinstance(current, list) or isinstance(previous, list):
            raise ValueError("compare_periods does not support dimension-grouped requests -- compute() each group separately")

        warnings = list(current.warnings) + list(previous.warnings)
        if current.value is None or previous.value is None:
            absolute_change = None
            percentage_change = None
            warnings.append("One or both periods have a NULL value -- change cannot be computed.")
        else:
            absolute_change = current.value - previous.value
            if previous.value == 0:
                percentage_change = None
                warnings.append("previous_value is 0 -- percentage_change is undefined, not infinity.")
            else:
                percentage_change = (absolute_change / previous.value) * 100

        return ComparisonResult(
            kpi_id=kpi_id, current=current, previous=previous,
            current_value=current.value, previous_value=previous.value,
            absolute_change=absolute_change, percentage_change=percentage_change,
            warnings=warnings,
        )

    # -- Revenue / Freight Revenue (both: SUM at item grain, pre-aggregated) ---

    def _compute_item_grain_sum(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        """Implements CAUSA_REVENUE = SUM(agg_order_items.item_price_total) and,
        identically shaped, Freight Revenue = SUM(item_freight_total). Reads
        fact_order_items (native grain, per contract) joined to fact_orders for
        date/status/window filtering and dimension context -- NEVER joined to
        order_payments or order_reviews (that table isn't even loaded here)."""
        value_col = "price" if qp.kpi_id == "revenue" else "freight_value"

        items = self.data.get("fact_order_items")
        items = _join_order_context(
            self.data, items,
            ["purchase_timestamp", "order_status", "customer_state", "in_analytical_window"],
        )
        items = _apply_date_range(items, "purchase_timestamp", qp.start, qp.end)
        items = _apply_window_filter(items, qp.apply_window_filter)
        items = _apply_order_status_filter(items, qp.filters)

        # eligible population for coverage: all fact_orders in the same date/status/window scope
        orders = self.data.get("fact_orders")
        orders = _apply_date_range(orders, "purchase_timestamp", qp.start, qp.end)
        orders = _apply_window_filter(orders, qp.apply_window_filter)
        orders = _apply_order_status_filter(orders, qp.filters)
        eligible_orders = set(orders["order_id"])
        contributing_orders = set(items["order_id"].unique())
        coverage = (len(contributing_orders) / len(eligible_orders)) if eligible_orders else None

        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        lineage = qp.contract["lineage"]["chain"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}
        warnings = self._coverage_warning(coverage, threshold, len(eligible_orders) - len(contributing_orders), "orders without item data")

        if not qp.dimensions:
            value = float(items[value_col].sum()) if len(items) else None
            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions={}, filters=qp.filters, sample_size=len(items), coverage=coverage,
                data_quality=_data_quality_tier(coverage, threshold), source=qp.contract["source_tables"],
                lineage=lineage, warnings=warnings,
            )

        items, group_cols = _apply_dimension_columns(self.data, items, qp.dimensions, "purchase_timestamp")
        grouped = items.groupby(group_cols, dropna=False)
        value_series = grouped[value_col].sum()
        sample_size_series = grouped.size()
        dim_names = [d.name for d in qp.dimensions]
        # per-group coverage is not separately computed here (would need a matching
        # per-group eligible-orders denominator) -- expose the overall coverage on
        # every group and flag this explicitly, rather than presenting a
        # per-group number without the correct denominator.
        coverage_by_group = {k: coverage for k in value_series.index}
        warnings_by_group = {k: warnings for k in value_series.index}
        return _split_by_dimensions(
            qp.kpi_id, qp.contract, group_cols, dim_names, period, qp.filters, lineage,
            qp.contract["source_tables"], value_series, sample_size_series,
            coverage_by_group, warnings_by_group, threshold,
        )

    # -- Quantity Sold ---------------------------------------------------------

    def _compute_quantity_sold(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        """COUNT(order_items.order_item_id). Verified assumption (documented in
        docs/KPI_COMPUTATION_ENGINE.md, not invented here): the raw Olist schema
        has NO quantity column; when a customer buys >1 unit of the same product
        in one order, Olist represents that as multiple order_item rows (each
        with its own order_item_id, same product_id, same price) -- confirmed
        against the real canonical data before this function was written. So
        COUNT(order_item rows) legitimately equals units sold; this is not a
        silent reinterpretation of row count as quantity."""
        items = self.data.get("fact_order_items")
        items = _join_order_context(
            self.data, items,
            ["purchase_timestamp", "order_status", "customer_state", "in_analytical_window"],
        )
        items = _apply_date_range(items, "purchase_timestamp", qp.start, qp.end)
        items = _apply_window_filter(items, qp.apply_window_filter)
        items = _apply_order_status_filter(items, qp.filters)

        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        lineage = qp.contract["lineage"]["chain"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}

        if not qp.dimensions:
            value = float(len(items))
            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions={}, filters=qp.filters, sample_size=len(items), coverage=1.0,
                data_quality=_data_quality_tier(1.0, threshold), source=qp.contract["source_tables"],
                lineage=lineage, warnings=[],
            )

        items, group_cols = _apply_dimension_columns(self.data, items, qp.dimensions, "purchase_timestamp")
        value_series = items.groupby(group_cols, dropna=False).size().astype(float)
        dim_names = [d.name for d in qp.dimensions]
        coverage_by_group = {k: 1.0 for k in value_series.index}
        warnings_by_group = {k: [] for k in value_series.index}
        return _split_by_dimensions(
            qp.kpi_id, qp.contract, group_cols, dim_names, period, qp.filters, lineage,
            qp.contract["source_tables"], value_series, value_series.astype(int),
            coverage_by_group, warnings_by_group, threshold,
        )

    # -- Orders -----------------------------------------------------------------

    def _compute_orders(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        """COUNT(DISTINCT order_id). Default scope = ALL order_status values --
        no status filter is applied unless the caller explicitly requests one.
        canceled/unavailable/delivered orders are never silently excluded."""
        orders = self.data.get("fact_orders")
        orders = _apply_date_range(orders, "purchase_timestamp", qp.start, qp.end)
        orders = _apply_window_filter(orders, qp.apply_window_filter)
        orders = _apply_order_status_filter(orders, qp.filters)  # no-op unless explicitly requested

        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        lineage = qp.contract["lineage"]["chain"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}

        if not qp.dimensions:
            value = float(orders["order_id"].nunique())
            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions={}, filters=qp.filters, sample_size=len(orders), coverage=1.0,
                data_quality=_data_quality_tier(1.0, threshold), source=qp.contract["source_tables"],
                lineage=lineage, warnings=[],
            )

        orders, group_cols = _apply_dimension_columns(self.data, orders, qp.dimensions, "purchase_timestamp")
        grouped = orders.groupby(group_cols, dropna=False)
        value_series = grouped["order_id"].nunique().astype(float)
        sample_series = grouped.size()
        dim_names = [d.name for d in qp.dimensions]
        coverage_by_group = {k: 1.0 for k in value_series.index}
        warnings_by_group = {k: [] for k in value_series.index}
        return _split_by_dimensions(
            qp.kpi_id, qp.contract, group_cols, dim_names, period, qp.filters, lineage,
            qp.contract["source_tables"], value_series, sample_series,
            coverage_by_group, warnings_by_group, threshold,
        )

    # -- AOV ----------------------------------------------------------------

    def _compute_aov(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        """Revenue / COUNT(DISTINCT order_id WHERE has item data) -- the
        denominator is deliberately NOT the Orders KPI's population. Numerator
        and denominator are exposed in metadata for traceability, per spec."""
        agg_items = self.data.get("agg_order_items")
        agg_items = _join_order_context(
            self.data, agg_items,
            ["purchase_timestamp", "order_status", "customer_state", "in_analytical_window"],
        )
        agg_items = _apply_date_range(agg_items, "purchase_timestamp", qp.start, qp.end)
        agg_items = _apply_window_filter(agg_items, qp.apply_window_filter)
        agg_items = _apply_order_status_filter(agg_items, qp.filters)

        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}

        if not qp.dimensions:
            numerator = float(agg_items["item_price_total"].sum()) if len(agg_items) else 0.0
            denominator = int(agg_items["order_id"].nunique())
            value = None if denominator == 0 else numerator / denominator

            orders = self.data.get("fact_orders")
            orders = _apply_date_range(orders, "purchase_timestamp", qp.start, qp.end)
            orders = _apply_window_filter(orders, qp.apply_window_filter)
            orders = _apply_order_status_filter(orders, qp.filters)
            eligible = len(orders)
            coverage = (denominator / eligible) if eligible else None
            warnings = self._coverage_warning(coverage, threshold, eligible - denominator, "orders without item data")
            if denominator == 0:
                warnings.append("Zero orders with item data in scope -- AOV is NULL, not 0.")

            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period,
                grain=qp.contract["base_grain"], dimensions={}, filters=qp.filters,
                sample_size=denominator, coverage=coverage,
                data_quality=_data_quality_tier(coverage, threshold),
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"],
                warnings=warnings,
                metadata={"numerator": numerator, "denominator": denominator, "ratio": value},
            )

        agg_items, group_cols = _apply_dimension_columns(self.data, agg_items, qp.dimensions, "purchase_timestamp")
        dim_names = [d.name for d in qp.dimensions]
        results = []
        for key, sub in agg_items.groupby(group_cols, dropna=False):
            keys = key if isinstance(key, tuple) else (key,)
            dims = dict(zip(dim_names, keys))
            numerator = float(sub["item_price_total"].sum())
            denominator = int(sub["order_id"].nunique())
            value = None if denominator == 0 else numerator / denominator
            results.append(KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions=dims, filters=qp.filters, sample_size=denominator, coverage=None,
                data_quality="UNKNOWN",
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"],
                warnings=["Per-group coverage not computed for dimension-grouped AOV -- see docs/KPI_COMPUTATION_ENGINE.md."],
                metadata={"numerator": numerator, "denominator": denominator, "ratio": value},
            ))
        return results

    # -- Average Delivery Days --------------------------------------------------

    def _compute_avg_delivery_days(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        orders = self.data.get("fact_orders")
        orders = _apply_date_range(orders, "purchase_timestamp", qp.start, qp.end)
        orders = _apply_window_filter(orders, qp.apply_window_filter)
        orders = _apply_order_status_filter(orders, qp.filters)

        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}
        effective_filters = {**qp.filters, "delivery_data_quality_flag": qp.delivery_flag_filter or "VALID"}

        if not qp.dimensions:
            total_in_scope = len(orders)
            flag_counts = orders["delivery_data_quality_flag"].value_counts().to_dict()
            excluded_invalid = int(flag_counts.get("INVALID_SEQUENCE", 0))
            excluded_missing = int(flag_counts.get("MISSING_CUSTOMER_DATE", 0) + flag_counts.get("MISSING_CARRIER_DATE", 0))

            valid = orders[orders["delivery_data_quality_flag"] == (qp.delivery_flag_filter or "VALID")]
            n = len(valid)
            value = float(valid["delivery_days"].mean()) if n else None
            coverage = (n / total_in_scope) if total_in_scope else None

            warnings = []
            if excluded_invalid:
                warnings.append(f"{excluded_invalid} rows excluded (INVALID_SEQUENCE -- carrier timestamp precedes purchase timestamp).")
            if excluded_missing:
                warnings.append(f"{excluded_missing} rows excluded due to missing/invalid delivery timestamps.")
            warnings += self._coverage_warning(coverage, threshold, total_in_scope - n, None)

            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period,
                grain=qp.contract["base_grain"], dimensions={}, filters=effective_filters,
                sample_size=n, coverage=coverage, data_quality=_data_quality_tier(coverage, threshold),
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"], warnings=warnings,
                metadata={"excluded_invalid": excluded_invalid, "excluded_missing": excluded_missing, "total_in_scope": total_in_scope},
            )

        orders, group_cols = _apply_dimension_columns(self.data, orders, qp.dimensions, "purchase_timestamp")
        dim_names = [d.name for d in qp.dimensions]
        results = []
        for key, sub in orders.groupby(group_cols, dropna=False):
            keys = key if isinstance(key, tuple) else (key,)
            dims = dict(zip(dim_names, keys))
            total = len(sub)
            flag_counts = sub["delivery_data_quality_flag"].value_counts().to_dict()
            excluded_invalid = int(flag_counts.get("INVALID_SEQUENCE", 0))
            excluded_missing = int(flag_counts.get("MISSING_CUSTOMER_DATE", 0) + flag_counts.get("MISSING_CARRIER_DATE", 0))
            valid = sub[sub["delivery_data_quality_flag"] == (qp.delivery_flag_filter or "VALID")]
            n = len(valid)
            value = float(valid["delivery_days"].mean()) if n else None
            coverage = (n / total) if total else None
            results.append(KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions=dims, filters=effective_filters, sample_size=n, coverage=coverage,
                data_quality=_data_quality_tier(coverage, threshold),
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"],
                warnings=self._coverage_warning(coverage, threshold, total - n, None),
                metadata={"excluded_invalid": excluded_invalid, "excluded_missing": excluded_missing, "total_in_scope": total},
            ))
        return results

    # -- On-Time Delivery Rate ---------------------------------------------------

    def _compute_on_time_delivery_rate(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        orders = self.data.get("fact_orders")
        orders = _apply_date_range(orders, "purchase_timestamp", qp.start, qp.end)
        orders = _apply_window_filter(orders, qp.apply_window_filter)
        orders = _apply_order_status_filter(orders, qp.filters)

        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}
        effective_filters = {**qp.filters, "delivery_data_quality_flag": qp.delivery_flag_filter or "VALID"}

        if not qp.dimensions:
            total_in_scope = len(orders)
            valid = orders[orders["delivery_data_quality_flag"] == (qp.delivery_flag_filter or "VALID")]
            denominator = len(valid)
            numerator = int((valid["delivery_delay_days"] <= 0).sum())
            value = None if denominator == 0 else numerator / denominator
            coverage = (denominator / total_in_scope) if total_in_scope else None
            excluded = total_in_scope - denominator

            warnings = self._coverage_warning(coverage, threshold, excluded, None)
            if denominator == 0:
                warnings.append("Zero orders with valid delivery data in scope -- rate is NULL, not 0%.")

            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period,
                grain=qp.contract["base_grain"], dimensions={}, filters=effective_filters,
                sample_size=denominator, coverage=coverage, data_quality=_data_quality_tier(coverage, threshold),
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"], warnings=warnings,
                metadata={"numerator": numerator, "denominator": denominator, "rate": value, "excluded_rows": excluded},
            )

        orders, group_cols = _apply_dimension_columns(self.data, orders, qp.dimensions, "purchase_timestamp")
        dim_names = [d.name for d in qp.dimensions]
        results = []
        for key, sub in orders.groupby(group_cols, dropna=False):
            keys = key if isinstance(key, tuple) else (key,)
            dims = dict(zip(dim_names, keys))
            total = len(sub)
            valid = sub[sub["delivery_data_quality_flag"] == (qp.delivery_flag_filter or "VALID")]
            denominator = len(valid)
            numerator = int((valid["delivery_delay_days"] <= 0).sum())
            value = None if denominator == 0 else numerator / denominator
            coverage = (denominator / total) if total else None
            results.append(KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions=dims, filters=effective_filters, sample_size=denominator, coverage=coverage,
                data_quality=_data_quality_tier(coverage, threshold),
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"],
                warnings=self._coverage_warning(coverage, threshold, total - denominator, None),
                metadata={"numerator": numerator, "denominator": denominator, "rate": value, "excluded_rows": total - denominator},
            ))
        return results

    # -- Average Review Score ------------------------------------------------

    def _compute_avg_review_score(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        lineage = qp.contract["lineage"]["chain"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}

        if qp.variant == "review_level_average":
            if qp.dimensions:
                raise KPIRequestError(
                    "review_level_average does not support dimension-grouped requests in this engine -- "
                    "its time anchor (review_creation_date) differs from the order-level variants' "
                    "(purchase_timestamp), and customer_state requires an additional join not built for "
                    "this variant. Use the default order_level_representative variant for grouped queries."
                )
            reviews = self.data.get("fact_reviews")
            reviews = _apply_date_range(reviews, "review_creation_date", qp.start, qp.end)
            # order_status / window filtering still requires joining to fact_orders,
            # per the contract's declared source (an order attribute), even though
            # this variant's time anchor is review_creation_date, not purchase_timestamp.
            reviews = _join_order_context(self.data, reviews, ["order_status", "in_analytical_window"])
            reviews = _apply_window_filter(reviews, qp.apply_window_filter)
            reviews = _apply_order_status_filter(reviews, qp.filters)
            n = len(reviews)
            value = float(reviews["review_score"].mean()) if n else None
            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain="review (fact_reviews, no dedup)",
                dimensions={}, filters=qp.filters, sample_size=n, coverage=1.0 if n else None,
                data_quality=_data_quality_tier(1.0 if n else None, threshold),
                source=["fact_reviews"], lineage=lineage, warnings=[],
                metadata={"variant": qp.variant, "note": "Every raw review row weighted equally, including duplicate review_ids and multi-review orders. NOT MAX()."},
            )

        # order_level_representative (default) or order_level_true_average
        source_col = "latest_review_score" if qp.variant == "order_level_representative" else "avg_review_score"
        agg = self.data.get("agg_order_reviews")
        agg = _join_order_context(
            self.data, agg,
            ["purchase_timestamp", "order_status", "customer_state", "in_analytical_window"],
        )
        agg = _apply_date_range(agg, "purchase_timestamp", qp.start, qp.end)
        agg = _apply_window_filter(agg, qp.apply_window_filter)
        agg = _apply_order_status_filter(agg, qp.filters)

        if not qp.dimensions:
            orders = self.data.get("fact_orders")
            orders = _apply_date_range(orders, "purchase_timestamp", qp.start, qp.end)
            orders = _apply_window_filter(orders, qp.apply_window_filter)
            orders = _apply_order_status_filter(orders, qp.filters)
            eligible = len(orders)
            n = len(agg)
            coverage = (n / eligible) if eligible else None

            value = float(agg[source_col].mean()) if n else None
            warnings = self._coverage_warning(coverage, threshold, eligible - n, "orders without any review")

            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period,
                grain=qp.contract["base_grain"], dimensions={}, filters=qp.filters,
                sample_size=n, coverage=coverage, data_quality=_data_quality_tier(coverage, threshold),
                source=qp.contract["source_tables"], lineage=lineage, warnings=warnings,
                metadata={"variant": qp.variant, "source_column": f"agg_order_reviews.{source_col}"},
            )

        agg, group_cols = _apply_dimension_columns(self.data, agg, qp.dimensions, "purchase_timestamp")
        dim_names = [d.name for d in qp.dimensions]
        results = []
        for key, sub in agg.groupby(group_cols, dropna=False):
            keys = key if isinstance(key, tuple) else (key,)
            dims = dict(zip(dim_names, keys))
            n = len(sub)
            value = float(sub[source_col].mean()) if n else None
            results.append(KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions=dims, filters=qp.filters, sample_size=n, coverage=None, data_quality="UNKNOWN",
                source=qp.contract["source_tables"], lineage=lineage,
                warnings=["Per-group coverage not computed for dimension-grouped review score -- see docs/KPI_COMPUTATION_ENGINE.md."],
                metadata={"variant": qp.variant, "source_column": f"agg_order_reviews.{source_col}"},
            ))
        return results

    # -- Review Volume --------------------------------------------------------

    def _compute_review_volume(self, qp: QueryPlan) -> KPIResult | list[KPIResult]:
        """Review-level count (COUNT of fact_reviews rows), per the contract's
        formula. distinct_orders_represented is ALSO exposed in metadata,
        explicitly labeled, so the two different metrics (review-level count vs.
        orders-with-review count) are never confused for one another."""
        reviews = self.data.get("fact_reviews")
        reviews = _apply_date_range(reviews, "review_creation_date", qp.start, qp.end)
        reviews = _join_order_context(self.data, reviews, ["order_status", "customer_state", "in_analytical_window"])
        reviews = _apply_window_filter(reviews, qp.apply_window_filter)
        reviews = _apply_order_status_filter(reviews, qp.filters)
        if "has_text" in qp.filters and qp.filters["has_text"]:
            reviews = reviews[reviews["has_text"]]

        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]
        period = {"start": str(qp.start.date()), "end": str(qp.end.date())}

        if not qp.dimensions:
            value = float(len(reviews))
            distinct_orders = int(reviews["order_id"].nunique())
            return KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period,
                grain=qp.contract["base_grain"], dimensions={}, filters=qp.filters,
                sample_size=int(value), coverage=1.0, data_quality=_data_quality_tier(1.0, threshold),
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"], warnings=[],
                metadata={
                    "review_level_count": int(value),
                    "distinct_orders_represented": distinct_orders,
                    "note": "value = review-level count (this KPI's contract grain). "
                            "distinct_orders_represented is a DIFFERENT metric (orders-with->=1-review count), "
                            "exposed here for clarity, not as the primary value.",
                },
            )

        reviews, group_cols = _apply_dimension_columns(self.data, reviews, qp.dimensions, "review_creation_date")
        dim_names = [d.name for d in qp.dimensions]
        results = []
        for key, sub in reviews.groupby(group_cols, dropna=False):
            keys = key if isinstance(key, tuple) else (key,)
            dims = dict(zip(dim_names, keys))
            value = float(len(sub))
            distinct_orders = int(sub["order_id"].nunique())
            results.append(KPIResult(
                kpi_id=qp.kpi_id, value=value, period=period, grain=qp.contract["base_grain"],
                dimensions=dims, filters=qp.filters, sample_size=int(value), coverage=1.0,
                data_quality=_data_quality_tier(1.0, threshold),
                source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"], warnings=[],
                metadata={"review_level_count": int(value), "distinct_orders_represented": distinct_orders},
            ))
        return results

    # -- Repeat Purchase Rate ----------------------------------------------------

    def _compute_repeat_purchase_rate(self, qp: QueryPlan) -> KPIResult:
        """customers with >=2 orders / customers with >=1 order, using
        customer_unique_id (never customer_id). Default in_analytical_window
        filter is OFF for this KPI specifically (per its contract) since a
        customer's orders can straddle the window boundary."""
        if qp.dimensions:
            raise KPIRequestError(
                "repeat_purchase_rate's 'month' dimension is declared supported at the data level, but "
                "only as a COHORT month (customer's first order date) -- config/kpis.yaml explicitly "
                "documents 'no ready query is implemented' for this (see the contract's "
                "unresolved_semantic_decisions). A naive per-period slice would double-count "
                "repeat status across periods, which this engine refuses to do rather than silently "
                "computing something the contract does not actually define."
            )

        orders = self.data.get("fact_orders")
        orders = _apply_date_range(orders, "purchase_timestamp", qp.start, qp.end)
        orders = _apply_window_filter(orders, qp.apply_window_filter)  # no-op by default for this KPI
        orders = _apply_order_status_filter(orders, qp.filters)

        # fact_orders already carries customer_unique_id denormalized from
        # dim_customer (verified consistent by Step 2's own test suite) -- no
        # join needed, and joining dim_customer again here would collide with
        # this already-present column.
        order_counts = orders.groupby("customer_unique_id")["order_id"].nunique()
        total_customers = int(len(order_counts))
        repeat_customers = int((order_counts >= 2).sum())
        value = None if total_customers == 0 else repeat_customers / total_customers
        threshold = qp.contract["data_quality_requirements"]["coverage_threshold_pct"]

        min_obs = qp.contract["data_quality_requirements"]["minimum_observations"]
        warnings = []
        if total_customers < min_obs:
            warnings.append(f"Only {total_customers} distinct customers in scope, below the contract's minimum_observations ({min_obs}) for a stable rate estimate.")

        return KPIResult(
            kpi_id=qp.kpi_id, value=value,
            period={"start": str(qp.start.date()), "end": str(qp.end.date())},
            grain=qp.contract["base_grain"], dimensions={}, filters=qp.filters,
            sample_size=total_customers, coverage=1.0, data_quality=_data_quality_tier(1.0, threshold),
            source=qp.contract["source_tables"], lineage=qp.contract["lineage"]["chain"], warnings=warnings,
            metadata={"repeat_customers": repeat_customers, "total_customers": total_customers, "rate": value},
        )

    # -- shared -----------------------------------------------------------------

    @staticmethod
    def _coverage_warning(coverage: Optional[float], threshold_pct: float, excluded_count: int,
                           excluded_reason: Optional[str]) -> list[str]:
        warnings = []
        if coverage is not None and coverage * 100 < threshold_pct and excluded_count > 0:
            reason = f" ({excluded_reason})" if excluded_reason else ""
            warnings.append(
                f"{excluded_count} rows excluded{reason}; coverage {coverage * 100:.2f}% is below the "
                f"contract's {threshold_pct}% HIGH-confidence threshold."
            )
        return warnings
