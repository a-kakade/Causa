"""Step 6: deterministic causal-language gate tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import agents.models as agents_models  # noqa: E402
from causal import language_gate  # noqa: E402

_BANNED = ("caused by", "because of", "led to", "resulted in", "responsible for", "caused this")


@pytest.mark.parametrize("phrase", _BANNED)
def test_blocks_banned_causal_phrases(phrase):
    text = f"Revenue growth was {phrase} the volume increase."
    with pytest.raises(ValueError):
        language_gate.enforce_language_gate(text, "field", causal_claim_allowed=False)


def test_blocks_caused_by_when_causal_claim_not_allowed():
    with pytest.raises(ValueError):
        language_gate.enforce_language_gate("The delay was caused by the carrier.", "field", False)


def test_blocks_because_of_when_causal_claim_not_allowed():
    with pytest.raises(ValueError):
        language_gate.enforce_language_gate("Revenue fell because of the price change.", "field", False)


@pytest.mark.parametrize("phrase", [
    "is associated with", "is consistent with", "coincides with",
    "supports the hypothesis", "mathematically explains",
])
def test_allows_sanctioned_hedged_phrases(phrase):
    text = f"The volume effect {phrase} 80% of the revenue change."
    result = language_gate.enforce_language_gate(text, "field", causal_claim_allowed=False)
    assert result == text


def test_gate_reuses_agents_models_pattern_not_a_third_regex():
    assert language_gate.UNSUPPORTED_CAUSAL_PATTERN is agents_models.UNSUPPORTED_CAUSAL_PATTERN


def test_gate_applied_even_when_causal_claim_allowed_true():
    with pytest.raises(ValueError):
        language_gate.enforce_language_gate("This effect caused the observed change.", "field",
                                             causal_claim_allowed=True)


def test_check_allowed_hedge_present_detects_mathematically_explains():
    assert language_gate.check_allowed_hedge_present("The mix effect mathematically explains the gap.")


def test_check_allowed_hedge_present_false_for_plain_sentence():
    assert not language_gate.check_allowed_hedge_present("Revenue was 1010271.37 in November 2017.")
