"""
step5_investigate_november_2017.py — builds the real ToolContext, runs a
full Step 5 investigation for Revenue October -> November 2017 (twice: once
as RequesterRole.ANALYST, once as RequesterRole.EXECUTIVE, to demonstrate
the RBAC cap), runs the Step 5 test suite, and writes
reports/step5_validation.json.

Every REQUIRED_* constant below is used ONLY as a post-hoc assertion target
against the finished InvestigationState -- never fed into agent logic, same
discipline scripts/step4_validate_engine.py already establishes for its own
REQUIRED_KPI_MOVEMENTS/REQUIRED_PVM.

Real-LLM vs dry run: if agents.llm_client.has_groq_credentials() is true AND
a real API call actually succeeds, this script runs the ANALYST investigation
against the real Groq-hosted model. Otherwise (no credentials, or no network
reachability -- both true in the sandbox this was authored in) it falls back
to a scripted agents.llm_client.FakeLLMClient and the report states
"dry_run": true explicitly -- never silently presented as a real run.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from lib.raw_loader import PROCESSED_DIR  # noqa: E402

from kpi.engine import KPIEngine  # noqa: E402
from kpi.semantic_registry import SemanticRegistry  # noqa: E402

from agents import orchestrator  # noqa: E402
from agents.llm_client import FakeLLMClient, GroqLLMClient, LLMResponse, LLMUnavailable, has_groq_credentials  # noqa: E402
from agents.models import InvestigationStatus, RequesterRole  # noqa: E402
from tools.context import build_tool_context  # noqa: E402

CANONICAL_TABLES = [
    "dim_customer", "dim_product", "dim_seller",
    "fact_orders", "fact_order_items", "fact_payments", "fact_reviews",
    "agg_order_items", "agg_order_payments", "agg_order_reviews",
]

TEST_FILES = [
    "tests/test_state_machine.py", "tests/test_tool_gateway.py", "tests/test_rbac.py", "tests/test_budgets.py",
    "tests/test_numeric_guardrail.py", "tests/test_contradictions.py", "tests/test_confidence.py",
    "tests/test_hypothesis.py", "tests/test_evidence_agent.py", "tests/test_counter_evidence.py",
    "tests/test_orchestrator.py", "tests/test_prompt_injection.py",
]

# Assertion targets ONLY -- see module docstring. Sourced from
# STEP4_VALIDATION.md §3 (already independently validated against the same
# live-computed KPIEngine/driver_engine this script itself calls).
REQUIRED_REVENUE_PCT = 52.1
REQUIRED_REVENUE_ABSOLUTE = 346051.94
REQUIRED_ORDERS_PCT = 62.9
REQUIRED_AOV_PCT = -6.75
REQUIRED_PVM = {"volume": 417227.65, "price": 4674.63, "mix": -75850.34}
REQUIRED_DELIVERY_PCT = 27.87
REQUIRED_REVIEW_SCORE_PCT = -5.16


def run_tests() -> dict:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TEST_FILES, "-rf", "--tb=line"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    output = proc.stdout + proc.stderr
    failed = re.findall(r"^FAILED (\S+)", output, re.MULTILINE)
    n_passed = int(m.group(1)) if (m := re.search(r"(\d+) passed", output)) else 0
    n_failed = int(m.group(1)) if (m := re.search(r"(\d+) failed", output)) else 0
    return {"returncode": proc.returncode, "n_passed": n_passed, "n_failed": n_failed,
            "failed_tests": failed, "all_passed": proc.returncode == 0}


# ---------------------------------------------------------------------------
# Dry-run LLM script -- used only when a real Groq call is unreachable.
# Mirrors the ScriptedRoutingClient pattern in tests/_llm_test_helpers.py,
# duplicated here (not imported from tests/) since scripts/ should not
# depend on the test tree.
# ---------------------------------------------------------------------------

def _tool_call(call_id: str, name: str, arguments: dict) -> LLMResponse:
    return LLMResponse(
        content=[{"type": "tool_use", "id": call_id, "name": name, "input": arguments}],
        stop_reason="tool_use", input_tokens=0, output_tokens=0, model="dry_run_scripted_fallback",
        raw_message={"role": "assistant", "content": None,
                     "tool_calls": [{"id": call_id, "type": "function",
                                     "function": {"name": name, "arguments": json.dumps(arguments)}}]},
    )


def _last_tool_result(messages: list) -> str:
    last = messages[-1]
    return last.get("content", "") if last.get("role") == "tool" else ""


def _extract_ids(content: str) -> list:
    return re.findall(r'"(ev_[a-zA-Z0-9_]+)"', content)


class DryRunScriptedClient:
    """A single, reasonably realistic scripted investigation: proposes
    hypotheses about volume, delivery/review-score, and geographic
    concentration, gathers REAL evidence for each via the real Tool Gateway,
    and classifies/counters using the real evidence_ids that come back --
    only the model's own text/decisions are scripted, not the underlying
    computation."""

    def build_user_message(self, text: str) -> dict:
        return {"role": "user", "content": text}

    def build_tool_result_messages(self, results: list) -> list:
        return [{"role": "tool", "tool_call_id": i, "content": c} for i, c in results]

    def create(self, *, system: str, messages: list, tools: list, max_tokens: int = 4096) -> LLMResponse:
        if "Hypothesis Agent" in system:
            hyps = [
                {"driver": "volume", "dimension": "orders", "mechanism": "order-count expansion",
                 "statement": "Revenue growth may be associated with an increase in order volume.",
                 "expected_evidence": ["DRIVER_CONTRIBUTION:volume"], "falsification_evidence": []},
                {"driver": "delivery", "dimension": "avg_review_score", "mechanism": "service-quality feedback",
                 "statement": "Delivery deterioration may be associated with declining review scores.",
                 "expected_evidence": ["CONCURRENT_KPI:avg_delivery_days"], "falsification_evidence": []},
                {"driver": "geography", "dimension": "customer_state", "mechanism": "regional concentration",
                 "statement": "The revenue movement may be concentrated in a small number of customer states.",
                 "expected_evidence": ["SEGMENT_CONTRIBUTION:customer_state"], "falsification_evidence": []},
            ]
            return _tool_call("h1", "submit_hypotheses", {"hypotheses": hyps})

        if "Evidence Agent" in system:
            content = _last_tool_result(messages)
            if content:
                ids = _extract_ids(content)
                classifications = [{"evidence_id": i, "classification": "SUPPORTS", "rationale": "consistent direction"}
                                    for i in ids[:3]]
                return _tool_call("e2", "submit_evidence_classification", {"classifications": classifications})
            # Route the tool call by which hypothesis's user prompt this is.
            user_text = next((m["content"] for m in messages if m.get("role") == "user"), "")
            if "delivery" in user_text.lower():
                return _tool_call("e1", "get_concurrent_kpis", dict(
                    kpi_ids=["avg_delivery_days", "avg_review_score"], period_current_start="2017-11-01",
                    period_current_end="2017-11-30", period_current_label="2017-11",
                    period_previous_start="2017-10-01", period_previous_end="2017-10-31",
                    period_previous_label="2017-10"))
            dim = "customer_state" if "geograph" in user_text.lower() or "customer_state" in user_text else "product_category"
            return _tool_call("e1", "get_driver_decomposition", dict(
                kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
                period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
                period_previous_label="2017-10", segment_dimensions=[dim], top_n=10))

        # Counter-Evidence Agent
        content = _last_tool_result(messages)
        if content:
            return _tool_call("c2", "submit_counter_evidence_report", {
                "supporting_evidence": [], "contradicting_evidence": [],
                "unresolved_questions": ["Is the sample size sufficient across every affected segment?"],
                "contradiction_level": "WEAK",
            })
        return _tool_call("c1", "get_driver_decomposition", dict(
            kpi_id="revenue", period_current_start="2017-11-01", period_current_end="2017-11-30",
            period_current_label="2017-11", period_previous_start="2017-10-01", period_previous_end="2017-10-31",
            period_previous_label="2017-10", segment_dimensions=["seller_state"], top_n=10))


def _probe_real_groq() -> bool:
    if not has_groq_credentials():
        return False
    try:
        client = GroqLLMClient()
        client.create(system="You are a test probe. Reply with the single word OK.",
                       messages=[client.build_user_message("ping")], tools=[], max_tokens=8)
        return True
    except LLMUnavailable:
        return False


def main():
    t_start = time.time()
    canonical = {t: pd.read_parquet(PROCESSED_DIR / f"{t}.parquet") for t in CANONICAL_TABLES}
    registry = SemanticRegistry.load()
    registry.validate()
    kpi_engine = KPIEngine(registry=registry)

    ctx = build_tool_context(canonical, kpi_engine, registry)
    build_seconds = round(time.time() - t_start, 2)

    real_llm_reachable = _probe_real_groq()
    llm_client = GroqLLMClient() if real_llm_reachable else DryRunScriptedClient()

    t0 = time.time()
    analyst_state = orchestrator.run_investigation(
        investigation_id="november_2017_revenue_analyst", requester_role=RequesterRole.ANALYST, kpi_id="revenue",
        period_current_start="2017-11-01", period_current_end="2017-11-30", period_current_label="2017-11",
        period_previous_start="2017-10-01", period_previous_end="2017-10-31", period_previous_label="2017-10",
        ctx=ctx, llm_client=llm_client,
    )
    analyst_seconds = round(time.time() - t0, 2)

    t0 = time.time()
    executive_state = orchestrator.run_investigation(
        investigation_id="november_2017_revenue_executive", requester_role=RequesterRole.EXECUTIVE, kpi_id="revenue",
        period_current_start="2017-11-01", period_current_end="2017-11-30", period_current_label="2017-11",
        period_previous_start="2017-10-01", period_previous_end="2017-10-31", period_previous_label="2017-10",
        ctx=ctx, llm_client=DryRunScriptedClient() if not real_llm_reachable else GroqLLMClient(),
    )
    executive_seconds = round(time.time() - t0, 2)

    # ---- Post-hoc required-value checks (never fed into agent logic) ----
    movement_pct_check = {
        "computed": analyst_state.movement.get("percentage"), "required": REQUIRED_REVENUE_PCT,
        "matches": analyst_state.movement.get("percentage") is not None
        and abs(analyst_state.movement["percentage"] - REQUIRED_REVENUE_PCT) < 0.1,
    }
    movement_absolute_check = {
        "computed": analyst_state.movement.get("absolute"), "required": REQUIRED_REVENUE_ABSOLUTE,
        "matches": analyst_state.movement.get("absolute") is not None
        and abs(analyst_state.movement["absolute"] - REQUIRED_REVENUE_ABSOLUTE) < 1.0,
    }
    diversity_check = {
        "n_hypotheses": len(analyst_state.hypotheses),
        "within_bounds": 0 <= len(analyst_state.hypotheses) <= 5,
        "all_pairs_unique": len({(h.driver, h.dimension) for h in analyst_state.hypotheses}) == len(analyst_state.hypotheses),
    }
    citation_check = {"all_results_valid": all(r.is_valid() for r in analyst_state.hypothesis_results)}
    executive_no_internal_leak = {
        "leaked": any(ctx.evidence_store[c.evidence_id].security.classification.value == "INTERNAL"
                      for c in executive_state.classified_evidence if c.evidence_id in ctx.evidence_store),
    }

    all_checks_pass = (
        movement_pct_check["matches"] and movement_absolute_check["matches"] and diversity_check["within_bounds"]
        and diversity_check["all_pairs_unique"] and citation_check["all_results_valid"]
        and not executive_no_internal_leak["leaked"]
    )

    test_results = run_tests()

    from agents.telemetry import aggregate
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dry_run": not real_llm_reachable,
        "llm_provider": "groq", "llm_model": llm_client.model if hasattr(llm_client, "model") else "dry_run_scripted_fallback",
        "context_build_seconds": build_seconds,
        "analyst_run_seconds": analyst_seconds, "executive_run_seconds": executive_seconds,
        "required_value_checks": {
            "revenue_percentage_change": movement_pct_check, "revenue_absolute_change": movement_absolute_check,
            "hypothesis_diversity": diversity_check, "citation_completeness": citation_check,
            "executive_rbac_no_internal_leak": executive_no_internal_leak, "all_checks_pass": all_checks_pass,
        },
        "analyst_investigation": analyst_state.to_dict(),
        "executive_investigation": executive_state.to_dict(),
        "analyst_telemetry_summary": aggregate(analyst_state),
        "executive_telemetry_summary": aggregate(executive_state),
        "tests": test_results,
    }

    out_path = REPO_ROOT / "reports" / "step5_validation.json"
    out_path.write_text(json.dumps(report, indent=2, default=str))

    print(f"dry_run={report['dry_run']}  all_checks_pass={all_checks_pass}  "
          f"tests: {test_results['n_passed']} passed / {test_results['n_failed']} failed")
    print(f"analyst status={analyst_state.status.value}  confidence={analyst_state.confidence}")
    print(f"executive status={executive_state.status.value}  confidence={executive_state.confidence}")
    print(f"wrote {out_path}")

    if not (all_checks_pass and test_results["all_passed"]):
        sys.exit(1)


if __name__ == "__main__":
    main()
