"""
pii.py — Step 4: deterministic, regex-based PII detection over review text
(task §9).

No NER library is installed in this repo (see requirements.txt), so name
detection here is a conservative capitalized-token heuristic, not true named
entity recognition -- documented as weak by design. This module ONLY
detects; it never mutates or redacts text. Actual redaction happens in
retrieval.py at result-construction time, so the canonical/cached review text
is never altered in place (task §9: "For the retrieval layer: redact or mask
unnecessary PII").

KNOWN CORPUS QUIRK: exploration of fact_reviews.parquet found review text
containing what appear to be upstream-anonymized placeholder proper nouns
styled as fictional house names (e.g. "targaryen", "lannister", "stark") --
an artifact of Olist's own PII-scrubbing, not naturally occurring customer
data. The capitalized-token heuristic below WILL flag these as
name_heuristic candidates. That is an acceptable, safe failure mode: this
module explicitly favors over-flagging (a false positive on a placeholder
name) over under-flagging (missing a real one) -- see task §9's own
disclaimer, "Do not claim perfect PII detection."
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PII_TYPE_PHONE = "phone"
PII_TYPE_EMAIL = "email"
PII_TYPE_URL = "url"
PII_TYPE_ADDRESS = "address"
PII_TYPE_NAME_HEURISTIC = "name_heuristic"

_PHONE_RE = re.compile(r"(?:\+?55[\s.-]?)?\(?\d{2}\)?[\s.-]?9?\d{4}[\s.-]?\d{4}\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_CEP_RE = re.compile(r"\b\d{5}-?\d{3}\b")
_ADDRESS_WORD_RE = re.compile(r"\b(rua|avenida|av\.|alameda|rodovia)\b", re.IGNORECASE)

# Common Portuguese sentence-starters / high-frequency capitalized words that
# would otherwise dominate false positives if treated as name candidates.
_CAPITALIZED_TOKEN_RE = re.compile(r"\b[A-ZÀ-Ú][a-zà-ú]{2,}\b")
_CAPITALIZED_STOPLIST = {
    "Muito", "Bom", "Boa", "Ótimo", "Otimo", "Excelente", "Recomendo", "Produto",
    "Entrega", "Chegou", "Compra", "Comprei", "Loja", "Obrigado", "Obrigada",
    "Não", "Nao", "Ainda", "Todo", "Toda", "Depois", "Quando", "Porém", "Porem",
}


@dataclass
class PiiResult:
    pii_detected: bool
    pii_types: list[str] = field(default_factory=list)


_REDACTION_PATTERNS = {
    PII_TYPE_EMAIL: _EMAIL_RE,
    PII_TYPE_URL: _URL_RE,
    PII_TYPE_PHONE: _PHONE_RE,
}


def redact_pii(text: str, pii_types: list[str]) -> str:
    """Task §9/§13: redaction happens at the RETRIEVAL layer, on a copy of the
    text, never on the canonical/cached review text itself. Only redacts the
    pattern-matchable types (email/url/phone); `address` and
    `name_heuristic` are word/context-based rather than a single matchable
    span in this deterministic implementation and are left in place here,
    surfaced instead via `pii_detected`/`pii_types` on the result so a caller
    can decide to withhold the whole review if that's not enough."""
    redacted = text
    for pii_type in pii_types:
        pattern = _REDACTION_PATTERNS.get(pii_type)
        if pattern:
            redacted = pattern.sub(f"[REDACTED_{pii_type.upper()}]", redacted)
    return redacted


def detect_pii(text: str | None) -> PiiResult:
    if not text:
        return PiiResult(pii_detected=False, pii_types=[])

    types: set[str] = set()
    if _EMAIL_RE.search(text):
        types.add(PII_TYPE_EMAIL)
    if _URL_RE.search(text):
        types.add(PII_TYPE_URL)
    if _PHONE_RE.search(text):
        types.add(PII_TYPE_PHONE)
    if _CEP_RE.search(text) or _ADDRESS_WORD_RE.search(text):
        types.add(PII_TYPE_ADDRESS)

    candidates = [t for t in _CAPITALIZED_TOKEN_RE.findall(text) if t not in _CAPITALIZED_STOPLIST]
    # Require >=2 distinct capitalized non-stoplist tokens before flagging --
    # a single capitalized word at a sentence start is far too common in
    # short reviews to be a useful signal on its own.
    if len(set(candidates)) >= 2:
        types.add(PII_TYPE_NAME_HEURISTIC)

    return PiiResult(pii_detected=bool(types), pii_types=sorted(types))
