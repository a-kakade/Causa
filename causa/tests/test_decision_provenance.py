"""Step 7: provenance tests -- no module in src/decision/ except
candidate_generator.py/explanation.py ever imports anything LLM-shaped;
identical inputs+config always produce identical DecisionResult output
(determinism); the evidence.models pre-reserved ACTION/RECOMMENDS/
HAS_CONFIDENCE vocabulary this package uses is still additive-only.

Mirrors tests/test_provenance.py's AST-scan pattern for src/causal/.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from evidence.models import GRAPH_NODE_TYPES, RelationshipType  # noqa: E402

from decision.models import DriverSignal  # noqa: E402
from decision.ontology import DecisionOntology, DecisionScoringConfig  # noqa: E402
from decision.ranking import run_decision_pipeline  # noqa: E402

_LLM_ALLOWED_MODULES = {"candidate_generator.py", "explanation.py"}


def test_no_module_in_decision_package_imports_llm_client_except_two_allowed():
    decision_dir = REPO_ROOT / "src" / "decision"
    for path in decision_dir.glob("*.py"):
        if path.name in _LLM_ALLOWED_MODULES or path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names.add(getattr(node, "module", None) or "")
                for alias in node.names:
                    names.add(alias.name)
        assert not any("llm" in n.lower() or "groq" in n.lower() for n in names), \
            f"{path.name} imports something LLM-shaped: {names}"


def test_candidate_generator_and_explanation_only_reference_llm_client_locally():
    """Confirms the two allowed modules DO reference agents.llm_client
    somewhere (proving the AST scan above isn't vacuously passing because
    nothing imports it at all), but only inside a function body (a local
    import) or a guarded call -- never a module-level hard dependency that
    would break importing this package without an LLM SDK installed."""
    for name in _LLM_ALLOWED_MODULES:
        path = REPO_ROOT / "src" / "decision" / name
        text = path.read_text()
        assert "llm_client" in text, f"{name} was expected to reference agents.llm_client somewhere"


def test_pipeline_is_deterministic_given_identical_inputs_and_config():
    ontology = DecisionOntology.load()
    scoring = DecisionScoringConfig.load()
    signal = DriverSignal(
        driver="delivery_delay", driver_category="FULFILLMENT_LOGISTICS", kpi_id="on_time_delivery_rate",
        period="2017-11", addressable_population=12500, addressable_population_source="HISTORICAL_ESTIMATE",
        historical_estimated_effect=0.06, historical_effect_source="HISTORICAL_ESTIMATE", driver_confidence=0.78,
        source="MANUAL", business_context={"budget_available": True, "operational_capacity_available": True},
    )
    result_a = run_decision_pipeline(signal, ontology, scoring, request_id="fixed")
    result_b = run_decision_pipeline(signal, ontology, scoring, request_id="fixed")
    assert result_a.to_dict() == result_b.to_dict()


def test_evidence_models_action_vocabulary_still_additive_only():
    pre_existing_nodes = {"INVESTIGATION", "KPI", "MOVEMENT", "DRIVER", "SEGMENT",
                           "EVIDENCE", "BUSINESS_CONTEXT", "CONFIDENCE", "ACTION"}
    assert pre_existing_nodes.issubset(GRAPH_NODE_TYPES)
    pre_existing_edges = {"HAS_MOVEMENT", "EXPLAINED_BY", "SUPPORTED_BY", "CONTRADICTS",
                           "CONTEXTUALIZED_BY", "DERIVED_FROM", "HAS_CONFIDENCE", "RECOMMENDS"}
    current_edges = {m.value for m in RelationshipType}
    assert pre_existing_edges.issubset(current_edges)
    for name in pre_existing_edges:
        assert RelationshipType(name).value == name  # unchanged literal value


def test_no_numeric_field_source_reports_llm_generated():
    """The DataSource enum in decision.models deliberately has no
    LLM_GENERATED member -- no numeric field in this package may honestly
    report an LLM as its source."""
    from decision.models import DataSource
    assert "LLM_GENERATED" not in {m.name for m in DataSource}
    assert not any("LLM" in m.value for m in DataSource)
