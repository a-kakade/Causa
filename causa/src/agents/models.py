"""
models.py — Step 5: data structures for the Secure Multi-Agent Investigation
Engine.

Same posture as src/kpi/models.py, src/anomaly/models.py, src/drivers/models.py,
src/evidence/schema.py: this module holds definitions only -- no orchestration,
no tool execution, no LLM calls. Every dataclass here is a plain, serializable
container an agent module builds and the Orchestrator threads through
InvestigationState.

NON-NEGOTIABLE PRINCIPLE (task's own words): LLM =/= quantitative truth. This
module enforces the structural half of that rule: HypothesisEvaluation and
ContradictionRecord require non-empty evidence_ids to be considered valid,
Hypothesis.statement/rationale text is scanned for causal language at
construction time, and the numeric-guardrail helpers here are the single
source of truth both the tests and confidence_judge.py call into.

Three of the six agents in this package are LLM-backed: HYPOTHESIS, EVIDENCE,
and COUNTER_EVIDENCE make real calls to an LLM (Groq-hosted, via
src/agents/llm_client.py -- chosen by the user for cost; the client
abstraction is provider-agnostic)
for the genuinely interpretive work the task explicitly allows an agent to do
("formulate hypotheses ... decide what evidence to request ... interpret
evidence ... identify alternative explanations ... summarize evidence"). The
other three -- ORCHESTRATOR, CAUSAL_SELECTOR, CONFIDENCE_JUDGE -- are
DETERMINISTIC, rule-based Python modules with NO live LLM call anywhere,
per the task's own explicit language for each ("The Orchestrator must NOT
independently generate business conclusions"; "Never allow the LLM to declare
causality"; "Implement this primarily as a deterministic policy engine").

This split is the concrete mechanism for the NON-NEGOTIABLE PRINCIPLE above.
An LLM call being in the loop for 3 agents does NOT weaken "LLM =/= quantitative
truth" -- every number the LLM-backed agents cite must already exist in
governed evidence (build_allowed_numbers()/validate_numeric_claims() below,
called on every LLM-generated string before it is allowed into
InvestigationState), every causal-sounding claim is rejected at dataclass
construction time regardless of which agent produced it, and the two agents
that actually decide "how confident are we" and "which analytical method is
justified" never see a token of LLM output -- they only see already-validated,
already-guardrailed dataclasses from this module. TelemetryRecord.model stays
the literal string "deterministic_rule_engine_v1" for the three deterministic
agents' own audit records (they truly spend 0 tokens); the three LLM-backed
agents' TelemetryRecords instead carry the real `response.model` id (e.g.
"openai/gpt-oss-20b", agents.llm_client.DEFAULT_MODEL) and real token/cost numbers assembled by
src/agents/telemetry.py from the LLM provider's own `usage` field. See
docs/MULTI_AGENT_ARCHITECTURE.md
§0 for the full rationale, including why this is a stronger, not weaker,
security posture: src/tools/gateway.py enforces RBAC/tool permissions at the
tool-execution chokepoint regardless of whether a human, deterministic code,
or an LLM decided to request that tool -- so a compromised or confused model
can propose anything, but can never execute anything outside its agent role's
governed tool allowlist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# RBAC roles (task §6)
# ---------------------------------------------------------------------------

class RequesterRole(str, Enum):
    """The three roles task §6 requires, at minimum. Mapped to the EXISTING
    SecurityClassification scale (PUBLIC_ANALYTICAL/INTERNAL/RESTRICTED) in
    src/tools/policy.py -- never redefined as a parallel clearance system.
    See docs/AGENT_SECURITY.md §2 for the mapping rationale (in short:
    EXECUTIVE is capped at PUBLIC_ANALYTICAL so seller-level INTERNAL detail
    can never leak into an executive-facing investigation, per task §6's own
    example)."""
    EXECUTIVE = "EXECUTIVE"
    ANALYST = "ANALYST"
    INTERNAL = "INTERNAL"


# ---------------------------------------------------------------------------
# Agent roles (task §2/§3 — used for Tool Gateway authorization)
# ---------------------------------------------------------------------------

class AgentRole(str, Enum):
    ORCHESTRATOR = "ORCHESTRATOR"
    HYPOTHESIS = "HYPOTHESIS"
    EVIDENCE = "EVIDENCE"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"
    CAUSAL_SELECTOR = "CAUSAL_SELECTOR"
    CONFIDENCE_JUDGE = "CONFIDENCE_JUDGE"


# ---------------------------------------------------------------------------
# Investigation state machine (task §8)
# ---------------------------------------------------------------------------

class InvestigationStatus(str, Enum):
    PLANNED = "PLANNED"
    SECURITY_VALIDATED = "SECURITY_VALIDATED"
    HYPOTHESES_GENERATED = "HYPOTHESES_GENERATED"
    EVIDENCE_COLLECTION = "EVIDENCE_COLLECTION"
    COUNTER_EVIDENCE = "COUNTER_EVIDENCE"
    CONTRADICTION_ANALYSIS = "CONTRADICTION_ANALYSIS"
    METHOD_SELECTION = "METHOD_SELECTION"
    CONFIDENCE_EVALUATION = "CONFIDENCE_EVALUATION"
    COMPLETED = "COMPLETED"
    # Terminal alternatives (task §8)
    ABSTAINED = "ABSTAINED"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    SECURITY_BLOCKED = "SECURITY_BLOCKED"


TERMINAL_STATUSES = frozenset({
    InvestigationStatus.COMPLETED, InvestigationStatus.ABSTAINED,
    InvestigationStatus.NEEDS_CLARIFICATION, InvestigationStatus.BUDGET_EXCEEDED,
    InvestigationStatus.SECURITY_BLOCKED,
})


# ---------------------------------------------------------------------------
# Analytical method selection (task §1's E section)
# ---------------------------------------------------------------------------

class AnalyticalMethod(str, Enum):
    T1_DESCRIPTIVE = "T1_DESCRIPTIVE"
    T2_ARITHMETIC = "T2_ARITHMETIC"
    T3_QUASI_EXPERIMENTAL = "T3_QUASI_EXPERIMENTAL"
    T4_EXPERIMENTAL = "T4_EXPERIMENTAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Ordinal rank used by causal_selector.py's downgrade rule (task §5/§13: a
# strong contradiction or a failed assumption downgrades the claim by moving
# to a lower-numbered method here, never upward).
METHOD_RANK: dict[AnalyticalMethod, int] = {
    AnalyticalMethod.INSUFFICIENT_DATA: -1,
    AnalyticalMethod.T1_DESCRIPTIVE: 1,
    AnalyticalMethod.T2_ARITHMETIC: 2,
    AnalyticalMethod.T3_QUASI_EXPERIMENTAL: 3,
    AnalyticalMethod.T4_EXPERIMENTAL: 4,
}


# ---------------------------------------------------------------------------
# Confidence (task §1's F section)
# ---------------------------------------------------------------------------

class ConfidenceLevel(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    ABSTAIN = "ABSTAIN"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


# ---------------------------------------------------------------------------
# Evidence classification / contradiction (task §11/§12)
# ---------------------------------------------------------------------------

class EvidenceClassification(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    CONTEXT = "CONTEXT"
    INSUFFICIENT = "INSUFFICIENT"


class ContradictionSeverity(str, Enum):
    NONE = "NONE"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


CONTRADICTION_SEVERITY_RANK = {
    ContradictionSeverity.NONE: 0, ContradictionSeverity.WEAK: 1,
    ContradictionSeverity.MODERATE: 2, ContradictionSeverity.STRONG: 3,
}


# ---------------------------------------------------------------------------
# Causal-language guardrail (task §13) — stricter superset of
# evidence.models.CAUSAL_LANGUAGE_PATTERN, applied to every agent-generated
# string (hypothesis statements, evidence rationale, summaries), not just
# EvidenceObject.claim.
# ---------------------------------------------------------------------------

UNSUPPORTED_CAUSAL_PATTERN = re.compile(
    r"\b(caused?( by)?|causes?|because of|(?<!excluded )due to|the reason (is|for)|as a result of|"
    r"led to|driven by|drove the|responsible for|resulted in)\b",
    re.IGNORECASE,
)

# Explicitly allowed hedged vocabulary (task §13) — never flagged even though
# some share substrings with the KPI/driver domain. Kept here as documentation
# of intent; UNSUPPORTED_CAUSAL_PATTERN's own terms are chosen to never match
# these phrases.
ALLOWED_HEDGED_PHRASES = (
    "associated with", "consistent with", "coincides with",
    "contributed mathematically", "supports the hypothesis", "may be associated with",
    # Added in Step 6 (src/causal/language_gate.py) -- verified against
    # UNSUPPORTED_CAUSAL_PATTERN above to contain no "mathematically"/
    # "explain" token, so it can never be spuriously flagged.
    "mathematically explains",
)


def contains_unsupported_causal_language(text: str) -> bool:
    return bool(UNSUPPORTED_CAUSAL_PATTERN.search(text))


def assert_no_unsupported_causal_language(text: str, field_name: str) -> str:
    if contains_unsupported_causal_language(text):
        raise ValueError(
            f"{field_name} contains unsupported causal language: {text!r}. Agents may describe an "
            "association, a mathematical contribution, or a hypothesis -- never assert causation unless "
            "a validated T3/T4 method licenses it (task §13)."
        )
    return text


# ---------------------------------------------------------------------------
# Hypothesis (task §1's B section / §10)
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    """task §10: every hypothesis must identify driver/dimension/expected
    evidence/falsification evidence, and diversity is enforced across those
    same four axes by hypothesis_agent.py (never five paraphrases of one
    idea)."""
    hypothesis_id: str
    statement: str                       # hedged, never phrased as an established cause (task §1B)
    driver: str                          # e.g. "volume", "price", "mix", "delivery", "geography"
    dimension: str                       # e.g. "orders", "aov", "product_category", "customer_state"
    mechanism: str                       # short phrase distinguishing *how* this driver would matter
    expected_evidence: list[str] = field(default_factory=list)       # what would SUPPORT this hypothesis
    falsification_evidence: list[str] = field(default_factory=list)  # what would CONTRADICT it
    evidence_types_expected: list[str] = field(default_factory=list)  # EvidenceType values this hypothesis draws on
    status: str = "PROPOSED"

    def __post_init__(self) -> None:
        assert_no_unsupported_causal_language(self.statement, "Hypothesis.statement")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Counter-evidence (task §1's D section / §12)
# ---------------------------------------------------------------------------

@dataclass
class CounterEvidenceReport:
    hypothesis_id: str
    supporting_evidence: list[str] = field(default_factory=list)    # evidence_ids
    contradicting_evidence: list[str] = field(default_factory=list)  # evidence_ids
    unresolved_questions: list[str] = field(default_factory=list)
    contradiction_level: ContradictionSeverity = ContradictionSeverity.NONE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["contradiction_level"] = self.contradiction_level.value
        return d


@dataclass
class ContradictionRecord:
    """task §12's exact shape."""
    contradiction_id: str
    hypothesis_id: str
    supporting_evidence: list[str] = field(default_factory=list)
    contradicting_evidence: list[str] = field(default_factory=list)
    severity: ContradictionSeverity = ContradictionSeverity.NONE
    unresolved: bool = True

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["severity"] = self.severity.value
        return d


# ---------------------------------------------------------------------------
# Classified evidence (task §11) — never rewrites the original evidence
# ---------------------------------------------------------------------------

@dataclass
class ClassifiedEvidence:
    """`source_evidence` holds the ORIGINAL EvidenceObject/EvidenceResult
    object, untouched -- classification is metadata ABOUT the evidence, never
    a rewrite of it (task §11: "Do not rewrite evidence numerically.")."""
    evidence_id: str
    hypothesis_id: str
    classification: EvidenceClassification
    rationale: str
    source_evidence: Any   # evidence.schema.EvidenceObject | EvidenceResult — kept opaque here to avoid a
                            # src/agents -> src/evidence type-only import cycle risk; callers narrow it.

    def __post_init__(self) -> None:
        assert_no_unsupported_causal_language(self.rationale, "ClassifiedEvidence.rationale")

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id, "hypothesis_id": self.hypothesis_id,
            "classification": self.classification.value, "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Method selection (task §1's E section)
# ---------------------------------------------------------------------------

@dataclass
class MethodSelection:
    hypothesis_id: str
    method: AnalyticalMethod
    justification: str
    downgraded: bool = False
    downgrade_reason: Optional[str] = None

    def __post_init__(self) -> None:
        assert_no_unsupported_causal_language(self.justification, "MethodSelection.justification")

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id, "method": self.method.value,
            "justification": self.justification, "downgraded": self.downgraded,
            "downgrade_reason": self.downgrade_reason,
        }


# ---------------------------------------------------------------------------
# Confidence result (task §1's F section) — must cite evidence (task §15)
# ---------------------------------------------------------------------------

@dataclass
class HypothesisResult:
    """The final per-hypothesis output object task §15 requires: status +
    confidence + evidence_ids. `evidence_ids` empty is INVALID for a
    SUPPORTED/CONTRADICTED status (checked by confidence_judge.py /
    tests/test_confidence.py), matching task §15's literal example."""
    hypothesis_id: str
    status: str                              # SUPPORTED | CONTRADICTED | INCONCLUSIVE
    confidence: ConfidenceLevel
    evidence_ids: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    method: Optional[AnalyticalMethod] = None
    contradiction_severity: ContradictionSeverity = ContradictionSeverity.NONE

    def is_valid(self) -> bool:
        """task §15: 'No evidence IDs: INVALID RESULT' — applies to any
        substantive (non-abstaining) conclusion."""
        if self.status in ("SUPPORTED", "CONTRADICTED") and not self.evidence_ids:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id, "status": self.status,
            "confidence": self.confidence.value, "evidence_ids": list(self.evidence_ids),
            "reasons": list(self.reasons), "method": self.method.value if self.method else None,
            "contradiction_severity": self.contradiction_severity.value,
        }


# ---------------------------------------------------------------------------
# Budgets (task §9)
# ---------------------------------------------------------------------------

class BudgetExceeded(Exception):
    def __init__(self, budget_name: str, limit: int, attempted: int):
        self.budget_name, self.limit, self.attempted = budget_name, limit, attempted
        super().__init__(f"Budget {budget_name!r} exceeded: limit={limit}, attempted={attempted}")


@dataclass
class Budgets:
    max_iterations: int = 20
    max_agent_calls: int = 120
    max_tool_calls: int = 200
    max_retrieval_calls: int = 60
    max_tokens: int = 200_000          # scaffolding for a future LLM-backed version; unused (0 tokens) today
    max_latency_seconds: float = 60.0

    used_iterations: int = 0
    used_agent_calls: int = 0
    used_tool_calls: int = 0
    used_retrieval_calls: int = 0
    used_tokens: int = 0
    used_latency_seconds: float = 0.0

    def check(self, name: str) -> None:
        limit_attr, used_attr = f"max_{name}", f"used_{name}"
        limit, used = getattr(self, limit_attr), getattr(self, used_attr)
        if used >= limit:
            raise BudgetExceeded(name, limit, used + 1)

    def increment(self, name: str, amount: float = 1) -> None:
        self.check(name)
        used_attr = f"used_{name}"
        setattr(self, used_attr, getattr(self, used_attr) + amount)

    def exhausted(self) -> bool:
        return any(getattr(self, f"used_{n}") >= getattr(self, f"max_{n}") for n in
                   ("iterations", "agent_calls", "tool_calls", "retrieval_calls", "tokens", "latency_seconds"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Audit trace (task §19)
# ---------------------------------------------------------------------------

@dataclass
class AuditTraceEntry:
    agent_id: str
    agent_role: str
    timestamp: str
    input_state_hash: str
    tool_call: Optional[str]
    tool_arguments_hash: Optional[str]
    tool_result_ids: list[str] = field(default_factory=list)  # evidence_ids only, never raw content/PII
    output: str = ""                                          # short, non-PII summary, never raw review text
    token_usage: int = 0
    latency_ms: float = 0.0
    security_decision: str = "ALLOWED"                        # ALLOWED | BLOCKED | DENIED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cost / telemetry (task §20)
# ---------------------------------------------------------------------------

@dataclass
class TelemetryRecord:
    agent_role: str
    # Default is correct for ORCHESTRATOR/CAUSAL_SELECTOR/CONFIDENCE_JUDGE records
    # (truly 0 tokens spent — see module docstring). HYPOTHESIS/EVIDENCE/
    # COUNTER_EVIDENCE records overwrite this with the real response.model
    # (e.g. "claude-opus-5") and real usage from src/agents/telemetry.py.
    model: str = "deterministic_rule_engine_v1"
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost: float = 0.0
    tool_calls: int = 0
    retrieval_calls: int = 0
    agent_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Investigation state (task §7) — the ONLY place investigation progress lives.
# No agent may keep its own conversational memory across calls (task §7:
# "Do not use uncontrolled conversational memory.") — every agent function in
# this package is called with an explicit InvestigationState and returns a
# new/updated one; nothing is cached in a module-level variable or closure.
# ---------------------------------------------------------------------------

@dataclass
class InvestigationState:
    investigation_id: str
    requester_role: RequesterRole
    kpi_id: str
    period: str
    movement: dict[str, Any] = field(default_factory=dict)   # e.g. {"absolute": ..., "percentage": ...}
    hypotheses: list[Hypothesis] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    classified_evidence: list[ClassifiedEvidence] = field(default_factory=list)
    counter_evidence_reports: list[CounterEvidenceReport] = field(default_factory=list)
    contradictions: list[ContradictionRecord] = field(default_factory=list)
    selected_methods: list[MethodSelection] = field(default_factory=list)
    hypothesis_results: list[HypothesisResult] = field(default_factory=list)
    confidence: Optional[ConfidenceLevel] = None
    status: InvestigationStatus = InvestigationStatus.PLANNED
    budgets: Budgets = field(default_factory=Budgets)
    audit_trace: list[AuditTraceEntry] = field(default_factory=list)
    telemetry: list[TelemetryRecord] = field(default_factory=list)
    retrieval_insufficiency_events: list[dict[str, Any]] = field(default_factory=list)
    security_events: list[dict[str, Any]] = field(default_factory=list)
    status_history: list[str] = field(default_factory=lambda: [InvestigationStatus.PLANNED.value])

    def state_hash(self) -> str:
        """Cheap content hash used by AuditTraceEntry.input_state_hash — NOT a
        security control, just a debugging/reproducibility aid (same spirit
        as structured_adapter.py's evidence_id_for)."""
        import hashlib
        import json
        payload = json.dumps({
            "investigation_id": self.investigation_id, "status": self.status.value,
            "n_hypotheses": len(self.hypotheses), "n_evidence": len(self.evidence_ids),
            "n_contradictions": len(self.contradictions),
        }, sort_keys=True)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "investigation_id": self.investigation_id, "requester_role": self.requester_role.value,
            "kpi_id": self.kpi_id, "period": self.period, "movement": self.movement,
            "hypotheses": [h.to_dict() for h in self.hypotheses],
            "evidence_ids": list(self.evidence_ids),
            "classified_evidence": [c.to_dict() for c in self.classified_evidence],
            "counter_evidence_reports": [c.to_dict() for c in self.counter_evidence_reports],
            "contradictions": [c.to_dict() for c in self.contradictions],
            "selected_methods": [m.to_dict() for m in self.selected_methods],
            "hypothesis_results": [h.to_dict() for h in self.hypothesis_results],
            "confidence": self.confidence.value if self.confidence else None,
            "status": self.status.value, "budgets": self.budgets.to_dict(),
            "audit_trace": [a.to_dict() for a in self.audit_trace],
            "telemetry": [t.to_dict() for t in self.telemetry],
            "retrieval_insufficiency_events": list(self.retrieval_insufficiency_events),
            "security_events": list(self.security_events),
            "status_history": list(self.status_history),
        }


# ---------------------------------------------------------------------------
# Numeric guardrail (task §14)
# ---------------------------------------------------------------------------

_NUMBER_PATTERN = re.compile(r"[-+]?R?\$?\s?\d[\d,]*\.?\d*\s?%?")


def _parse_number_token(token: str) -> Optional[float]:
    cleaned = token.strip().replace("R$", "").replace("$", "").replace("%", "").replace(",", "").strip()
    if not cleaned or cleaned in ("+", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def extract_numeric_claims(text: str) -> list[float]:
    """Extracts every number-shaped token from agent-generated text. Deliberately
    liberal (currency/percent-formatted or bare) — validate_numeric_claims below
    decides what's actually a violation."""
    out = []
    for m in _NUMBER_PATTERN.finditer(text):
        v = _parse_number_token(m.group())
        if v is not None:
            out.append(v)
    return out


def build_allowed_numbers(evidence_objects: list[Any]) -> set[float]:
    """Builds the governed set of numbers any agent output may cite, from the
    ACTUAL evidence objects passed in (task §14: 'Construct allowed_numbers
    from evidence objects'). Pulls .value.value, and any numeric entries in
    .metadata, off every evidence-shaped object; tolerant of both
    EvidenceObject (pydantic) and EvidenceResult / plain dicts."""
    allowed: set[float] = set()

    def _add(v: Any) -> None:
        if isinstance(v, bool):
            return
        if isinstance(v, (int, float)):
            allowed.add(round(float(v), 6))

    for ev in evidence_objects:
        value_obj = getattr(ev, "value", None)
        if value_obj is not None:
            _add(getattr(value_obj, "value", None))
        metadata = getattr(ev, "metadata", None) or {}
        for v in metadata.values():
            _add(v)
        rank = metadata.get("rank") if isinstance(metadata, dict) else None
        _add(rank)
    return allowed


def validate_numeric_claims(text: str, allowed_numbers: set[float], tolerance: float = 0.0005,
                             minimum_magnitude: float = 20.0) -> tuple[bool, list[float]]:
    """task §14: every quantitative value in agent output must trace back to
    `allowed_numbers`.

    Two independent exclusion rules decide what counts as a "claim" worth
    checking, not magnitude alone: a token carrying a currency sign ('R$'/
    '$'), a percent sign, or a decimal point is ALWAYS checked regardless of
    size (a percentage like "52.1%" or a ratio like "0.42" is a real claim
    even though it's numerically small) -- only a BARE, marker-free small
    integer (no currency/percent/decimal point) below `minimum_magnitude`
    (default 20 -- covers hypothesis numbering "H1", rank "#3", "top 5
    segments") is treated as a structural label, not a business number.

    `tolerance` is a RELATIVE fraction (default 0.05%, i.e. 0.0005) applied
    per-allowed-number, with an absolute floor of 0.01 so near-zero allowed
    values (e.g. a small ratio) still tolerate ordinary floating-point/
    rounding noise. A relative tolerance that scaled with a *loose* fraction
    (an earlier version of this function used 1.5%) would let a fabricated
    number that merely landed in the same order of magnitude as a real one
    (e.g. "R$999,999.99" when the real absolute change is "R$346,051.94")
    slip through silently -- 0.05% keeps the check meaningfully tight while
    still tolerating "52.1%" against a computed 52.09903901787393.
    Returns (ok, violating_numbers)."""
    violations = []
    for m in _NUMBER_PATTERN.finditer(text):
        token = m.group()
        v = _parse_number_token(token)
        if v is None:
            continue
        has_marker = ("$" in token) or ("%" in token) or ("." in token)
        if not has_marker and abs(v) < minimum_magnitude and v == int(v):
            continue   # bare small integer, no currency/percent/decimal marker — a label, not a claim
        if v == int(v) and 1900 <= v <= 2100:
            continue   # a 4-digit calendar year (e.g. "November 2017", the investigation's own
                       # period) — a date reference, not a quantitative business claim. NOT gated on
                       # `has_marker`: a year at the end of a sentence ("...in November 2017.") has
                       # its token's trailing period absorbed by _NUMBER_PATTERN as if it were a
                       # decimal point, which would otherwise spuriously set has_marker=True. Real
                       # false-positive observed in a live run: a hypothesis naming its own
                       # investigation period was rejected outright because "2017" wasn't itself in
                       # allowed_numbers — fixed here rather than loosening the tolerance check that
                       # catches genuine fabrications.
        if any(abs(v - a) <= max(tolerance * abs(a), 0.01) for a in allowed_numbers):
            continue
        violations.append(v)
    return (len(violations) == 0), violations


class NumericValidationFailed(Exception):
    def __init__(self, text: str, violating_numbers: list[float]):
        self.text, self.violating_numbers = text, violating_numbers
        super().__init__(f"NUMERIC_VALIDATION_FAILED: {violating_numbers} not found in allowed_numbers for {text!r}")
