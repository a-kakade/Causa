"""
safety.py — Step 4: deterministic prompt-injection / safety classification
over review text (task §7/§8/§26).

Pure regex/keyword pattern matching -- no LLM call, no ML model. Review text
is UNTRUSTED_DATA (task §8): it is scanned for phrasing that resembles an
attempt to redirect a downstream agent's behavior, but the classification
result is a FLAG on the evidence object, never a trigger that executes,
deletes, or otherwise acts on the text. BLOCKED reviews are still embedded,
indexed, and traceable -- retrieval.py simply excludes them from normal
query results by default (task §8: "Do not delete suspicious reviews from
the canonical source").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from evidence.models import SecurityStatus

# Patterns that, on their own, are only mildly suspicious (common in
# legitimate reviews making an unrelated remark) -- one hit here alone is
# SUSPICIOUS, not BLOCKED.
_SUSPICIOUS_PATTERNS = [
    re.compile(r"\byou are now\b", re.IGNORECASE),
    re.compile(r"\bact as (an?|the)\b", re.IGNORECASE),
    re.compile(r"^\s*system\s*:", re.IGNORECASE),
]

# Patterns that combine an imperative verb with a clearly sensitive target --
# these are explicit attempts to redirect instructions or exfiltrate data,
# and classify as BLOCKED (a flag, never a deletion -- see module docstring).
_BLOCKED_PATTERNS = [
    re.compile(r"ignore (all|the|any|your)? ?(previous|prior|above)? ?instructions?", re.IGNORECASE),
    re.compile(r"disregard (the|your|all)? ?(system|previous|prior)? ?(prompt|instructions?)", re.IGNORECASE),
    re.compile(r"reveal (the|your) (system prompt|instructions?|api key|password|database)", re.IGNORECASE),
    re.compile(r"forget (the|this) investigation", re.IGNORECASE),
    re.compile(r"\bexecute\b.{0,20}\b(command|code|script)\b", re.IGNORECASE),
    re.compile(r"\bgive me all\b.{0,20}\b(customer|password|email)s?\b", re.IGNORECASE),
]


@dataclass
class SafetyResult:
    security_status: str          # SAFE | SUSPICIOUS | BLOCKED
    matched_patterns: list[str]


def classify_safety(text: str | None) -> SafetyResult:
    if not text:
        return SafetyResult(security_status=SecurityStatus.SAFE.value, matched_patterns=[])

    matched = [p.pattern for p in _BLOCKED_PATTERNS if p.search(text)]
    if matched:
        return SafetyResult(security_status=SecurityStatus.BLOCKED.value, matched_patterns=matched)

    matched = [p.pattern for p in _SUSPICIOUS_PATTERNS if p.search(text)]
    if matched:
        return SafetyResult(security_status=SecurityStatus.SUSPICIOUS.value, matched_patterns=matched)

    return SafetyResult(security_status=SecurityStatus.SAFE.value, matched_patterns=[])
