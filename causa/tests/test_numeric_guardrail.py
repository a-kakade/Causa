"""Step 5: numeric guardrail tests (task §14).

Uses REAL November 2017 evidence values (via agent_ctx) rather than
synthetic numbers wherever possible, per this repo's exact-value-assertion
discipline.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from agents.models import (  # noqa: E402
    NumericValidationFailed,
    build_allowed_numbers,
    extract_numeric_claims,
    validate_numeric_claims,
)
from agents.models import AgentRole, InvestigationState, RequesterRole  # noqa: E402
from tools import gateway  # noqa: E402


def test_extract_numeric_claims_finds_currency_percent_and_bare_numbers():
    text = "Revenue moved by R$346,051.94, a +52.10% change, across 12 orders."
    values = extract_numeric_claims(text)
    assert any(abs(v - 346051.94) < 0.01 for v in values)
    assert any(abs(v - 52.10) < 0.01 for v in values)
    assert any(v == 12 for v in values)


def test_build_allowed_numbers_from_real_november_2017_revenue_movement(agent_ctx):
    state = InvestigationState(investigation_id="ng1", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "compare_kpi", dict(
        kpi_id="revenue", current_start="2017-11-01", current_end="2017-11-30",
        previous_start="2017-10-01", previous_end="2017-10-31",
    ), agent_ctx)
    assert result.ok
    ev = agent_ctx.evidence_store[result.result_ids[0]]
    allowed = build_allowed_numbers([ev])

    # The real, live-computed absolute change (task's own required value: 346,051.94)
    assert any(abs(a - 346051.94) < 1.0 for a in allowed)
    # The real, live-computed percentage change (task's own required value: 52.1%)
    assert any(abs(a - 52.1) < 0.1 for a in allowed)


def test_validate_numeric_claims_passes_for_real_cited_numbers(agent_ctx):
    state = InvestigationState(investigation_id="ng2", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "compare_kpi", dict(
        kpi_id="revenue", current_start="2017-11-01", current_end="2017-11-30",
        previous_start="2017-10-01", previous_end="2017-10-31",
    ), agent_ctx)
    ev = agent_ctx.evidence_store[result.result_ids[0]]
    allowed = build_allowed_numbers([ev])

    ok, violations = validate_numeric_claims("Revenue increased by R$346051.94, a +52.10% change.", allowed)
    assert ok and not violations


def test_validate_numeric_claims_rejects_a_fabricated_number(agent_ctx):
    state = InvestigationState(investigation_id="ng3", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
                                period="2017-11")
    result = gateway.call_tool(state, AgentRole.EVIDENCE, "compare_kpi", dict(
        kpi_id="revenue", current_start="2017-11-01", current_end="2017-11-30",
        previous_start="2017-10-01", previous_end="2017-10-31",
    ), agent_ctx)
    ev = agent_ctx.evidence_store[result.result_ids[0]]
    allowed = build_allowed_numbers([ev])

    ok, violations = validate_numeric_claims("Revenue increased by R$999999.99, a fabricated number.", allowed)
    assert not ok
    assert any(abs(v - 999999.99) < 0.01 for v in violations)


def test_small_bare_integers_are_not_flagged_as_quantitative_claims():
    # "H1", rank "3", "top 5" -- structural labels, not business numbers.
    ok, violations = validate_numeric_claims("Hypothesis 3 ranks in the top 5 segments.", allowed_numbers=set())
    assert ok and not violations


def test_a_percentage_shaped_fraction_is_still_checked_even_though_small():
    ok, violations = validate_numeric_claims("The share was 0.42 of the total.", allowed_numbers={0.42})
    assert ok
    ok2, violations2 = validate_numeric_claims("The share was 0.99 of the total.", allowed_numbers={0.42})
    assert not ok2


def test_a_bare_calendar_year_naming_the_investigation_period_is_not_flagged():
    """Real false positive observed against a live Groq run
    (openai/gpt-oss-20b): a hypothesis naming its own investigation period
    ('...may be associated with the revenue movement in November 2017.')
    was rejected because '2017' wasn't itself in allowed_numbers -- a date
    reference is not a quantitative business claim."""
    ok, violations = validate_numeric_claims(
        "Growth in orders from customer states may be associated with the revenue movement in November 2017.",
        allowed_numbers=set(),
    )
    assert ok and not violations


def test_a_four_digit_number_outside_the_calendar_year_range_is_still_checked():
    ok, violations = validate_numeric_claims("Revenue reached R$3000.00 last month.", allowed_numbers=set())
    assert not ok   # "3000.00" carries a currency marker -- always checked, not exempted


def test_numeric_validation_failed_exception_carries_the_violations():
    exc = NumericValidationFailed("some text", [999999.99])
    assert exc.violating_numbers == [999999.99]
    assert "999999.99" in str(exc)
