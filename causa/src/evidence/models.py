"""
models.py — Step 4: the Evidence Fabric's taxonomy, enums, and leaf value
objects.

This module holds no orchestration logic and touches no canonical data. Its
only job is to define the governed vocabulary evidence objects are built
from -- the same "definitions, not calculation" posture src/kpi/models.py,
src/anomaly/models.py, and src/drivers/models.py already take relative to
their own engines.

STRICT RULE (task §1/§2): Steps 3B-3D currently produce only T1/T2/T3
evidence. T4_CAUSAL and T5_EXPERIMENTAL (and the EvidenceType values
EXTERNAL_CONTEXT/BUSINESS_RULE/CAUSAL_RESULT/ACTION_RESULT) are declared here
for taxonomy extensibility but are never instantiated anywhere in this
package. POPULATED_IN_STEP4 is the concrete enforcement mechanism -- every
evidence-constructing function in structured_adapter.py and
review_ingestion.py asserts its evidence_type is a member of this set before
building an EvidenceObject, so "do not fabricate T4/T5 evidence" is a runtime
check, not just a comment.
"""

from __future__ import annotations

import re
from enum import Enum


# ---------------------------------------------------------------------------
# Evidence taxonomy (task §1)
# ---------------------------------------------------------------------------

class EvidenceTier(str, Enum):
    T1_DESCRIPTIVE = "T1_DESCRIPTIVE"      # observed movement or association
    T2_ARITHMETIC = "T2_ARITHMETIC"        # deterministic mathematical decomposition
    T3_STATISTICAL = "T3_STATISTICAL"      # statistical/anomaly evidence
    T4_CAUSAL = "T4_CAUSAL"                # reserved -- validated causal inference; NOT populated in Step 4
    T5_EXPERIMENTAL = "T5_EXPERIMENTAL"    # reserved -- experimental evidence; NOT populated in Step 4


# ---------------------------------------------------------------------------
# Evidence types (task §2)
# ---------------------------------------------------------------------------

class EvidenceType(str, Enum):
    KPI_OBSERVATION = "KPI_OBSERVATION"
    KPI_MOVEMENT = "KPI_MOVEMENT"
    ANOMALY_SIGNAL = "ANOMALY_SIGNAL"
    DRIVER_CONTRIBUTION = "DRIVER_CONTRIBUTION"
    SEGMENT_CONTRIBUTION = "SEGMENT_CONTRIBUTION"
    CONCURRENT_KPI = "CONCURRENT_KPI"
    STATISTICAL_RESULT = "STATISTICAL_RESULT"
    CUSTOMER_REVIEW = "CUSTOMER_REVIEW"
    EXTERNAL_CONTEXT = "EXTERNAL_CONTEXT"      # reserved, not populated in Step 4
    BUSINESS_RULE = "BUSINESS_RULE"            # reserved, not populated in Step 4
    CAUSAL_RESULT = "CAUSAL_RESULT"            # reserved, not populated in Step 4 (Step 5+ only)
    ACTION_RESULT = "ACTION_RESULT"            # reserved, not populated in Step 4 (Step 5+ only)


# The only evidence types any function in this package is permitted to
# construct. structured_adapter.py and review_ingestion.py both assert
# membership here before returning an EvidenceObject.
POPULATED_IN_STEP4 = frozenset({
    EvidenceType.KPI_OBSERVATION,
    EvidenceType.KPI_MOVEMENT,
    EvidenceType.ANOMALY_SIGNAL,
    EvidenceType.DRIVER_CONTRIBUTION,
    EvidenceType.SEGMENT_CONTRIBUTION,
    EvidenceType.CONCURRENT_KPI,
    EvidenceType.STATISTICAL_RESULT,
    EvidenceType.CUSTOMER_REVIEW,
})

# Fixed evidence_type -> evidence_tier lookup (task §1's "Steps 3B-3D produce
# only T1/T2/T3" rule, made mechanical rather than decided ad hoc per call
# site). CUSTOMER_REVIEW is T1_DESCRIPTIVE: a review is an observed fact, not
# an arithmetic or statistical derivation.
TIER_FOR_EVIDENCE_TYPE: dict[EvidenceType, EvidenceTier] = {
    EvidenceType.KPI_OBSERVATION: EvidenceTier.T1_DESCRIPTIVE,
    EvidenceType.KPI_MOVEMENT: EvidenceTier.T1_DESCRIPTIVE,
    EvidenceType.CONCURRENT_KPI: EvidenceTier.T1_DESCRIPTIVE,
    EvidenceType.CUSTOMER_REVIEW: EvidenceTier.T1_DESCRIPTIVE,
    EvidenceType.DRIVER_CONTRIBUTION: EvidenceTier.T2_ARITHMETIC,
    EvidenceType.SEGMENT_CONTRIBUTION: EvidenceTier.T2_ARITHMETIC,
    EvidenceType.ANOMALY_SIGNAL: EvidenceTier.T3_STATISTICAL,
    EvidenceType.STATISTICAL_RESULT: EvidenceTier.T3_STATISTICAL,
}


# ---------------------------------------------------------------------------
# Security / trust (task §8/§9/§21, reusing Step 3A's classification scale)
# ---------------------------------------------------------------------------

class SecurityClassification(str, Enum):
    """Identical literal values and ordering to the scale already established
    in config/kpis.yaml and enforced in src/kpi/query_planner.py and
    src/drivers/engine.py. Not redefined -- reused."""
    PUBLIC_ANALYTICAL = "PUBLIC_ANALYTICAL"
    INTERNAL = "INTERNAL"
    RESTRICTED = "RESTRICTED"


# Same rank map/order as CLEARANCE_RANK in src/kpi/query_planner.py and
# src/drivers/engine.py. Duplicated here rather than imported because those
# modules don't expose it as a public, importable constant (it's a private
# module-level dict in each) and because src/evidence/ is a new layer with
# its own access_control.py -- see access_control.py for the canonical
# Step-4-side copy this constant mirrors.
CLEARANCE_RANK: dict[str, int] = {
    SecurityClassification.PUBLIC_ANALYTICAL.value: 0,
    SecurityClassification.INTERNAL.value: 1,
    SecurityClassification.RESTRICTED.value: 2,
}


class TrustLevel(str, Enum):
    """Whether the *content* of this evidence object came from a governed
    deterministic engine (kpi/anomaly/drivers) or from raw, unvetted customer
    text. This is orthogonal to SecurityClassification (which governs *who*
    may see it) -- TrustLevel governs whether the content itself may ever be
    treated as instructions (task §8: never)."""
    TRUSTED_SYSTEM = "TRUSTED_SYSTEM"
    UNTRUSTED_DATA = "UNTRUSTED_DATA"


class SecurityStatus(str, Enum):
    """Task §8. BLOCKED is a classification flag only -- nothing in this
    package ever deletes a review row because of it (task §8: "Do not delete
    suspicious reviews from the canonical source")."""
    SAFE = "SAFE"
    SUSPICIOUS = "SUSPICIOUS"
    BLOCKED = "BLOCKED"


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class RelationshipType(str, Enum):
    """Task §16's edge types, reused for both EvidenceObject.relationships and
    graph.py's NetworkX edges so the two stay vocabulary-consistent."""
    HAS_MOVEMENT = "HAS_MOVEMENT"
    EXPLAINED_BY = "EXPLAINED_BY"
    SUPPORTED_BY = "SUPPORTED_BY"
    CONTRADICTS = "CONTRADICTS"
    CONTEXTUALIZED_BY = "CONTEXTUALIZED_BY"
    DERIVED_FROM = "DERIVED_FROM"
    HAS_CONFIDENCE = "HAS_CONFIDENCE"
    RECOMMENDS = "RECOMMENDS"


GRAPH_NODE_TYPES = frozenset({
    "INVESTIGATION", "KPI", "MOVEMENT", "DRIVER", "SEGMENT",
    "EVIDENCE", "BUSINESS_CONTEXT", "CONFIDENCE", "ACTION",
})


# ---------------------------------------------------------------------------
# Causal-language guard (task §31: no field may read as a causal conclusion)
# ---------------------------------------------------------------------------

# Same wordlist/pattern src/anomaly/ and src/drivers/ tests already scan
# fixtures for (tests/test_anomaly_engine.py, tests/test_driver_engine.py).
# Reused verbatim here so EvidenceObject/Claim enforce the identical rule
# structurally, at construction time, rather than only via an external test
# scan. The "(?<!excluded )due to" exclusion preserves the same pre-existing
# idiom Step 3D copies from KPIResult.warnings verbatim (e.g. "N rows
# excluded due to missing/invalid delivery timestamps" is a mechanical
# data-quality note, not a causal claim about a KPI movement).
CAUSAL_LANGUAGE_PATTERN = re.compile(
    r"\b(caused by|causes|because of|(?<!excluded )due to|the reason (is|for)|as a result of|"
    r"black\s*friday|led to|driven by|drove the|responsible for)\b",
    re.IGNORECASE,
)


def contains_causal_language(text: str) -> bool:
    return bool(CAUSAL_LANGUAGE_PATTERN.search(text))
