"""
eligibility.py — Step 6: the eligibility checker.

Before ANY causal analysis is attempted, this module verifies the 12 things
the task lists (treatment exists, outcome exists, treatment precedes outcome,
sufficient pre-period, sufficient post-period, treatment variation, control
variation, sample size, missingness, confounders, consistent grain,
consistent KPI definition) and returns ELIGIBLE / PARTIALLY_ELIGIBLE /
INELIGIBLE / CAUSAL_INELIGIBLE with explicit, data-cited reasons for every
check -- never just an overall verdict with no explanation.

This module never calls an LLM, never imports agents.llm_client, and never
constructs a causal conclusion of its own -- it only reports what the data
can and cannot support. All 12 checks always run, always in the same fixed
order, so `EligibilityReport.checks` is reproducible and independently
auditable (tests/test_eligibility.py::
test_all_12_checks_run_in_fixed_order_and_always_return_12_results).

Reuses, never duplicates: kpi.query_planner's dimension/filter governance
(via KPIEngine.compute), the KPI contract's own
data_quality_requirements.minimum_observations/coverage_threshold_pct (never
a hardcoded number), and drivers.engine.SUPPORTED_SEGMENT_DIMENSIONS for
which dimensions may ever serve as a treatment/control group.
"""

from __future__ import annotations

from typing import Any, Optional

import pandas as pd

from drivers.engine import SUPPORTED_SEGMENT_DIMENSIONS
from kpi.engine import KPIEngine
from kpi.models import KPIRequest, KPIResult
from kpi.query_planner import KPIRequestError
from kpi.semantic_registry import SemanticRegistry

from causal.models import CausalHypothesis, CheckResult, CheckResultStatus, EligibilityReport, EligibilityVerdict

# Checks 4/5/8/9 are "escalating": below a lower bound they are HARD_FAIL,
# between the lower and upper bound they are SOFT_FAIL, at/above the upper
# bound they PASS. Documented and justified in docs/CAUSAL_METHOD_SELECTION.md.
_MIN_PRE_PERIOD_HARD = 2
_MIN_PRE_PERIOD_SOFT = 6
_MIN_POST_PERIOD_HARD = 1
_MIN_POST_PERIOD_SOFT = 3

_ALL_OTHER_PREFIX = "all_other"

CHECK_NAMES = (
    "treatment_exists",
    "outcome_exists",
    "treatment_precedes_outcome",
    "sufficient_pre_period",
    "sufficient_post_period",
    "treatment_variation",
    "control_variation",
    "sample_size",
    "missingness",
    "confounders",
    "consistent_grain",
    "consistent_kpi_definition",
)


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------


def _period_bound(period: dict[str, str], key: str) -> Optional[str]:
    """A CausalHypothesis period is either {"start":..,"end":..} or a single
    {"date": ..} point event. Always returns a "YYYY-MM..." string or None."""
    if key in period:
        return period[key]
    return period.get("date")


def _to_month(date_str: Optional[str]) -> Optional[pd.Period]:
    if not date_str:
        return None
    return pd.Period(date_str[:7], freq="M")


def _months_between(start_month: Optional[pd.Period], end_month: Optional[pd.Period]) -> Optional[int]:
    """Inclusive count of whole months in [start_month, end_month]. None if
    either bound is missing or the range is inverted."""
    if start_month is None or end_month is None or end_month < start_month:
        return None
    return int((end_month - start_month).n) + 1


def _kpi_or_none(registry: SemanticRegistry, kpi_id: str) -> Optional[dict[str, Any]]:
    try:
        return registry.get(kpi_id)
    except KeyError:
        return None


def _dimension_or_none(registry: SemanticRegistry, kpi_id: str, dimension: str) -> Optional[dict[str, Any]]:
    contract = _kpi_or_none(registry, kpi_id)
    if contract is None:
        return None
    return registry.get_dimension(kpi_id, dimension)


def compute_group_results(kpi_engine: KPIEngine, kpi_id: str, dimension: str,
                           start: str, end: str) -> list[KPIResult]:
    """Every value of `dimension` for `kpi_id` over [start, end]. Never
    raises on a governance error -- callers treat an empty/failed result as
    "no variation," which is exactly what an eligibility check should report,
    not crash on."""
    try:
        result = kpi_engine.compute(KPIRequest(kpi_id=kpi_id, start_date=start, end_date=end, dimensions=[dimension]))
    except (KPIRequestError, KeyError, ValueError):
        return []
    return result if isinstance(result, list) else [result]


def group_slice(results: list[KPIResult], dimension: str, group_value: Optional[str],
                 exclude_value: Optional[str] = None) -> tuple[Optional[float], int]:
    """Resolves one named group's (value, sample_size) from a list of
    per-dimension-value KPIResults. `group_value` starting with "all_other"
    is a real, computable complement (every OTHER dimension value actually
    observed in the data), not a fabricated control group -- summed because
    every outcome KPI a DiD/PVM hypothesis in this package targets (revenue)
    is additive across a dimension's values by construction."""
    if group_value is None:
        return None, 0
    if group_value.startswith(_ALL_OTHER_PREFIX):
        matches = [r for r in results if r.dimensions.get(dimension) != exclude_value]
    else:
        matches = [r for r in results if r.dimensions.get(dimension) == group_value]
    if not matches:
        return None, 0
    values = [r.value for r in matches if r.value is not None]
    total_value = sum(values) if values else None
    total_sample = sum(r.sample_size for r in matches)
    return total_value, total_sample


def _kpi_single_value(kpi_engine: KPIEngine, kpi_id: str, start: str, end: str) -> tuple[Optional[float], int]:
    try:
        result = kpi_engine.compute(KPIRequest(kpi_id=kpi_id, start_date=start, end_date=end))
    except (KPIRequestError, KeyError, ValueError):
        return None, 0
    if isinstance(result, list):
        return None, 0
    return result.value, result.sample_size


# ---------------------------------------------------------------------------
# The 12 checks
# ---------------------------------------------------------------------------


def _check_treatment_exists(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                             requester_clearance: str) -> CheckResult:
    if h.treatment_dimension is not None:
        dim = _dimension_or_none(registry, h.outcome, h.treatment_dimension)
        if dim is not None and dim["supported"] and h.treatment_dimension in SUPPORTED_SEGMENT_DIMENSIONS:
            return CheckResult("treatment_exists", CheckResultStatus.PASS,
                                f"treatment dimension '{h.treatment_dimension}' is a governed, supported "
                                f"dimension of outcome '{h.outcome}'.")
        return CheckResult(
            "treatment_exists", CheckResultStatus.HARD_FAIL,
            f"treatment dimension '{h.treatment_dimension}' is not a governed, supported dimension of "
            f"outcome '{h.outcome}' (SUPPORTED_SEGMENT_DIMENSIONS={SUPPORTED_SEGMENT_DIMENSIONS}).",
        )
    if _kpi_or_none(registry, h.treatment) is not None:
        return CheckResult("treatment_exists", CheckResultStatus.PASS,
                            f"treatment '{h.treatment}' is a governed kpi_id.")
    return CheckResult(
        "treatment_exists", CheckResultStatus.HARD_FAIL,
        f"treatment '{h.treatment}' is not a governed kpi_id and no treatment_dimension was given.",
    )


def _check_outcome_exists(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                           requester_clearance: str) -> CheckResult:
    if _kpi_or_none(registry, h.outcome) is not None:
        return CheckResult("outcome_exists", CheckResultStatus.PASS, f"outcome '{h.outcome}' is a governed kpi_id.")
    return CheckResult("outcome_exists", CheckResultStatus.HARD_FAIL,
                        f"outcome '{h.outcome}' is not present in the KPI semantic registry.")


def _check_treatment_precedes_outcome(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                                       requester_clearance: str) -> CheckResult:
    if h.treatment_dimension is not None:
        return CheckResult(
            "treatment_precedes_outcome", CheckResultStatus.HARD_FAIL,
            f"treatment '{h.treatment}={h.treatment_group_value}' is a pre-existing group characteristic "
            "with no assignment timing -- treatment cannot be shown to precede outcome.",
        )
    t_end = _period_bound(h.treatment_period, "end") or _period_bound(h.treatment_period, "date")
    o_start = _period_bound(h.outcome_period, "start") or _period_bound(h.outcome_period, "date")
    if t_end is None or o_start is None:
        return CheckResult("treatment_precedes_outcome", CheckResultStatus.HARD_FAIL,
                            "treatment_period/outcome_period do not carry resolvable dates.")
    if pd.Timestamp(t_end) <= pd.Timestamp(o_start) + pd.Timedelta(days=1):
        return CheckResult("treatment_precedes_outcome", CheckResultStatus.PASS,
                            f"treatment period ends {t_end}, at or before outcome period starts {o_start}.")
    return CheckResult(
        "treatment_precedes_outcome", CheckResultStatus.HARD_FAIL,
        f"treatment period ends {t_end}, AFTER outcome period starts {o_start} -- temporal order cannot "
        "be established.",
    )


def _check_sufficient_pre_period(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                                  requester_clearance: str) -> CheckResult:
    contract = _kpi_or_none(registry, h.outcome)
    if contract is None:
        return CheckResult("sufficient_pre_period", CheckResultStatus.NOT_APPLICABLE, "outcome not resolvable.")
    window = contract["valid_time_window"]
    window_start = _to_month(window["default_start"])
    t_start = _to_month(_period_bound(h.treatment_period, "start") or _period_bound(h.treatment_period, "date"))
    if t_start is None:
        return CheckResult("sufficient_pre_period", CheckResultStatus.HARD_FAIL,
                            "treatment_period has no resolvable start date.")
    n = _months_between(window_start, t_start - 1)
    n = n or 0
    if n < _MIN_PRE_PERIOD_HARD:
        return CheckResult("sufficient_pre_period", CheckResultStatus.HARD_FAIL,
                            f"only {n} pre-period months available (< {_MIN_PRE_PERIOD_HARD}), cannot estimate "
                            "even a naive baseline.")
    if n < _MIN_PRE_PERIOD_SOFT:
        return CheckResult("sufficient_pre_period", CheckResultStatus.SOFT_FAIL,
                            f"only {n} pre-period months available (< {_MIN_PRE_PERIOD_SOFT} needed for a "
                            "defensible pre-trend check).")
    return CheckResult("sufficient_pre_period", CheckResultStatus.PASS, f"{n} pre-period months available.")


def _check_sufficient_post_period(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                                   requester_clearance: str) -> CheckResult:
    contract = _kpi_or_none(registry, h.outcome)
    if contract is None:
        return CheckResult("sufficient_post_period", CheckResultStatus.NOT_APPLICABLE, "outcome not resolvable.")
    window = contract["valid_time_window"]
    window_end = _to_month(window["default_end"])
    t_end = _to_month(_period_bound(h.treatment_period, "end") or _period_bound(h.treatment_period, "date"))
    if t_end is None:
        return CheckResult("sufficient_post_period", CheckResultStatus.HARD_FAIL,
                            "treatment_period has no resolvable end date.")
    n = _months_between(t_end + 1, window_end)
    n = n or 0
    if n < _MIN_POST_PERIOD_HARD:
        return CheckResult("sufficient_post_period", CheckResultStatus.HARD_FAIL,
                            f"only {n} post-period months available (< {_MIN_POST_PERIOD_HARD}).")
    if n < _MIN_POST_PERIOD_SOFT:
        return CheckResult("sufficient_post_period", CheckResultStatus.SOFT_FAIL,
                            f"only {n} post-period months available (< {_MIN_POST_PERIOD_SOFT} needed).")
    return CheckResult("sufficient_post_period", CheckResultStatus.PASS, f"{n} post-period months available.")


def _check_treatment_variation(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                                requester_clearance: str) -> CheckResult:
    pre_start = _period_bound(h.treatment_period, "start") or _period_bound(h.treatment_period, "date")
    pre_end = _period_bound(h.treatment_period, "end") or _period_bound(h.treatment_period, "date")
    if h.treatment_dimension is not None:
        results = compute_group_results(kpi_engine, h.outcome, h.treatment_dimension, pre_start, pre_end)
        value, sample = group_slice(results, h.treatment_dimension, h.treatment_group_value)
    else:
        value, sample = _kpi_single_value(kpi_engine, h.treatment, pre_start, pre_end)
    if sample >= 1 and value is not None:
        return CheckResult("treatment_variation", CheckResultStatus.PASS,
                            f"treatment group has {sample} observations, value={value}.")
    return CheckResult("treatment_variation", CheckResultStatus.HARD_FAIL,
                        f"treatment group '{h.treatment_group_value or h.treatment}' has zero observations in "
                        f"{pre_start}..{pre_end}.")


def _check_control_variation(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                              requester_clearance: str) -> CheckResult:
    method_needs_control = h.proposed_method.value == "DIFFERENCE_IN_DIFFERENCES" or h.control_group_value is not None
    if not method_needs_control and h.treatment_dimension is None:
        return CheckResult("control_variation", CheckResultStatus.NOT_APPLICABLE,
                            "this hypothesis's proposed method does not require a control group.")
    if h.control_group_value is None:
        return CheckResult("control_variation", CheckResultStatus.HARD_FAIL,
                            "no control_group_value specified on the hypothesis -- a control group is "
                            "required for any quasi-experimental method.")
    pre_start = _period_bound(h.treatment_period, "start") or _period_bound(h.treatment_period, "date")
    pre_end = _period_bound(h.treatment_period, "end") or _period_bound(h.treatment_period, "date")
    results = compute_group_results(kpi_engine, h.outcome, h.treatment_dimension, pre_start, pre_end)
    value, sample = group_slice(results, h.treatment_dimension, h.control_group_value,
                                  exclude_value=h.treatment_group_value)
    if sample >= 1 and value is not None:
        return CheckResult("control_variation", CheckResultStatus.PASS,
                            f"control group '{h.control_group_value}' has {sample} observations, value={value}.")
    return CheckResult("control_variation", CheckResultStatus.HARD_FAIL,
                        f"control group '{h.control_group_value}' has zero observations in {pre_start}..{pre_end}.")


def _check_sample_size(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                        requester_clearance: str) -> CheckResult:
    contract = _kpi_or_none(registry, h.outcome)
    if contract is None:
        return CheckResult("sample_size", CheckResultStatus.NOT_APPLICABLE, "outcome not resolvable.")
    minimum = contract["data_quality_requirements"]["minimum_observations"]
    start = _period_bound(h.outcome_period, "start") or _period_bound(h.outcome_period, "date")
    end = _period_bound(h.outcome_period, "end") or _period_bound(h.outcome_period, "date")
    if h.treatment_dimension is not None:
        results = compute_group_results(kpi_engine, h.outcome, h.treatment_dimension, start, end)
        _, sample = group_slice(results, h.treatment_dimension, h.treatment_group_value)
    else:
        _, sample = _kpi_single_value(kpi_engine, h.outcome, start, end)
    if sample >= minimum:
        return CheckResult("sample_size", CheckResultStatus.PASS,
                            f"sample_size={sample} meets the KPI contract's minimum_observations={minimum}.")
    if sample >= minimum / 2:
        return CheckResult("sample_size", CheckResultStatus.SOFT_FAIL,
                            f"sample_size={sample} is below the KPI contract's minimum_observations={minimum}.")
    return CheckResult("sample_size", CheckResultStatus.HARD_FAIL,
                        f"sample_size={sample} is far below the KPI contract's minimum_observations={minimum} "
                        "(less than half).")


def _check_missingness(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                        requester_clearance: str) -> CheckResult:
    contract = _kpi_or_none(registry, h.outcome)
    if contract is None:
        return CheckResult("missingness", CheckResultStatus.NOT_APPLICABLE, "outcome not resolvable.")
    threshold_pct = contract["data_quality_requirements"]["coverage_threshold_pct"]
    start = _period_bound(h.outcome_period, "start") or _period_bound(h.outcome_period, "date")
    end = _period_bound(h.outcome_period, "end") or _period_bound(h.outcome_period, "date")
    try:
        result = kpi_engine.compute(KPIRequest(kpi_id=h.outcome, start_date=start, end_date=end))
    except (KPIRequestError, KeyError, ValueError):
        return CheckResult("missingness", CheckResultStatus.HARD_FAIL, f"could not compute coverage for '{h.outcome}'.")
    coverage = None if isinstance(result, list) else result.coverage
    if coverage is None:
        return CheckResult("missingness", CheckResultStatus.SOFT_FAIL,
                            f"coverage for '{h.outcome}' is unknown -- treated as a soft concern, not a block.")
    coverage_pct = coverage * 100
    if coverage_pct >= threshold_pct:
        return CheckResult("missingness", CheckResultStatus.PASS,
                            f"coverage={coverage_pct:.2f}% meets the contract's {threshold_pct}% threshold.")
    if coverage_pct >= threshold_pct / 2:
        return CheckResult("missingness", CheckResultStatus.SOFT_FAIL,
                            f"coverage={coverage_pct:.2f}% is below the contract's {threshold_pct}% threshold.")
    return CheckResult("missingness", CheckResultStatus.HARD_FAIL,
                        f"coverage={coverage_pct:.2f}% is far below the contract's {threshold_pct}% threshold "
                        "(less than half).")


def _check_confounders(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                        requester_clearance: str) -> CheckResult:
    # Imported lazily to avoid a module-level import cycle (diagnostics.py
    # imports causal.models, not the other way around) -- see diagnostics.py.
    from causal.diagnostics import detect_known_confounders

    confounders = detect_known_confounders(h)
    if not confounders:
        return CheckResult("confounders", CheckResultStatus.PASS, "no known/suspected confounders detected.")
    names = ", ".join(c.name for c in confounders)
    # Never a HARD_FAIL: a confounder is a governance flag ("report it"), not
    # an eligibility blocker (task's own words: "Explicitly report known/
    # suspected confounders" -- not "reject the hypothesis").
    return CheckResult("confounders", CheckResultStatus.SOFT_FAIL,
                        f"known/suspected confounder(s) detected: {names}.")


def _check_consistent_grain(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                             requester_clearance: str) -> CheckResult:
    contract = _kpi_or_none(registry, h.outcome)
    if contract is None:
        return CheckResult("consistent_grain", CheckResultStatus.NOT_APPLICABLE, "outcome not resolvable.")
    if h.unit_of_analysis in ("order", "review", "month", "day", "week"):
        return CheckResult("consistent_grain", CheckResultStatus.PASS,
                            f"unit_of_analysis '{h.unit_of_analysis}' matches a base time/record grain.")
    dim = registry.get_dimension(h.outcome, h.unit_of_analysis)
    if dim is not None and dim["supported"]:
        return CheckResult("consistent_grain", CheckResultStatus.PASS,
                            f"unit_of_analysis '{h.unit_of_analysis}' is a supported dimension of '{h.outcome}'.")
    reason = dim.get("unsupported_reason", "not declared") if dim else "not declared"
    return CheckResult(
        "consistent_grain", CheckResultStatus.HARD_FAIL,
        f"unit_of_analysis '{h.unit_of_analysis}' is not a supported grain/dimension for outcome "
        f"'{h.outcome}' per its KPI contract ({reason}).",
    )


def _check_consistent_kpi_definition(h: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                                      requester_clearance: str) -> CheckResult:
    outcome_contract = _kpi_or_none(registry, h.outcome)
    if outcome_contract is None:
        return CheckResult("consistent_kpi_definition", CheckResultStatus.NOT_APPLICABLE, "outcome not resolvable.")
    window = outcome_contract["valid_time_window"]
    full_start, full_end = window["full_data_start"], window["full_data_end"]

    if h.treatment_dimension is None:
        treatment_contract = _kpi_or_none(registry, h.treatment)
        if treatment_contract is not None and treatment_contract["valid_time_window"] != window:
            return CheckResult(
                "consistent_kpi_definition", CheckResultStatus.HARD_FAIL,
                f"treatment '{h.treatment}' and outcome '{h.outcome}' do not share the same governed "
                "valid_time_window.",
            )

    for label, period in (("treatment_period", h.treatment_period), ("outcome_period", h.outcome_period)):
        start = _to_month(_period_bound(period, "start") or _period_bound(period, "date"))
        end = _to_month(_period_bound(period, "end") or _period_bound(period, "date"))
        if start is None or end is None:
            continue
        if start < _to_month(full_start) or end > _to_month(full_end):
            return CheckResult(
                "consistent_kpi_definition", CheckResultStatus.HARD_FAIL,
                f"{label} {period} falls outside the governed full_data window {full_start}..{full_end}.",
            )
    return CheckResult("consistent_kpi_definition", CheckResultStatus.PASS,
                        "treatment/outcome share a governed KPI definition and window.")


_CHECK_FUNCTIONS = (
    _check_treatment_exists,
    _check_outcome_exists,
    _check_treatment_precedes_outcome,
    _check_sufficient_pre_period,
    _check_sufficient_post_period,
    _check_treatment_variation,
    _check_control_variation,
    _check_sample_size,
    _check_missingness,
    _check_confounders,
    _check_consistent_grain,
    _check_consistent_kpi_definition,
)


def check_eligibility(hypothesis: CausalHypothesis, kpi_engine: KPIEngine, registry: SemanticRegistry,
                       requester_clearance: str = "INTERNAL") -> EligibilityReport:
    """Runs all 12 checks, always in the same fixed order, and rolls them up
    into one verdict:

        any HARD_FAIL                                    -> INELIGIBLE
        ...unless the ONLY hard fail is treatment_precedes_outcome         -> CAUSAL_INELIGIBLE
        else any SOFT_FAIL                                -> PARTIALLY_ELIGIBLE
        else                                               -> ELIGIBLE
    """
    checks = [fn(hypothesis, kpi_engine, registry, requester_clearance) for fn in _CHECK_FUNCTIONS]
    hard = [c.check_name for c in checks if c.status == CheckResultStatus.HARD_FAIL]
    soft = [c.check_name for c in checks if c.status == CheckResultStatus.SOFT_FAIL]

    if hard:
        if hard == ["treatment_precedes_outcome"]:
            verdict = EligibilityVerdict.CAUSAL_INELIGIBLE
        else:
            verdict = EligibilityVerdict.INELIGIBLE
    elif soft:
        verdict = EligibilityVerdict.PARTIALLY_ELIGIBLE
    else:
        verdict = EligibilityVerdict.ELIGIBLE

    return EligibilityReport(
        hypothesis_id=hypothesis.hypothesis_id, verdict=verdict, checks=checks,
        hard_fail_checks=hard, soft_fail_checks=soft,
    )
