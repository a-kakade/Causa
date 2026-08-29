"""
routes/decisions.py — GET /api/investigations/{id}/recommendations.

Bridges the investigation's own hypothesis_results/causal results into a
DriverSignal (decision.bridge.*) and runs the REAL
decision.ranking.run_decision_pipeline -- never generates a recommendation
itself. Computed lazily, cached on the InvestigationRecord.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_investigation_store
from api.serializers import decision_result_dict
from api.store import InvestigationStore

router = APIRouter(prefix="/api/investigations", tags=["decisions"])

_ontology = None
_scoring_config = None


def _decision_config():
    global _ontology, _scoring_config
    if _ontology is None:
        from decision.ontology import DecisionOntology, DecisionScoringConfig
        _ontology = DecisionOntology.load()
        _scoring_config = DecisionScoringConfig.load()
    return _ontology, _scoring_config


@router.get("/{investigation_id}/recommendations")
def get_recommendations(investigation_id: str, store: InvestigationStore = Depends(get_investigation_store)):
    from decision.bridge import driver_signal_from_hypothesis_result
    from decision.ranking import run_decision_pipeline

    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")
    if record.decision_result is not None:
        return record.decision_result

    ontology, scoring_config = _decision_config()

    driver_signal = None
    hypothesis_by_id = {h.hypothesis_id: h for h in record.state.hypotheses}
    # Bridge from Step 5's own hypothesis_results (real, in-memory dataclasses
    # on record.state) -- record.causal_results is stored pre-serialized
    # (dicts), so the Step 6-sourced bridge path is intentionally not used
    # here; a future iteration could re-run causal analysis live to get a
    # real CausalResult object for driver_signal_from_causal_result instead.
    for result in record.state.hypothesis_results:
        if result.status != "SUPPORTED":
            continue
        hyp = hypothesis_by_id.get(result.hypothesis_id)
        driver_signal = driver_signal_from_hypothesis_result(result, hyp, record.state, ontology, business_context={})
        if driver_signal is not None:
            break

    if driver_signal is None:
        response = {
            "investigation_id": investigation_id, "top_recommendation": None, "alternatives": [],
            "conditional": [], "blocked": [], "all_candidates_evaluated": 0,
            "pipeline_trace": ["no SUPPORTED hypothesis result bridged into a known decision-ontology driver "
                               "for this investigation -- no recommendation was generated"],
        }
        store.update_decision(investigation_id, response)
        return response

    decision_result = run_decision_pipeline(driver_signal, ontology, scoring_config, request_id=investigation_id)
    result_dict = decision_result_dict(decision_result)
    response = {"investigation_id": investigation_id, **result_dict}
    store.update_decision(investigation_id, response)
    return response
