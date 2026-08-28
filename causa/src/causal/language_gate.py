"""
language_gate.py — Step 6: the deterministic causal-language gate.

Reuses agents.models.UNSUPPORTED_CAUSAL_PATTERN / assert_no_unsupported_causal_
language directly rather than defining a third causal-language regex. Two
already exist in this repo (evidence.models.CAUSAL_LANGUAGE_PATTERN, the
narrower original; agents.models.UNSUPPORTED_CAUSAL_PATTERN, its documented
stricter superset) -- this module must not become a third, independently
drifting copy.

Banned (from agents.models.UNSUPPORTED_CAUSAL_PATTERN): caused/caused by,
causes, because of, due to (unless "excluded due to"), the reason is/for, as
a result of, led to, driven by, drove the, responsible for, resulted in.

Allowed (agents.models.ALLOWED_HEDGED_PHRASES, documentation only, never
pattern-matched): associated with, consistent with, coincides with,
contributed mathematically, supports the hypothesis, may be associated with.
Plus this module's own ADDITIONAL_ALLOWED_CAUSAL_HEDGES: "mathematically
explains" (verified against the live UNSUPPORTED_CAUSAL_PATTERN to contain no
"mathematically"/"explain" token, so it can never be spuriously flagged).
"""

from __future__ import annotations

from agents.models import (
    ALLOWED_HEDGED_PHRASES,
    UNSUPPORTED_CAUSAL_PATTERN,
    assert_no_unsupported_causal_language,
    contains_unsupported_causal_language,
)

ADDITIONAL_ALLOWED_CAUSAL_HEDGES: tuple[str, ...] = ("mathematically explains",)


def enforce_language_gate(text: str, field_name: str, causal_claim_allowed: bool) -> str:
    """Runs the SAME check regardless of `causal_claim_allowed` -- even a
    licensed T3/T4 CausalResult's free-text `limitations`/`assumptions`
    fields must stay non-causal-phrased, since the actual causal assertion
    lives only in CausalResult.status/estimate, never in prose (task's own
    framing: this gate is universal, not conditional on tier). Raises
    ValueError (via assert_no_unsupported_causal_language) on a banned
    phrase; returns the text unchanged otherwise."""
    return assert_no_unsupported_causal_language(text, field_name)


def check_allowed_hedge_present(text: str) -> bool:
    """True if `text` contains at least one sanctioned hedge phrase. Never a
    blocking check by itself -- a sentence needs no hedge phrase at all to be
    fine (e.g. a plain numeric statement); this is only for tests/docs to
    confirm example sentences use the sanctioned vocabulary."""
    lowered = text.lower()
    return any(phrase in lowered for phrase in (*ALLOWED_HEDGED_PHRASES, *ADDITIONAL_ALLOWED_CAUSAL_HEDGES))


__all__ = [
    "UNSUPPORTED_CAUSAL_PATTERN",
    "ADDITIONAL_ALLOWED_CAUSAL_HEDGES",
    "enforce_language_gate",
    "check_allowed_hedge_present",
    "contains_unsupported_causal_language",
]
