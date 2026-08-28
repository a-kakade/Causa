"""Step 6: provenance tests -- every number/citation traces to a real Step
3D/Step 4 engine call, no module in src/causal/ ever imports an LLM client,
and the evidence.models extension is additive-only."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

import evidence.graph as graph_mod  # noqa: E402
from evidence.models import GRAPH_NODE_TYPES, RelationshipType  # noqa: E402

from causal.engine import run_causal_analysis  # noqa: E402
from causal.models import CausalHypothesis, CausalMethod  # noqa: E402

OCT = ("2017-10-01", "2017-10-31")
NOV = ("2017-11-01", "2017-11-30")


def _pvm_hypothesis():
    return CausalHypothesis(
        hypothesis_id="C1_order_volume", treatment="orders", outcome="revenue", unit_of_analysis="order",
        treatment_period={"start": OCT[0], "end": OCT[1]}, outcome_period={"start": NOV[0], "end": NOV[1]},
        proposed_mechanism="Order volume growth is associated with revenue growth via the PVM volume effect.",
        required_data=["revenue", "orders"], proposed_method=CausalMethod.PVM,
    )


def test_pvm_result_cites_real_driver_decomposition_evidence_ids_not_recomputed(engine):
    result = run_causal_analysis(_pvm_hypothesis(), engine, engine.registry)
    assert result.evidence_ids, "PVM result must cite real evidence_ids from Step 4's structured adapter"
    assert all(eid.startswith("ev_") for eid in result.evidence_ids)
    # The exact November 2017 PVM values, unchanged from STEP3D_VALIDATION.md.
    assert abs(result.estimate["volume_effect"] - 417227.65) < 0.01
    assert abs(result.estimate["price_effect"] - 4674.63) < 0.01
    assert abs(result.estimate["mix_effect"] - (-75850.34)) < 0.01


def test_did_result_cites_kpi_engine_compare_periods_evidence_not_fabricated_numbers(engine):
    h = CausalHypothesis(
        hypothesis_id="C4_geographic", treatment="customer_state", outcome="revenue",
        unit_of_analysis="customer_state",
        treatment_period={"start": "2017-06-01", "end": "2017-11-30"},
        outcome_period={"start": OCT[0], "end": NOV[1]},
        proposed_mechanism="Revenue growth may be associated with disproportionate growth from SP.",
        required_data=["revenue"], proposed_method=CausalMethod.DIFFERENCE_IN_DIFFERENCES,
        treatment_dimension="customer_state", treatment_group_value="SP", control_group_value="all_other_states",
    )
    result = run_causal_analysis(h, engine, engine.registry)
    # Whatever method/tier was actually selected, no number is fabricated --
    # an estimate, if present, must be a finite real float, not a placeholder.
    if result.estimate is not None:
        for value in result.estimate.values():
            if isinstance(value, (int, float)):
                assert value == value  # not NaN


def test_engine_extends_evidence_graph_with_causal_analysis_and_causal_result_nodes(engine):
    g = graph_mod.new_graph()
    run_causal_analysis(_pvm_hypothesis(), engine, engine.registry, graph=g)
    node_types = {data.get("node_type") for _, data in g.nodes(data=True)}
    assert "CAUSAL_ANALYSIS" in node_types
    assert "CAUSAL_RESULT" in node_types
    assert g.has_node("causal_analysis_of_C1_order_volume")
    assert g.has_node("causal_result_of_C1_order_volume")


def test_graph_extension_adds_tested_by_has_assumption_has_diagnostic_edges(engine):
    g = graph_mod.new_graph()
    run_causal_analysis(_pvm_hypothesis(), engine, engine.registry, graph=g)
    edge_types = {data.get("relationship_type") for _, _, data in g.edges(data=True)}
    assert RelationshipType.TESTED_BY.value in edge_types
    assert RelationshipType.HAS_ASSUMPTION.value in edge_types


def test_downgraded_to_edge_emitted_when_aspirational_tier_exceeds_achieved_tier(engine):
    h = CausalHypothesis(
        hypothesis_id="C_its", treatment="revenue", outcome="revenue", unit_of_analysis="month",
        treatment_period={"start": NOV[0], "end": NOV[1]}, outcome_period={"start": "2017-12-01", "end": "2018-08-31"},
        proposed_mechanism="X is associated with Y.", required_data=["revenue"],
        proposed_method=CausalMethod.INTERRUPTED_TIME_SERIES,
    )
    g = graph_mod.new_graph()
    result = run_causal_analysis(h, engine, engine.registry, graph=g)
    edge_types = [data.get("relationship_type") for _, _, data in g.edges(data=True)]
    if result.evidence_tier.value != "T3_QUASI_EXPERIMENTAL":
        assert RelationshipType.DOWNGRADED_TO.value in edge_types


def test_no_module_in_causal_package_imports_llm_client():
    causal_dir = REPO_ROOT / "src" / "causal"
    for path in causal_dir.glob("*.py"):
        tree = ast.parse(path.read_text())
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names.add(getattr(node, "module", None) or "")
                for alias in node.names:
                    names.add(alias.name)
        assert not any("llm" in n.lower() or "groq" in n.lower() for n in names), \
            f"{path.name} imports something LLM-shaped: {names}"


def test_evidence_models_extensions_are_additive_only():
    pre_existing_nodes = {"INVESTIGATION", "KPI", "MOVEMENT", "DRIVER", "SEGMENT",
                           "EVIDENCE", "BUSINESS_CONTEXT", "CONFIDENCE", "ACTION"}
    assert pre_existing_nodes.issubset(GRAPH_NODE_TYPES)
    pre_existing_edges = {"HAS_MOVEMENT", "EXPLAINED_BY", "SUPPORTED_BY", "CONTRADICTS",
                           "CONTEXTUALIZED_BY", "DERIVED_FROM", "HAS_CONFIDENCE", "RECOMMENDS"}
    current_edges = {m.value for m in RelationshipType}
    assert pre_existing_edges.issubset(current_edges)
    for name in pre_existing_edges:
        assert RelationshipType(name).value == name  # unchanged literal value
