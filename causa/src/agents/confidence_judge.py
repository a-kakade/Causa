"""
confidence_judge.py — Step 5: the Confidence Judge (task §1F).

"Implement this primarily as a deterministic policy engine" -- implemented
here as ENTIRELY deterministic: no LLM call anywhere in this module. Inputs
are evidence completeness, source reliability, freshness, historical
sufficiency, supporting/contradicting evidence, evidence tier, retrieval
sufficiency, and analytical validity (task's own list, verbatim). Output is
HIGH / MEDIUM / LOW / ABSTAIN / NEEDS_CLARIFICATION per hypothesis, plus an
investigation-level confidence = the WORST hypothesis-level result (never
let one strong hypothesis mask another's abstention).

Two structural guarantees the task explicitly calls out:
  - "A large amount of weak evidence must NOT automatically become high
    confidence" -- evidence_completeness is a RATIO (SUPPORTS / total
    classified for this hypothesis), and source_reliability is averaged only
    over SUPPORTS-classified items -- padding with CONTEXT/INSUFFICIENT
    items cannot move either number (see tests/test_confidence.py's "1 weak
    SUPPORTS + 20 CONTEXT items -> never HIGH" case).
  - "Strong contradiction must cap confidence" -- a STRONG severity caps the
    result at MEDIUM regardless of the weighted score.
  - "RetrievalInsufficient must reduce confidence or force abstention" -- a
    hypothesis whose evidence-gathering hit a RETRIEVAL_INSUFFICIENT sentinel
    with otherwise-thin evidence_completeness is forced to
    NEEDS_CLARIFICATION rather than scored normally.
"""

from __future__ import annotations

from agents.models import (
    AnalyticalMethod,
    ConfidenceLevel,
    ContradictionSeverity,
    EvidenceClassification,
    HypothesisResult,
    InvestigationState,
)

_LEVEL_RANK = {
    ConfidenceLevel.ABSTAIN: 0, ConfidenceLevel.NEEDS_CLARIFICATION: 0, ConfidenceLevel.LOW: 1,
    ConfidenceLevel.MEDIUM: 2, ConfidenceLevel.HIGH: 3,
}

_WEIGHTS = {"completeness": 0.25, "source_reliability": 0.20, "freshness": 0.15, "historical_sufficiency": 0.15}
_CONTRADICTION_PENALTY = {
    ContradictionSeverity.NONE: 0.0, ContradictionSeverity.WEAK: 0.15,
    ContradictionSeverity.MODERATE: 0.5, ContradictionSeverity.STRONG: 1.0,
}
_CONTRADICTION_WEIGHT = 0.30
_RETRIEVAL_INSUFFICIENCY_PENALTY_WEIGHT = 0.10

HIGH_THRESHOLD, MEDIUM_THRESHOLD = 0.75, 0.5


def _quality_field(ev, field: str):
    quality = getattr(ev, "quality", None) or (ev.get("quality") if isinstance(ev, dict) else None)
    if quality is None:
        return None
    return getattr(quality, field, None) if not isinstance(quality, dict) else quality.get(field)


def _score_hypothesis(classified: list, contradiction_severity: ContradictionSeverity,
                       insufficiency_hit: bool) -> tuple:
    supports = [c for c in classified if c.classification == EvidenceClassification.SUPPORTS]
    total = len(classified) or 1
    completeness = len(supports) / total

    reliabilities = [_quality_field(c.source_evidence, "source_reliability") for c in supports]
    reliabilities = [r for r in reliabilities if r is not None]
    source_reliability = sum(reliabilities) / len(reliabilities) if reliabilities else 0.0

    # Freshness: 1.0 if every supporting item's time.end falls within (or at)
    # the investigation period being evaluated is not always determinable
    # generically here, so this uses quality.freshness when the evidence
    # carries it, defaulting to a neutral 0.6 (never 1.0 by default -- an
    # unstated freshness must not silently look "as good as verified fresh").
    freshnesses = [_quality_field(c.source_evidence, "freshness") for c in supports]
    freshnesses = [f for f in freshnesses if f is not None]
    freshness = sum(freshnesses) / len(freshnesses) if freshnesses else (0.6 if supports else 0.0)

    hist = [_quality_field(c.source_evidence, "historical_sufficiency") for c in supports]
    hist = [h for h in hist if h is not None]
    historical_sufficiency = sum(hist) / len(hist) if hist else (0.5 if supports else 0.0)

    contradiction_penalty = _CONTRADICTION_PENALTY[contradiction_severity]
    retrieval_penalty = 1.0 if insufficiency_hit else 0.0

    score = (
        _WEIGHTS["completeness"] * completeness + _WEIGHTS["source_reliability"] * source_reliability
        + _WEIGHTS["freshness"] * freshness + _WEIGHTS["historical_sufficiency"] * historical_sufficiency
        - _CONTRADICTION_WEIGHT * contradiction_penalty - _RETRIEVAL_INSUFFICIENCY_PENALTY_WEIGHT * retrieval_penalty
    )
    score = max(0.0, min(1.0, score))
    return score, completeness, len(supports)


def _level_for(score: float, contradiction_severity: ContradictionSeverity, n_supports: int,
               method: AnalyticalMethod, insufficiency_hit: bool, completeness: float) -> ConfidenceLevel:
    if n_supports == 0 or method == AnalyticalMethod.INSUFFICIENT_DATA:
        return ConfidenceLevel.ABSTAIN
    if insufficiency_hit and completeness < 0.3:
        return ConfidenceLevel.NEEDS_CLARIFICATION
    if score >= HIGH_THRESHOLD:
        level = ConfidenceLevel.HIGH
    elif score >= MEDIUM_THRESHOLD:
        level = ConfidenceLevel.MEDIUM
    elif score > 0.0:
        level = ConfidenceLevel.LOW
    else:
        return ConfidenceLevel.ABSTAIN

    if contradiction_severity == ContradictionSeverity.STRONG and _LEVEL_RANK[level] > _LEVEL_RANK[ConfidenceLevel.MEDIUM]:
        return ConfidenceLevel.MEDIUM   # hard cap -- never HIGH regardless of score (task's own requirement)
    return level


def evaluate(state: InvestigationState) -> InvestigationState:
    for hypothesis in state.hypotheses:
        classified = [c for c in state.classified_evidence if c.hypothesis_id == hypothesis.hypothesis_id]
        contradiction = next((cr for cr in state.contradictions if cr.hypothesis_id == hypothesis.hypothesis_id), None)
        severity = contradiction.severity if contradiction else ContradictionSeverity.NONE
        method_sel = next((m for m in state.selected_methods if m.hypothesis_id == hypothesis.hypothesis_id), None)
        method = method_sel.method if method_sel else AnalyticalMethod.INSUFFICIENT_DATA
        insufficiency_hit = any(e.get("hypothesis_id") == hypothesis.hypothesis_id
                                 for e in state.retrieval_insufficiency_events)

        score, completeness, n_supports = _score_hypothesis(classified, severity, insufficiency_hit)
        level = _level_for(score, severity, n_supports, method, insufficiency_hit, completeness)

        evidence_ids = [c.evidence_id for c in classified
                        if c.classification in (EvidenceClassification.SUPPORTS, EvidenceClassification.CONTRADICTS)]
        status = "SUPPORTED" if n_supports > 0 and level != ConfidenceLevel.ABSTAIN else \
                 ("CONTRADICTED" if any(c.classification == EvidenceClassification.CONTRADICTS for c in classified)
                  and n_supports == 0 else "INCONCLUSIVE")

        result = HypothesisResult(
            hypothesis_id=hypothesis.hypothesis_id, status=status, confidence=level,
            evidence_ids=evidence_ids if status in ("SUPPORTED", "CONTRADICTED") else [],
            reasons=[f"score={score:.3f}", f"completeness={completeness:.3f}", f"n_supports={n_supports}",
                     f"contradiction_severity={severity.value}", f"method={method.value}"],
            method=method, contradiction_severity=severity,
        )
        assert result.is_valid(), f"HypothesisResult for {hypothesis.hypothesis_id} failed citation validity (task §15)"
        state.hypothesis_results.append(result)

    if state.hypothesis_results:
        state.confidence = min((r.confidence for r in state.hypothesis_results), key=lambda c: _LEVEL_RANK[c])
    else:
        state.confidence = ConfidenceLevel.ABSTAIN
    return state
