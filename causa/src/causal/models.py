"""
models.py — Step 6: data structures for the governed causal-analysis /
evidence-tier engine.

Same posture as src/kpi/models.py, src/drivers/models.py,
src/evidence/schema.py, src/agents/models.py: this module holds definitions
only -- no eligibility logic, no method selection, no estimation, no LLM
calls. Every dataclass here is a plain, serializable container the rest of
src/causal/ builds and returns.

NON-NEGOTIABLE PRINCIPLE (task's own words): "LLM proposes hypotheses.
Deterministic/statistical systems test them. LLM cannot declare causality."
CausalHypothesis.__post_init__ enforces the structural half of that rule the
same way agents.models.Hypothesis already does for Step 5: `proposed_mechanism`
is scanned for causal language at construction time, reusing
agents.models.assert_no_unsupported_causal_language rather than defining a
third copy of that regex (two already exist in the repo -- evidence.models'
narrower CAUSAL_LANGUAGE_PATTERN and agents.models' stricter superset; see
docs/CAUSAL_GOVERNANCE.md §3 for why this module reuses the superset).

Three distinct "tier" concepts already exist or are introduced in this repo,
and must never be conflated (docs/CAUSAL_ARCHITECTURE.md §2 has the full
mapping table):

  - evidence.models.EvidenceTier    -- how was ONE evidence item produced
                                       (observation / arithmetic / statistical)?
  - agents.models.AnalyticalMethod  -- what rigor label can Step 5's
                                       LLM-driven hypothesis pipeline attach to
                                       a hypothesis' SUPPORT, given only which
                                       evidence tiers back it?
  - causal.models.CausalTier (here) -- what is the strongest evidence tier a
                                       SPECIFIC causal hypothesis + SPECIFIC
                                       method run can defensibly support,
                                       after eligibility screening and method
                                       diagnostics?

CausalTier is deliberately its own enum, not a reuse of either of the other
two -- a DiD run can compute a T3-shaped estimate that gets capped back down
to T1 because parallel trends failed, a judgment neither of the other two
enums has any vocabulary for.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional

from agents.models import assert_no_unsupported_causal_language

# ---------------------------------------------------------------------------
# Evidence tier this causal layer can award (task's four tiers, verbatim)
# ---------------------------------------------------------------------------


class CausalTier(str, Enum):
    T1_DESCRIPTIVE = "T1_DESCRIPTIVE"
    T2_ARITHMETIC = "T2_ARITHMETIC"
    T3_QUASI_EXPERIMENTAL = "T3_QUASI_EXPERIMENTAL"
    T4_EXPERIMENTAL = "T4_EXPERIMENTAL"


CAUSAL_TIER_RANK: dict[CausalTier, int] = {
    CausalTier.T1_DESCRIPTIVE: 1,
    CausalTier.T2_ARITHMETIC: 2,
    CausalTier.T3_QUASI_EXPERIMENTAL: 3,
    CausalTier.T4_EXPERIMENTAL: 4,
}


# ---------------------------------------------------------------------------
# Eligibility verdict (task's eligibility checker)
# ---------------------------------------------------------------------------


class EligibilityVerdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    PARTIALLY_ELIGIBLE = "PARTIALLY_ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    # A distinct, stricter verdict reserved for temporal-order failure (task's
    # "if temporal ordering is unreliable: CAUSAL_INELIGIBLE" section) -- kept
    # separate from plain INELIGIBLE so callers can distinguish "we cannot
    # even discuss causality here" from "we simply don't have enough data."
    CAUSAL_INELIGIBLE = "CAUSAL_INELIGIBLE"


# ---------------------------------------------------------------------------
# Method selection (task's seven methods, verbatim)
# ---------------------------------------------------------------------------


class CausalMethod(str, Enum):
    DESCRIPTIVE_ASSOCIATION = "DESCRIPTIVE_ASSOCIATION"
    PVM = "PVM"
    DIFFERENCE_IN_DIFFERENCES = "DIFFERENCE_IN_DIFFERENCES"
    INTERRUPTED_TIME_SERIES = "INTERRUPTED_TIME_SERIES"
    CAUSAL_IMPACT = "CAUSAL_IMPACT"
    EXPERIMENTAL_RESULT = "EXPERIMENTAL_RESULT"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Abstention outcomes (task's five statuses, verbatim)
# ---------------------------------------------------------------------------


class CausalStatus(str, Enum):
    CAUSAL_SUPPORTED = "CAUSAL_SUPPORTED"
    CAUSAL_INSUFFICIENT = "CAUSAL_INSUFFICIENT"
    CAUSAL_REJECTED = "CAUSAL_REJECTED"
    DESCRIPTIVE_ONLY = "DESCRIPTIVE_ONLY"
    ARITHMETIC_ONLY = "ARITHMETIC_ONLY"


# ---------------------------------------------------------------------------
# Eligibility check plumbing
# ---------------------------------------------------------------------------


class CheckResultStatus(str, Enum):
    PASS = "PASS"
    SOFT_FAIL = "SOFT_FAIL"
    HARD_FAIL = "HARD_FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass
class CausalHypothesis:
    """The LLM (or a human, or a converter from a Step 5 Hypothesis) proposes
    this. Nothing about this dataclass's existence licenses a causal claim --
    `proposed_method` is a non-binding suggestion; method_selector.py may
    override it entirely based on real eligibility/diagnostics."""

    hypothesis_id: str
    treatment: str  # a governed kpi_id, or a dimension name (with treatment_dimension/treatment_group_value set)
    outcome: str  # a governed kpi_id
    unit_of_analysis: str  # e.g. "order" | "customer_state" | "product_category" | "seller" | "month"
    treatment_period: dict[str, str]  # {"start": "YYYY-MM", "end": "YYYY-MM"} or {"date": "YYYY-MM-DD"}
    outcome_period: dict[str, str]
    proposed_mechanism: str  # hedged, non-causal phrasing -- validated at construction time
    required_data: list[str] = field(default_factory=list)  # kpi_ids/dimensions this hypothesis needs
    proposed_method: CausalMethod = CausalMethod.DESCRIPTIVE_ASSOCIATION
    assumptions: list[str] = field(default_factory=list)
    treatment_dimension: Optional[str] = None  # e.g. "customer_state"; None for a time-only treatment
    treatment_group_value: Optional[str] = None  # e.g. "SP" -- which value of treatment_dimension is "treated"
    control_group_value: Optional[str] = None  # e.g. "all_other_states"
    source: str = "MANUAL"  # "MANUAL" | "STEP5_HYPOTHESIS" -- where this hypothesis was proposed from

    def __post_init__(self) -> None:
        assert_no_unsupported_causal_language(self.proposed_mechanism, "CausalHypothesis.proposed_mechanism")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["proposed_method"] = self.proposed_method.value
        return d


@dataclass
class CheckResult:
    check_name: str
    status: CheckResultStatus
    reason: str
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class EligibilityReport:
    hypothesis_id: str
    verdict: EligibilityVerdict
    checks: list[CheckResult]  # always exactly the 12 canonical checks, in fixed order
    hard_fail_checks: list[str] = field(default_factory=list)
    soft_fail_checks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "verdict": self.verdict.value,
            "checks": [c.to_dict() for c in self.checks],
            "hard_fail_checks": list(self.hard_fail_checks),
            "soft_fail_checks": list(self.soft_fail_checks),
        }


@dataclass
class MethodSelectionResult:
    hypothesis_id: str
    method: CausalMethod
    why_selected: str
    why_other_methods_rejected: dict[str, str]  # always all 6 non-selected CausalMethod values as keys
    required_assumptions: list[str]
    eligibility_verdict: EligibilityVerdict

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "method": self.method.value,
            "why_selected": self.why_selected,
            "why_other_methods_rejected": dict(self.why_other_methods_rejected),
            "required_assumptions": list(self.required_assumptions),
            "eligibility_verdict": self.eligibility_verdict.value,
        }


@dataclass
class DiagnosticResult:
    diagnostic_name: str
    passed: bool
    statistic: Optional[float]
    threshold: Optional[float]
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ConfounderReport:
    """Emitted by diagnostics.detect_known_confounders. `controlled_for`
    defaults False and is never silently flipped True anywhere in this
    package (task's own words: "Do not claim they were controlled merely
    because they exist in the data.") -- see diagnostics.py's
    report_confounders_never_controlled for the literal enforcement."""

    name: str
    known_or_suspected: str  # "KNOWN" | "SUSPECTED"
    detail: str
    controlled_for: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CausalResult:
    hypothesis_id: str
    method: CausalMethod
    evidence_tier: CausalTier
    status: CausalStatus
    estimate: Optional[dict[str, Any]]
    uncertainty: Optional[dict[str, Any]]
    assumptions: list[str]
    diagnostics: list[DiagnosticResult]
    confounders: list[str]
    evidence_ids: list[str]
    limitations: list[str]
    causal_claim_allowed: bool
    eligibility_report: EligibilityReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id,
            "method": self.method.value,
            "evidence_tier": self.evidence_tier.value,
            "status": self.status.value,
            "estimate": self.estimate,
            "uncertainty": self.uncertainty,
            "assumptions": list(self.assumptions),
            "diagnostics": [d.to_dict() for d in self.diagnostics],
            "confounders": list(self.confounders),
            "evidence_ids": list(self.evidence_ids),
            "limitations": list(self.limitations),
            "causal_claim_allowed": self.causal_claim_allowed,
            "eligibility_report": self.eligibility_report.to_dict(),
        }
