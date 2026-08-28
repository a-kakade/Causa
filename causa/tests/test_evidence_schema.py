"""Evidence schema tests (Step 4 §3/§4/§14/§15/§20/§31).

Verifies the strict Pydantic EvidenceObject/Claim/EvidenceQuery/EvidenceResult
schema: extra fields are rejected, causal language is rejected in claim/text
fields, metadata/dimensions stay flat, and EvidenceQuery's bounds are
enforced. No engine, no canonical data -- pure schema tests.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evidence.models import (  # noqa: E402
    Confidence, EvidenceTier, EvidenceType, RelationshipType,
    SecurityClassification, SecurityStatus, TrustLevel,
)
from evidence.schema import (  # noqa: E402
    Claim, EvidenceObject, EvidenceQuery, EvidenceResult, FreshnessInfo,
    QualityInfo, RelationshipRef, RetrievalInfo, ReviewSourceRef, SecurityInfo,
    SourceInfo, TimeRange, ValueSpec,
)

NOW = datetime.now(timezone.utc).isoformat()


def _minimal_evidence_kwargs(**overrides):
    kwargs = dict(
        evidence_id="ev_test_0000000000000000",
        evidence_type=EvidenceType.KPI_MOVEMENT,
        evidence_tier=EvidenceTier.T1_DESCRIPTIVE,
        claim="Revenue increased by R$346,051.94 from October to November 2017.",
        value=ValueSpec(value=346051.94, unit="BRL"),
        time=TimeRange(start="2017-10-01", end="2017-11-30"),
        confidence=Confidence.HIGH,
        source=SourceInfo(system="kpi_engine", component="kpi.engine.KPIEngine.compare_periods"),
        freshness=FreshnessInfo(event_time="2017-11-30", processing_time=NOW),
        quality=QualityInfo(completeness=0.99, coverage=0.99),
        security=SecurityInfo(
            classification=SecurityClassification.PUBLIC_ANALYTICAL,
            trust_level=TrustLevel.TRUSTED_SYSTEM,
        ),
        created_at=NOW,
    )
    kwargs.update(overrides)
    return kwargs


# ---------------------------------------------------------------------------
# extra="forbid"
# ---------------------------------------------------------------------------

def test_evidence_object_rejects_extra_fields():
    kwargs = _minimal_evidence_kwargs()
    kwargs["not_a_real_field"] = "sneaky"
    with pytest.raises(ValidationError):
        EvidenceObject(**kwargs)


def test_value_spec_rejects_extra_fields():
    with pytest.raises(ValidationError):
        ValueSpec(value=1.0, unit="BRL", extra_thing="nope")


def test_evidence_query_rejects_extra_fields():
    with pytest.raises(ValidationError):
        EvidenceQuery(investigation_id="inv1", question="q", not_real="x")


# ---------------------------------------------------------------------------
# Causal-language rejection (task §31)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("phrase", [
    "Revenue increased because of the Black Friday effect.",
    "Delivery delays were caused by carrier issues.",
    "The drop in AOV was due to a mix shift.",
    "Volume growth led to the revenue increase.",
    "Higher order volume was responsible for the change.",
])
def test_evidence_object_claim_rejects_causal_language(phrase):
    kwargs = _minimal_evidence_kwargs(claim=phrase)
    with pytest.raises(ValidationError, match="causal language"):
        EvidenceObject(**kwargs)


def test_claim_text_rejects_causal_language():
    with pytest.raises(ValidationError, match="causal language"):
        Claim(claim_id="cl_1", text="Orders increased because of a marketing push.",
              supported_by=[], created_at=NOW)


def test_evidence_object_claim_allows_non_causal_descriptive_language():
    kwargs = _minimal_evidence_kwargs(
        claim="Revenue moved from R$664,219.43 in October 2017 to R$1,010,271.37 in November 2017 (+52.1%)."
    )
    obj = EvidenceObject(**kwargs)
    assert obj.claim.startswith("Revenue moved")


def test_relationship_note_rejects_causal_language():
    with pytest.raises(ValidationError, match="causal language"):
        RelationshipRef(
            relationship_type=RelationshipType.CONTRADICTS,
            target_evidence_id="ev_x",
            note="This gap is due to delivery issues in the affected category.",
        )


# ---------------------------------------------------------------------------
# Claim / SUPPORTED_BY (task §4)
# ---------------------------------------------------------------------------

def test_claim_supported_by_accepts_empty_list():
    claim = Claim(claim_id="cl_unsupported", text="An unsupported hypothesis, flagged as such.",
                  supported_by=[], created_at=NOW)
    assert claim.supported_by == []


def test_claim_supported_by_references_evidence_ids():
    claim = Claim(claim_id="cl_1", text="A claim backed by two pieces of evidence.",
                  supported_by=["ev_a", "ev_b"], created_at=NOW)
    assert claim.supported_by == ["ev_a", "ev_b"]


# ---------------------------------------------------------------------------
# EvidenceQuery bounds (task §14)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("top_k", [0, -1, 101, 1000])
def test_evidence_query_top_k_out_of_bounds_rejected(top_k):
    with pytest.raises(ValidationError):
        EvidenceQuery(investigation_id="inv1", question="q", top_k=top_k)


@pytest.mark.parametrize("top_k", [1, 10, 100])
def test_evidence_query_top_k_in_bounds_accepted(top_k):
    q = EvidenceQuery(investigation_id="inv1", question="q", top_k=top_k)
    assert q.top_k == top_k


@pytest.mark.parametrize("rel", [-0.1, 1.1, 2.0])
def test_evidence_query_minimum_relevance_out_of_bounds_rejected(rel):
    with pytest.raises(ValidationError):
        EvidenceQuery(investigation_id="inv1", question="q", minimum_relevance=rel)


def test_evidence_query_defaults_to_public_analytical_clearance():
    q = EvidenceQuery(investigation_id="inv1", question="q")
    assert q.requester_clearance == SecurityClassification.PUBLIC_ANALYTICAL


# ---------------------------------------------------------------------------
# SecurityInfo defaults (task §8/§9)
# ---------------------------------------------------------------------------

def test_security_info_defaults_to_safe_status_and_no_pii():
    sec = SecurityInfo(classification=SecurityClassification.PUBLIC_ANALYTICAL,
                        trust_level=TrustLevel.TRUSTED_SYSTEM)
    assert sec.security_status == SecurityStatus.SAFE
    assert sec.pii_detected is False
    assert sec.pii_types == []
    assert sec.redaction_status == "NOT_APPLICABLE"


def test_security_info_untrusted_review_can_be_flagged_suspicious():
    sec = SecurityInfo(classification=SecurityClassification.PUBLIC_ANALYTICAL,
                        trust_level=TrustLevel.UNTRUSTED_DATA,
                        security_status=SecurityStatus.SUSPICIOUS,
                        pii_detected=True, pii_types=["email"])
    assert sec.trust_level == TrustLevel.UNTRUSTED_DATA
    assert sec.security_status == SecurityStatus.SUSPICIOUS


# ---------------------------------------------------------------------------
# metadata / dimensions must stay flat (closes the extra="forbid" escape hatch)
# ---------------------------------------------------------------------------

def test_metadata_rejects_nested_dict():
    kwargs = _minimal_evidence_kwargs(metadata={"nested": {"a": 1}})
    with pytest.raises(ValidationError, match="flat"):
        EvidenceObject(**kwargs)


def test_metadata_rejects_nested_list():
    kwargs = _minimal_evidence_kwargs(metadata={"nested": [1, 2, 3]})
    with pytest.raises(ValidationError, match="flat"):
        EvidenceObject(**kwargs)


def test_metadata_accepts_flat_primitives():
    kwargs = _minimal_evidence_kwargs(metadata={"numerator": 7544, "denominator": 4631, "note": "ok", "flag": True})
    obj = EvidenceObject(**kwargs)
    assert obj.metadata["numerator"] == 7544


def test_evidence_result_metadata_rejects_nested():
    with pytest.raises(ValidationError, match="flat"):
        EvidenceResult(
            evidence_id="ev_r1", evidence_type=EvidenceType.CUSTOMER_REVIEW,
            claim="A customer review.", content="ótimo produto",
            retrieval=RetrievalInfo(rank=1, score=0.9, method="structured_filter"),
            source=ReviewSourceRef(review_id="r1", order_id="o1"),
            metadata={"bad": {"a": 1}},
            evidence_tier=EvidenceTier.T1_DESCRIPTIVE,
            security=SecurityInfo(classification=SecurityClassification.PUBLIC_ANALYTICAL,
                                   trust_level=TrustLevel.UNTRUSTED_DATA),
        )


# ---------------------------------------------------------------------------
# QualityInfo bounds (task §20 -- multiple sub-scores, each 0..1)
# ---------------------------------------------------------------------------

def test_quality_info_rejects_out_of_range_score():
    with pytest.raises(ValidationError):
        QualityInfo(completeness=1.5)


def test_quality_info_allows_none_for_not_applicable_scores():
    q = QualityInfo(completeness=0.9)
    assert q.retrieval_quality is None
    assert q.historical_sufficiency is None


# ---------------------------------------------------------------------------
# created_at / processing_time must be valid ISO datetimes
# ---------------------------------------------------------------------------

def test_created_at_rejects_non_iso_string():
    kwargs = _minimal_evidence_kwargs(created_at="not-a-date")
    with pytest.raises(ValidationError):
        EvidenceObject(**kwargs)


def test_created_at_accepts_iso_string():
    obj = EvidenceObject(**_minimal_evidence_kwargs())
    assert obj.created_at == NOW


# ---------------------------------------------------------------------------
# EvidenceResult never a bare string -- always has provenance (task §15)
# ---------------------------------------------------------------------------

def test_evidence_result_requires_source_and_retrieval():
    result = EvidenceResult(
        evidence_id="ev_r1", evidence_type=EvidenceType.CUSTOMER_REVIEW,
        claim="A customer review about delivery.", content="chegou atrasado",
        retrieval=RetrievalInfo(rank=1, score=0.81, method="structured_filter+semantic_e5_cosine"),
        source=ReviewSourceRef(review_id="r1", order_id="o1"),
        evidence_tier=EvidenceTier.T1_DESCRIPTIVE,
        security=SecurityInfo(classification=SecurityClassification.PUBLIC_ANALYTICAL,
                               trust_level=TrustLevel.UNTRUSTED_DATA),
    )
    assert result.source.review_id == "r1"
    assert result.retrieval.rank == 1
