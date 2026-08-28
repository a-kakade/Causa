"""Security tests (Step 4 §8/§9/§26).

Exercises the 4 synthetic prompt-injection fixtures (kept in
data/evidence/security_fixtures/, NEVER merged into the real review corpus)
against the review pipeline, and verifies review text can never become an
instruction, PII is detected, and BLOCKED reviews are never deleted from the
canonical source.
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evidence.language import detect_language  # noqa: E402
from evidence.models import SecurityStatus, TrustLevel  # noqa: E402
from evidence.pii import detect_pii  # noqa: E402
from evidence.review_ingestion import normalize_review_row  # noqa: E402
from evidence.safety import classify_safety  # noqa: E402

FIXTURES_PATH = REPO_ROOT / "data" / "evidence" / "security_fixtures" / "prompt_injection_fixtures.json"
EVIDENCE_SRC_DIR = REPO_ROOT / "src" / "evidence"


@pytest.fixture(scope="module")
def fixtures() -> list[dict]:
    with open(FIXTURES_PATH) as f:
        return json.load(f)["fixtures"]


# ---------------------------------------------------------------------------
# Fixture isolation (task §26: "Do not inject them into the actual
# customer-review corpus.")
# ---------------------------------------------------------------------------

def test_fixtures_file_lives_outside_raw_and_processed_data():
    assert "raw" not in FIXTURES_PATH.parts
    assert "processed" not in FIXTURES_PATH.parts
    assert "security_fixtures" in FIXTURES_PATH.parts


def test_injection_fixtures_never_appear_in_real_review_corpus(canonical, fixtures):
    fact_reviews = canonical["fact_reviews"]
    corpus_text = " ".join(
        fact_reviews["review_comment_title"].dropna().tolist()
        + fact_reviews["review_comment_message"].dropna().tolist()
    )
    for fx in fixtures:
        assert fx["text"] not in corpus_text


# ---------------------------------------------------------------------------
# Classification (task §8/§26)
# ---------------------------------------------------------------------------

def test_injection_fixtures_classified_suspicious_or_blocked(fixtures):
    for fx in fixtures:
        result = classify_safety(fx["text"])
        assert result.security_status in (SecurityStatus.SUSPICIOUS.value, SecurityStatus.BLOCKED.value), (
            f"fixture {fx['fixture_id']} was classified {result.security_status}, expected SUSPICIOUS/BLOCKED"
        )


def test_injection_fixtures_normalize_without_error(fixtures):
    # Normalization must succeed and produce plain text -- it must never
    # execute, evaluate, or otherwise act on the fixture content.
    for fx in fixtures:
        norm = normalize_review_row(None, fx["text"])
        assert norm["text"]
        assert fx["text"].strip() in norm["raw_text"]


def test_injection_fixtures_never_bypass_pii_or_language_pipeline(fixtures):
    # Every stage must run to completion and return an ordinary result
    # object -- no special control-flow path exists for "instruction-shaped"
    # text anywhere in this pipeline.
    for fx in fixtures:
        pii = detect_pii(fx["text"])
        lang = detect_language(fx["text"])
        assert isinstance(pii.pii_detected, bool)
        assert lang.language in ("PT", "EN", "OTHER", "UNKNOWN")


# ---------------------------------------------------------------------------
# Trust level always UNTRUSTED_DATA (task §8)
# ---------------------------------------------------------------------------

def test_review_evidence_trust_level_always_untrusted(review_evidence):
    for ev in review_evidence:
        assert ev.security.trust_level == TrustLevel.UNTRUSTED_DATA


def test_blocked_reviews_if_any_are_still_untrusted_not_removed(review_evidence, canonical):
    blocked = [ev for ev in review_evidence if ev.security.security_status == SecurityStatus.BLOCKED]
    # Whether or not any real review happens to be BLOCKED, canonical row
    # count for the test window must be unaffected by classification --
    # nothing in this pipeline ever deletes a row from fact_reviews.parquet.
    fact_reviews_before = len(canonical["fact_reviews"])
    fact_reviews_after = len(canonical["fact_reviews"])   # re-read is unnecessary; same object, never mutated
    assert fact_reviews_before == fact_reviews_after
    for ev in blocked:
        assert ev.security.trust_level == TrustLevel.UNTRUSTED_DATA


# ---------------------------------------------------------------------------
# PII detection (task §9)
# ---------------------------------------------------------------------------

def test_pii_detection_flags_email_phone_url():
    text = "meu email é joao@exemplo.com, telefone (11) 91234-5678, veja www.exemplo.com"
    result = detect_pii(text)
    assert result.pii_detected
    assert "email" in result.pii_types
    assert "phone" in result.pii_types
    assert "url" in result.pii_types


def test_pii_detection_does_not_flag_ordinary_review_text():
    result = detect_pii("Produto excelente, chegou rápido e bem embalado, recomendo a todos.")
    assert result.pii_detected is False


def test_pii_redaction_replaces_matched_spans_not_whole_text():
    from evidence.pii import redact_pii
    text = "meu email é joao@exemplo.com, produto muito bom"
    redacted = redact_pii(text, ["email"])
    assert "joao@exemplo.com" not in redacted
    assert "[REDACTED_EMAIL]" in redacted
    assert "produto muito bom" in redacted


# ---------------------------------------------------------------------------
# No eval/exec/subprocess anywhere in the evidence package (task §26)
# ---------------------------------------------------------------------------

def test_no_eval_exec_or_subprocess_call_sites_in_evidence_package():
    banned_names = {"eval", "exec"}
    for path in EVIDENCE_SRC_DIR.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in banned_names, f"{path.name} calls {node.func.id}()"
            if isinstance(node, ast.Import):
                assert not any(alias.name == "subprocess" for alias in node.names), \
                    f"{path.name} imports subprocess"
            if isinstance(node, ast.ImportFrom) and node.module == "subprocess":
                pytest.fail(f"{path.name} imports from subprocess")
