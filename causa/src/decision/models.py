"""
models.py — Step 7: data structures for the Decision & Action Intelligence
Engine.

Same posture as src/causal/models.py, src/agents/models.py, src/drivers/models.py:
this module holds definitions only -- no ontology loading, no candidate
generation, no scoring, no LLM calls. Every dataclass here is a plain,
serializable container the rest of src/decision/ builds and returns.

NON-NEGOTIABLE PRINCIPLE (mirrors task's own words for Step 5/6): a
recommendation's NUMBERS -- impact, confidence, controllability, effort,
priority -- are never an LLM's opinion. They are computed by deterministic
engines (impact_estimator.py, confidence_engine.py, scoring.py) from real
upstream data or explicit configuration, and any field that could not be
computed is marked "unknown"/None rather than fabricated. An LLM may only
ever touch two things in this package: how a candidate action is PHRASED
(candidate_generator.py) and how an already-computed DecisionResult is
VERBALIZED into prose (explanation.py) -- never what the numbers ARE.

ActionRecommendation.action_justified_by_evidence is this package's analog
of causal.models.CausalResult.causal_claim_allowed: a hardcoded boolean
field, never a soft convention, set only from an upstream CausalResult's own
causal_claim_allowed when the DriverSignal actually traces back to one
(source == "STEP6_CAUSAL_RESULT"). A recommendation backed only by a T1/T2
descriptive/arithmetic finding (or a hand-authored DriverSignal) is not
thereby invalid -- it just cannot claim causal justification, exactly the
distinction Step 6 draws for CausalResult itself.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

from agents.models import assert_no_unsupported_causal_language

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DriverCategory(str, Enum):
    FULFILLMENT_LOGISTICS = "FULFILLMENT_LOGISTICS"
    PRICING_PRODUCT_MIX = "PRICING_PRODUCT_MIX"
    DEMAND_VOLUME = "DEMAND_VOLUME"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    GEOGRAPHY = "GEOGRAPHY"
    OTHER = "OTHER"  # config may declare a driver_category string not in this closed set;
                      # loaders fall back to OTHER rather than raising -- the ontology YAML,
                      # not this enum, is the source of truth for what categories exist.


class ConstraintStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    BLOCKED = "BLOCKED"


_CONSTRAINT_STATUS_RANK = {ConstraintStatus.PASS: 0, ConstraintStatus.WARNING: 1, ConstraintStatus.BLOCKED: 2}


class ConstraintSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendationTier(str, Enum):
    TOP = "TOP"
    ALTERNATIVE = "ALTERNATIVE"
    CONDITIONAL = "CONDITIONAL"  # blocked, but exposed as a conditional option (task's own allowance)
    BLOCKED = "BLOCKED"


class DataSource(str, Enum):
    """Where a number in an ExpectedImpact/DriverSignal came from. UNKNOWN is
    a legitimate, expected value -- never a bug -- whenever upstream data is
    genuinely missing. There is deliberately no "LLM_GENERATED" member: no
    numeric field in this package may honestly report an LLM as its source."""
    HISTORICAL_ESTIMATE = "HISTORICAL_ESTIMATE"
    STEP6_CAUSAL_RESULT = "STEP6_CAUSAL_RESULT"
    STEP5_HYPOTHESIS_RESULT = "STEP5_HYPOTHESIS_RESULT"
    ONTOLOGY_DEFAULT = "ONTOLOGY_DEFAULT"
    BUSINESS_CONTEXT = "BUSINESS_CONTEXT"
    UNKNOWN = "UNKNOWN"


class GeneratedBy(str, Enum):
    DETERMINISTIC_TEMPLATE = "DETERMINISTIC_TEMPLATE"
    LLM_PHRASED_SCHEMA_VALIDATED = "LLM_PHRASED_SCHEMA_VALIDATED"


# ---------------------------------------------------------------------------
# Input contract: a driver signal from Step 3D/5/6, or hand-authored
# ---------------------------------------------------------------------------


@dataclass
class DriverSignal:
    """The one input contract every Step 7 pipeline run starts from. Never
    constructed with fabricated numbers -- a caller (or src/decision/bridge.py)
    that cannot honestly populate a numeric field must leave it None, not
    guess. business_context is always explicit and caller-supplied: no
    upstream Step 5/6 object carries real-world budget/inventory/capacity
    facts, so this package never infers them."""

    driver: str
    driver_category: str
    kpi_id: str
    period: str
    observed_change_pct: Optional[float] = None
    observed_change_absolute: Optional[float] = None
    addressable_population: Optional[float] = None
    addressable_population_source: str = DataSource.UNKNOWN.value
    historical_estimated_effect: Optional[float] = None
    historical_effect_source: str = DataSource.UNKNOWN.value
    driver_confidence: Optional[float] = None  # 0-1, from upstream Step 5/6 evidence, or None
    causal_claim_allowed: Optional[bool] = None  # echoed from a bridged CausalResult, else None
    causal_result_id: Optional[str] = None
    source: str = "MANUAL"  # "MANUAL" | "STEP5_HYPOTHESIS_RESULT" | "STEP6_CAUSAL_RESULT"
    business_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Expected impact -- the "never fabricate" object (task's Impact Estimator)
# ---------------------------------------------------------------------------


@dataclass
class ExpectedImpact:
    metric: str
    estimated_effect: Optional[float]
    effect_unit: str  # e.g. "pp" | "pct" | "absolute_orders" | "currency"
    addressable_population: Optional[float]
    confidence: Optional[float]
    calculated_impact: Optional[float]  # estimated_effect * addressable_population * confidence, or None
    revenue_impact: Optional[float]  # only populated when monetary inputs exist, else None
    effect_source: str
    population_source: str
    confidence_basis: str
    is_estimable: bool  # False whenever any required input was missing

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Constraint engine outputs
# ---------------------------------------------------------------------------


@dataclass
class ConstraintCheck:
    constraint: str
    status: ConstraintStatus
    details: str
    severity: ConstraintSeverity

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        d["severity"] = self.severity.value
        return d


def overall_constraint_status(checks: list[ConstraintCheck]) -> ConstraintStatus:
    """Worst of {BLOCKED > WARNING > PASS}. An empty check list (an action
    declared no relevant_constraints in the ontology) is PASS -- there is
    nothing to fail."""
    if not checks:
        return ConstraintStatus.PASS
    return max((c.status for c in checks), key=lambda s: _CONSTRAINT_STATUS_RANK[s])


# ---------------------------------------------------------------------------
# Monitoring plan
# ---------------------------------------------------------------------------


@dataclass
class MonitoringTarget:
    kpi: str
    direction: str  # "increase" | "decrease" | "stabilize"
    expected_effect: Optional[float]
    target: str  # a computed target string, or the literal sentinel "unknown"
    window: str
    warning_threshold: Optional[float]
    stop_condition: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Score breakdown -- the explicit, non-LLM-opinion factors (task's
# determinism/explainability requirement)
# ---------------------------------------------------------------------------


@dataclass
class ScoreBreakdown:
    confidence_factors: dict[str, float]
    confidence_weights: dict[str, float]
    confidence_score: float
    controllability_score: float
    controllability_basis: str
    effort_score: float
    effort_basis: str
    priority_formula: str
    priority_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# The core decision object
# ---------------------------------------------------------------------------


@dataclass
class ActionRecommendation:
    recommendation_id: str
    driver: str
    driver_category: str
    controllable_lever: str
    possible_action: str
    expected_impact: ExpectedImpact
    owner: str
    constraints: list[ConstraintCheck]
    controllability: float
    effort: float
    priority_score: float
    monitoring_kpis: list[MonitoringTarget]
    rationale: str
    assumptions: list[str]
    score_breakdown: ScoreBreakdown
    tier: RecommendationTier
    ranking_explanation: list[str]
    action_justified_by_evidence: bool
    generated_by: GeneratedBy
    source_driver_signal_id: str

    def __post_init__(self) -> None:
        assert_no_unsupported_causal_language(self.possible_action, "ActionRecommendation.possible_action")
        assert_no_unsupported_causal_language(self.rationale, "ActionRecommendation.rationale")

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_id": self.recommendation_id,
            "driver": self.driver,
            "driver_category": self.driver_category,
            "controllable_lever": self.controllable_lever,
            "possible_action": self.possible_action,
            "expected_impact": self.expected_impact.to_dict(),
            "owner": self.owner,
            "constraints": [c.to_dict() for c in self.constraints],
            "controllability": self.controllability,
            "effort": self.effort,
            "priority_score": self.priority_score,
            "monitoring_kpis": [m.to_dict() for m in self.monitoring_kpis],
            "rationale": self.rationale,
            "assumptions": list(self.assumptions),
            "score_breakdown": self.score_breakdown.to_dict(),
            "tier": self.tier.value,
            "ranking_explanation": list(self.ranking_explanation),
            "action_justified_by_evidence": self.action_justified_by_evidence,
            "generated_by": self.generated_by.value,
            "source_driver_signal_id": self.source_driver_signal_id,
        }


# ---------------------------------------------------------------------------
# Pipeline result
# ---------------------------------------------------------------------------


@dataclass
class DecisionResult:
    request_id: str
    driver_signal: DriverSignal
    top_recommendation: Optional[ActionRecommendation]
    alternatives: list[ActionRecommendation]
    conditional: list[ActionRecommendation]
    blocked: list[ActionRecommendation]
    all_candidates_evaluated: int
    pipeline_trace: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "driver_signal": self.driver_signal.to_dict(),
            "top_recommendation": self.top_recommendation.to_dict() if self.top_recommendation else None,
            "alternatives": [r.to_dict() for r in self.alternatives],
            "conditional": [r.to_dict() for r in self.conditional],
            "blocked": [r.to_dict() for r in self.blocked],
            "all_candidates_evaluated": self.all_candidates_evaluated,
            "pipeline_trace": list(self.pipeline_trace),
        }
