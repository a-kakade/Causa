"""
language.py — Step 4: language detection for review text (task §10).

Uses `langdetect` (already a repo dependency, used nowhere else yet) to fill
the `language` field on review evidence. This is a distinct concern from the
multilingual E5 embedding used in embeddings.py: langdetect answers "what
language is this text in" for metadata/filtering purposes; E5's own
multilinguality is what lets retrieval.py match a Portuguese review against
an English query without a separate translation step. Neither replaces the
other -- see docs/EVIDENCE_FABRIC.md.

Task §10 explicitly forbids solving multilinguality by translating the whole
corpus -- this module never calls a translation API or model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from langdetect import DetectorFactory, LangDetectException, detect_langs

# langdetect's detection is non-deterministic by default (it seeds its PRNG
# from the input text's hash-derived character n-grams using a random state
# that is NOT fixed across runs unless DetectorFactory.seed is set). Fixed
# here once at import time so language detection -- and therefore every
# evidence object and vector index metadata field derived from it -- is
# reproducible across runs (task §12: "rebuildable deterministically").
DetectorFactory.seed = 0

LANG_PT = "PT"
LANG_EN = "EN"
LANG_OTHER = "OTHER"
LANG_UNKNOWN = "UNKNOWN"

# Below this length, langdetect's statistical n-gram model is unreliable
# (Olist review titles/messages are frequently very short -- title mean is
# 12 chars). Short text is honestly reported UNKNOWN rather than guessed.
MIN_CHARS_FOR_DETECTION = 10

_LANGDETECT_CODE_MAP = {"pt": LANG_PT, "en": LANG_EN}


@dataclass
class LanguageResult:
    language: str            # PT | EN | OTHER | UNKNOWN
    language_confidence: Optional[float]   # 0..1, None when UNKNOWN


def detect_language(text: Optional[str]) -> LanguageResult:
    if not text or len(text.strip()) < MIN_CHARS_FOR_DETECTION:
        return LanguageResult(language=LANG_UNKNOWN, language_confidence=None)
    try:
        candidates = detect_langs(text)
    except LangDetectException:
        return LanguageResult(language=LANG_UNKNOWN, language_confidence=None)
    if not candidates:
        return LanguageResult(language=LANG_UNKNOWN, language_confidence=None)
    top = candidates[0]
    language = _LANGDETECT_CODE_MAP.get(top.lang, LANG_OTHER)
    return LanguageResult(language=language, language_confidence=round(float(top.prob), 4))
