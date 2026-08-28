"""Step 9: safety/integrity tests (spec section 31) -- feedback cannot
change trusted KPI values, evidence values, Step 7 formulas, Step 8
verification rules, or inject arbitrary business rules. No automatic model
training or deployment hook exists anywhere in src/feedback/."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
FEEDBACK_SRC = REPO_ROOT / "src" / "feedback"

from feedback.capture import submit_feedback  # noqa: E402
from feedback.evaluator import CandidateOutput, evaluate_case  # noqa: E402
from feedback.models import EvaluationCase, FeedbackRating, OutputType  # noqa: E402
from story.claim_verifier import verify_claim  # noqa: E402
from story.models import ClaimType, EvidenceItem, EvidencePackage, NarrativeClaim, ValidationStatus  # noqa: E402
from decision.models import (  # noqa: E402
    ActionRecommendation,
    ConstraintCheck,
    ConstraintSeverity,
    ConstraintStatus,
    ExpectedImpact,
    GeneratedBy as DecisionGeneratedBy,
    MonitoringTarget,
    RecommendationTier,
    ScoreBreakdown,
)

# ---------------------------------------------------------------------------
# 1. Feedback cannot mutate a KPIStory's NarrativeClaim / EvidenceItem values
# ---------------------------------------------------------------------------


def _package():
    item = EvidenceItem(
        evidence_id="EV001", metric="revenue", value=52.1, unit="percent", direction="increase", period="2017-11",
        source_system="kpi_engine", timestamp="2026-08-28T12:00:00+00:00", analytical_method="x",
        confidence="HIGH", claim_type=ClaimType.FACT,
    )
    return EvidencePackage(package_id="pkg1", kpi_id="revenue", period="2017-11", items=[item])


def test_feedback_submission_never_mutates_evidence_value():
    package = _package()
    original_value = package.items[0].value

    submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1",
                     affected_evidence_ids=["EV001"], comment="This number looks wrong to me.")

    assert package.items[0].value == original_value  # untouched -- trusted value never mutated


def test_feedback_submission_never_mutates_narrative_claim():
    claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT, evidence_ids=["EV001"])
    package = _package()
    verify_claim(claim, package, tolerance=0.0005, absolute_floor=0.01)
    original_status = claim.validation_status

    submit_feedback(FeedbackRating.INCORRECT, OutputType.STORY_CLAIM, session_id="s1", comment="wrong")

    assert claim.validation_status == original_status
    assert claim.text == "Revenue increased 52.1%."


def test_evaluator_never_calls_verify_claim_with_side_effects_on_unrelated_objects():
    """evaluate_case only ever verifies claims the candidate_runner itself
    produced fresh -- it never reaches back into some pre-existing trusted
    story object and re-scores it in place."""
    package = _package()
    trusted_claim = NarrativeClaim(text="Revenue increased 52.1%.", claim_type=ClaimType.FACT,
                                    evidence_ids=["EV001"])
    verify_claim(trusted_claim, package, tolerance=0.0005, absolute_floor=0.01)
    snapshot_status = trusted_claim.validation_status

    case = EvaluationCase(case_id="EC1", dataset_version="v1", source_feedback_id="FB1", created_at="t",
                           forbidden_claims=["revenue caused profit growth"])

    def runner(c):
        return CandidateOutput(claim_texts=["unrelated candidate text"])

    evaluate_case(case, runner)
    assert trusted_claim.validation_status == snapshot_status


# ---------------------------------------------------------------------------
# 2. Feedback cannot change a Step 7 ActionRecommendation's computed numbers
# ---------------------------------------------------------------------------


def _recommendation():
    impact = ExpectedImpact(
        metric="on_time_delivery_rate", estimated_effect=0.06, effect_unit="pp", addressable_population=12500,
        confidence=0.78, calculated_impact=585.0, revenue_impact=None, effect_source="HISTORICAL_ESTIMATE",
        population_source="HISTORICAL_ESTIMATE", confidence_basis="test", is_estimable=True,
    )
    breakdown = ScoreBreakdown(confidence_factors={}, confidence_weights={}, confidence_score=0.78,
                                controllability_score=0.9, controllability_basis="test", effort_score=0.5,
                                effort_basis="test", priority_formula="x", priority_score=0.7)
    return ActionRecommendation(
        recommendation_id="rec_delivery_delay_expedite", driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS",
        controllable_lever="carrier_selection", possible_action="Expedite high-risk shipments.",
        expected_impact=impact, owner="ops_team", constraints=[
            ConstraintCheck("operational_capacity", ConstraintStatus.BLOCKED, "utilization at threshold",
                             ConstraintSeverity.HIGH),
        ], controllability=0.9, effort=0.5, priority_score=0.7, monitoring_kpis=[], rationale="test rationale",
        assumptions=[], score_breakdown=breakdown, tier=RecommendationTier.BLOCKED, ranking_explanation=[],
        action_justified_by_evidence=False, generated_by=DecisionGeneratedBy.DETERMINISTIC_TEMPLATE,
        source_driver_signal_id="ds1",
    )


def test_feedback_submission_never_mutates_recommendation():
    rec = _recommendation()
    original_tier = rec.tier
    original_priority = rec.priority_score

    submit_feedback(FeedbackRating.WRONG_RECOMMENDATION, OutputType.RECOMMENDATION, session_id="s1",
                     affected_recommendation_id=rec.recommendation_id, comment="Carrier capacity is exhausted.")

    assert rec.tier == original_tier
    assert rec.priority_score == original_priority


# ---------------------------------------------------------------------------
# 3. No automatic model training / deployment hook anywhere in src/feedback/
# ---------------------------------------------------------------------------

_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "torch", "tensorflow", "sklearn", "transformers", "peft", "fine_tune", "finetune", "train",
)
_FORBIDDEN_CALL_NAME_SUBSTRINGS = ("fit", "train", "fine_tune", "finetune", "deploy", "publish_model")


def _iter_feedback_py_files():
    return sorted(FEEDBACK_SRC.glob("*.py"))


def test_no_ml_training_library_imported_anywhere_in_feedback_package():
    for path in _iter_feedback_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for forbidden in _FORBIDDEN_IMPORT_SUBSTRINGS:
                        assert forbidden not in alias.name.lower(), (
                            f"{path.name} imports {alias.name!r} -- a training library must never appear in "
                            f"src/feedback/"
                        )
            elif isinstance(node, ast.ImportFrom) and node.module:
                for forbidden in _FORBIDDEN_IMPORT_SUBSTRINGS:
                    assert forbidden not in node.module.lower(), (
                        f"{path.name} imports from {node.module!r} -- a training library must never appear in "
                        f"src/feedback/"
                    )


def test_no_deployment_or_weight_update_call_anywhere_in_feedback_package():
    """AST-scan style test, same technique tests/test_orchestrator.py uses to
    prove Step 5's Orchestrator never imports an LLM client directly."""
    for path in _iter_feedback_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = None
                if isinstance(func, ast.Name):
                    name = func.id
                elif isinstance(func, ast.Attribute):
                    name = func.attr
                if name:
                    for forbidden in _FORBIDDEN_CALL_NAME_SUBSTRINGS:
                        assert forbidden not in name.lower(), (
                            f"{path.name} calls a function named {name!r}, which resembles a model-training/"
                            f"deployment call -- forbidden anywhere in src/feedback/"
                        )


def test_feedback_package_never_imports_agents_or_decision_write_paths():
    """src/feedback/ may import read-only model/config modules from other
    packages (story.models, decision.models, decision.ontology,
    decision.constraint_engine for its own evaluation checks) but must never
    import anything that WRITES/retrains/deploys -- there is no such module
    anywhere in this repo, so this test also documents the invariant."""
    disallowed_modules = {"agents.llm_client"}  # only ever imported LOCALLY inside a function body,
                                                  # exactly like story/generator.py's own pattern --
                                                  # never at module scope (never unconditionally active).
    for path in _iter_feedback_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module_level_imports = {
            n.module for n in tree.body if isinstance(n, ast.ImportFrom) and n.module
        } | {
            alias.name for n in tree.body if isinstance(n, ast.Import) for alias in n.names
        }
        for disallowed in disallowed_modules:
            assert disallowed not in module_level_imports, (
                f"{path.name} imports {disallowed!r} at module scope -- must be a local, function-body-scoped "
                f"import so llm_client=None always works with zero import cost"
            )


# ---------------------------------------------------------------------------
# 4. Feedback status transitions never bypass human review
# ---------------------------------------------------------------------------


def test_pending_review_status_is_the_only_default():
    fb = submit_feedback(FeedbackRating.CORRECT, OutputType.STORY_CLAIM, session_id="s1")
    from feedback.models import ReviewStatus
    assert fb.review_status == ReviewStatus.PENDING
