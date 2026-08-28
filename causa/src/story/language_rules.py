"""
language_rules.py — Step 8: the epistemic-type -> allowed-wording mapping.

Maps ClaimType to permissible narrative vocabulary and detects violations.
Reuses agents.models.UNSUPPORTED_CAUSAL_PATTERN/contains_unsupported_causal_language
as the real deterministic gate -- never a second, parallel causal-language
regex. ALLOWED_VERBS is a WHITELIST used only to feed prompt text
(story/prompts.py) and the deterministic template generator
(story/generator.py::_deterministic_sections) -- it is deliberately NOT used
as a whitelist gate in violates_language_rule(), because exact-phrase
matching against natural LLM prose ("Revenue grew" vs "Revenue increased" vs
"Revenue rose") would be far too brittle. The real, robust check is the
BLACKLIST (UNSUPPORTED_CAUSAL_PATTERN) applied to any claim whose evidence
does not license causal language -- the same asymmetry
agents.models.assert_no_unsupported_causal_language already uses everywhere
else in this repo.
"""

from __future__ import annotations

from typing import Optional

from agents.models import ALLOWED_HEDGED_PHRASES, contains_unsupported_causal_language

from story.models import ClaimType

# Vocabulary a narrative sentence of this ClaimType is ENCOURAGED to use
# (prompt guidance + deterministic-template source), never an exact-match
# whitelist gate for the verifier.
ALLOWED_VERBS: dict[ClaimType, tuple[str, ...]] = {
    ClaimType.FACT: ("increased", "decreased", "declined", "was", "rose", "fell", "remained"),
    ClaimType.ANALYTICAL_FINDING: ("explains", "contributed", "accounted for", "contributed mathematically"),
    ClaimType.ASSOCIATION: ("coincided with", "was associated with", "occurred alongside", "moved together with"),
    ClaimType.HYPOTHESIS: ("may have contributed", "could indicate", "may be associated with",
                            "is a plausible explanation for"),
    ClaimType.UNKNOWN: ("evidence is insufficient to determine",),
}

# ClaimTypes whose narrative sentences may NEVER use causal-sounding
# language ("caused", "led to", "resulted in", "because of", "driven by",
# ...) regardless of phrasing -- the blacklist check applies unconditionally.
_STRICTLY_NON_CAUSAL_CLAIM_TYPES = frozenset({ClaimType.ASSOCIATION, ClaimType.HYPOTHESIS, ClaimType.UNKNOWN})


def violates_language_rule(text: str, claim_type: ClaimType) -> Optional[str]:
    """Returns a human-readable violation reason, or None if `text` is
    consistent with `claim_type`'s language rule.

    Two checks, in order:
      1. ASSOCIATION/HYPOTHESIS/UNKNOWN claims: any unsupported causal
         language (agents.models.UNSUPPORTED_CAUSAL_PATTERN) is an automatic
         violation -- no exception. This is the literal enforcement of
         "coincided with" allowed for ASSOCIATION, "caused" rejected for
         ASSOCIATION.
      2. FACT claims: also checked against the causal pattern -- a plain
         observation ("Revenue increased 52.1%") never needs causal
         connector language at all; if a FACT-labeled claim uses one, it
         should have been labeled ANALYTICAL_FINDING or stronger evidence
         is implied than actually exists, so it's rejected too.
      3. ANALYTICAL_FINDING claims: causal-sounding language is allowed
         ONLY if the exact phrase is one of agents.models.ALLOWED_HEDGED_PHRASES
         (e.g. "contributed mathematically", "mathematically explains") --
         anything else matching the causal pattern is still rejected.
    """
    has_causal_language = contains_unsupported_causal_language(text)

    if claim_type in _STRICTLY_NON_CAUSAL_CLAIM_TYPES:
        if has_causal_language:
            return (
                f"claim_type={claim_type.value} may never use causal language (e.g. 'caused', 'led to', "
                f"'resulted in') -- text: {text!r}"
            )
        return None

    if claim_type == ClaimType.FACT:
        if has_causal_language:
            return (
                f"claim_type=FACT should state a plain observation; causal-sounding language implies "
                f"stronger evidence than a fact-level claim licenses -- text: {text!r}"
            )
        return None

    if claim_type == ClaimType.ANALYTICAL_FINDING:
        if has_causal_language and not any(phrase in text.lower() for phrase in ALLOWED_HEDGED_PHRASES):
            return (
                f"claim_type=ANALYTICAL_FINDING may only use hedged phrases like "
                f"{ALLOWED_HEDGED_PHRASES!r} for causal-sounding language, not free causal wording -- "
                f"text: {text!r}"
            )
        return None

    return None
