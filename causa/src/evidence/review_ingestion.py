"""
review_ingestion.py — Step 4: normalizes canonical review rows and builds
CUSTOMER_REVIEW evidence objects (task §6/§7).

THIS MODULE PERFORMS A NON-GOVERNED JOIN. build_review_order_join() attaches
each review to the SET of product categories / sellers present on its order
via fact_reviews -> fact_orders -> fact_order_items -> dim_product. This is
explicitly NOT the same thing as a governed KPI dimension: config/kpis.yaml
and src/kpi/query_planner.py deliberately REFUSE product_category/seller as
review dimensions (a review attaches to an order, and ~9.86%% of orders span
multiple items/categories/sellers -- see config/kpis.yaml's avg_review_score
contract, "unsupported_reason"). This module does not silently resolve that
ambiguity by picking one category; it tags each review with a
`category_attribution_method` explaining exactly how confident the
category/seller label is, and this module is NEVER imported by
src/kpi/, src/anomaly/, or src/drivers/ -- it feeds review evidence only.

Review text is UNTRUSTED_DATA (task §8) -- every EvidenceObject this module
builds carries trust_level=UNTRUSTED_DATA regardless of its
security_status (SAFE/SUSPICIOUS/BLOCKED), and canonical fact_reviews.parquet
is read here but never written to or mutated.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from evidence import structured_adapter as adapter
from evidence.language import LanguageResult, detect_language
from evidence.models import (
    TIER_FOR_EVIDENCE_TYPE,
    Confidence,
    EvidenceType,
    SecurityClassification,
    SecurityStatus,
    TrustLevel,
)
from evidence.pii import PiiResult, detect_pii
from evidence.safety import SafetyResult, classify_safety
from evidence.schema import EvidenceObject, FreshnessInfo, QualityInfo, SecurityInfo, SourceInfo, TimeRange, ValueSpec

ADAPTER_VERSION = "1.0"

SINGLE_ITEM_ORDER = "single_item_order"
SINGLE_CATEGORY_ORDER = "single_category_order"
MULTI_ITEM_AMBIGUOUS = "multi_item_order_ambiguous"
NO_ITEMS_ON_ORDER = "no_items_on_order"

UNCATEGORIZED_LABEL = "uncategorized"       # matches drivers/pvm.py's sentinel, for consistency
UNKNOWN_SELLER_LABEL = "unknown_seller"     # matches drivers/contribution.py's sentinel


def normalize_review_row(title: Optional[str], message: Optional[str]) -> dict:
    """Non-destructive normalization: concatenates title + message (title
    first), strips/collapses whitespace, NFKC-normalizes unicode. The
    original, un-normalized concatenation is kept as `raw_text` alongside the
    normalized `text` so downstream security/PII scans can be re-run against
    either form and evidence lineage can always point back to exactly what
    was in fact_reviews.parquet. Never touches the parquet file itself."""
    parts = [p for p in (title, message) if isinstance(p, str) and p.strip()]
    raw_text = " ".join(parts)
    normalized = unicodedata.normalize("NFKC", raw_text)
    normalized = " ".join(normalized.split())   # collapse all whitespace runs
    return {"raw_text": raw_text, "text": normalized}


@dataclass
class ReviewOrderJoinRow:
    review_row_id: int
    review_id: str
    order_id: str
    review_score: int
    text: str
    raw_text: str
    review_creation_date: Optional[str]
    month: Optional[str]                        # purchase month (fact_orders.purchase_timestamp), YYYY-MM
    customer_state: Optional[str]
    category: Optional[str]                     # populated only when attribution is unambiguous
    seller: Optional[str]                        # populated only when attribution is unambiguous
    seller_state: Optional[str]
    category_attribution_method: str


def build_review_order_join(fact_reviews: pd.DataFrame, fact_orders: pd.DataFrame,
                             fact_order_items: pd.DataFrame, dim_product: pd.DataFrame,
                             dim_seller: pd.DataFrame) -> list[ReviewOrderJoinRow]:
    """Builds the review-pipeline-only join described in this module's
    docstring. Returns one ReviewOrderJoinRow per fact_reviews row (all
    99,224, including reviews on orders that have no items -- flagged
    NO_ITEMS_ON_ORDER, category/seller left None).

    Fully vectorized (merge/groupby, no per-row Python loop over 99K+ rows) --
    a per-row `.loc[]` lookup loop over the full review corpus was measured
    at ~25ms/row (~40 minutes for the full corpus); this version runs in low
    single-digit seconds."""
    items = fact_order_items.merge(dim_product[["product_id", "category_name_en"]], on="product_id", how="left")
    items = items.merge(dim_seller[["seller_id", "seller_state"]], on="seller_id", how="left")
    items["category_name_en"] = items["category_name_en"].fillna(UNCATEGORIZED_LABEL)
    items["seller_id"] = items["seller_id"].fillna(UNKNOWN_SELLER_LABEL)
    items["seller_state"] = items["seller_state"].fillna(UNKNOWN_SELLER_LABEL)

    per_order = items.groupby("order_id").agg(
        item_count=("order_item_id", "size"),
        categories=("category_name_en", lambda s: sorted(set(s))),
        sellers=("seller_id", lambda s: sorted(set(s))),
        seller_states=("seller_state", lambda s: sorted(set(s))),
    ).reset_index()
    per_order["n_categories"] = per_order["categories"].str.len()
    per_order["n_sellers"] = per_order["sellers"].str.len()
    per_order["first_category"] = per_order["categories"].str.get(0)
    per_order["first_seller"] = per_order["sellers"].str.get(0)
    per_order["first_seller_state"] = per_order["seller_states"].str.get(0)

    orders = fact_orders[["order_id", "purchase_timestamp", "customer_state"]]

    merged = fact_reviews.merge(orders, on="order_id", how="left").merge(per_order, on="order_id", how="left")

    month = merged["purchase_timestamp"].dt.strftime("%Y-%m")
    creation_date = merged["review_creation_date"].dt.strftime("%Y-%m-%d")

    has_items = merged["item_count"].notna()
    is_single_item = has_items & (merged["item_count"] == 1)
    is_single_category = has_items & (merged["item_count"] != 1) & (merged["n_categories"] == 1) & \
        (merged["n_sellers"] == 1)

    method = pd.Series(MULTI_ITEM_AMBIGUOUS, index=merged.index)
    method = method.mask(~has_items, NO_ITEMS_ON_ORDER)
    method = method.mask(is_single_category, SINGLE_CATEGORY_ORDER)
    method = method.mask(is_single_item, SINGLE_ITEM_ORDER)
    unambiguous = is_single_item | is_single_category

    category = merged["first_category"].where(unambiguous)
    seller = merged["first_seller"].where(unambiguous)
    seller_state = merged["first_seller_state"].where(unambiguous)

    # Convert every per-row column to plain Python lists up front -- iterating
    # zip() over lists is orders of magnitude faster than repeated .iloc[i]
    # scalar lookups (each .iloc call re-does pandas' indexing machinery).
    def _to_list(series: pd.Series) -> list:
        return series.where(series.notna(), None).tolist()

    review_row_ids = merged["review_row_id"].tolist()
    review_ids = merged["review_id"].tolist()
    order_ids = merged["order_id"].tolist()
    review_scores = merged["review_score"].tolist()
    creation_dates = _to_list(creation_date)
    months = _to_list(month)
    customer_states = _to_list(merged["customer_state"])
    categories_out = _to_list(category)
    sellers_out = _to_list(seller)
    seller_states_out = _to_list(seller_state)
    methods_out = method.tolist()

    normalized = (normalize_review_row(t, m) for t, m in
                  zip(merged["review_comment_title"], merged["review_comment_message"]))

    rows: list[ReviewOrderJoinRow] = [
        ReviewOrderJoinRow(
            review_row_id=int(review_row_ids[i]), review_id=str(review_ids[i]), order_id=str(order_ids[i]),
            review_score=int(review_scores[i]), text=norm["text"], raw_text=norm["raw_text"],
            review_creation_date=creation_dates[i], month=months[i], customer_state=customer_states[i],
            category=categories_out[i], seller=sellers_out[i], seller_state=seller_states_out[i],
            category_attribution_method=methods_out[i],
        )
        for i, norm in enumerate(normalized)
    ]
    return rows


def build_review_evidence(row: ReviewOrderJoinRow) -> EvidenceObject:
    """Builds one CUSTOMER_REVIEW EvidenceObject (T1_DESCRIPTIVE, always
    trust_level=UNTRUSTED_DATA). Runs language/pii/safety detection on the
    NORMALIZED text (never on a translated/paraphrased version, per task
    §7/§8)."""
    evidence_type = EvidenceType.CUSTOMER_REVIEW
    lang: LanguageResult = detect_language(row.text)
    pii: PiiResult = detect_pii(row.text)
    safety: SafetyResult = classify_safety(row.text)

    now = datetime.now(timezone.utc).isoformat()
    dims = {"order_id": row.order_id, "category_attribution_method": row.category_attribution_method}
    if row.month:
        dims["month"] = row.month
    if row.customer_state:
        dims["customer_state"] = row.customer_state
    if row.category:
        dims["category"] = row.category
    if row.seller:
        dims["seller"] = row.seller
    if row.seller_state:
        dims["seller_state"] = row.seller_state

    classification = SecurityClassification.INTERNAL if row.seller else SecurityClassification.PUBLIC_ANALYTICAL

    claim = f"Customer review (score={row.review_score}) for order {row.order_id}."

    return EvidenceObject(
        evidence_id=adapter.evidence_id_for("review", row.review_row_id),
        evidence_type=evidence_type,
        evidence_tier=TIER_FOR_EVIDENCE_TYPE[evidence_type],
        claim=claim,
        value=ValueSpec(value=row.review_score, unit="score_1_5"),
        time=TimeRange(start=row.review_creation_date or "1970-01-01", end=row.review_creation_date or "1970-01-01"),
        dimensions=dims,
        confidence=Confidence.HIGH,   # the review_score itself is a directly-observed canonical field
        source=SourceInfo(system="review_pipeline", component="evidence.review_ingestion.build_review_evidence",
                           version=ADAPTER_VERSION),
        lineage=[
            {"layer": "canonical_table", "reference": "data/processed/fact_reviews.parquet"},
            {"layer": "raw_table", "reference": "data/raw/olist/olist_order_reviews_dataset.csv"},
            {"layer": "order_join", "reference": "data/processed/fact_orders.parquet (order_id)"},
        ],
        freshness=FreshnessInfo(event_time=row.review_creation_date, processing_time=now),
        quality=QualityInfo(
            completeness=1.0 if row.text else 0.0,
            source_reliability=1.0 if row.category_attribution_method in
            (SINGLE_ITEM_ORDER, SINGLE_CATEGORY_ORDER) else 0.5,
        ),
        security=SecurityInfo(
            classification=classification,
            trust_level=TrustLevel.UNTRUSTED_DATA,
            security_status=SecurityStatus(safety.security_status),
            pii_detected=pii.pii_detected,
            pii_types=pii.pii_types,
            redaction_status="NOT_REDACTED",
        ),
        metadata={
            "review_id": row.review_id, "language": lang.language,
            "language_confidence": lang.language_confidence, "has_text": bool(row.text),
            "text": row.text,   # normalized text -- the retrieval layer's source of truth for embedding/content
        },
        created_at=now,
    )
