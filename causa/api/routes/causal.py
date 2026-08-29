"""
routes/causal.py — GET /api/investigations/{id}/causal-analysis.

Bridges a Step 5 Hypothesis into a Step 6 CausalHypothesis via
causal.engine.causal_hypothesis_from_step5, then runs the REAL
causal.engine.run_causal_analysis. Computed lazily on first request, cached
in the InvestigationRecord thereafter. If no hypothesis bridges cleanly
(e.g. the real Nov-2017 run ABSTAINED with no usable hypotheses), this
returns an empty, honest result -- never a manufactured fallback hypothesis
(that fallback-authoring is script-only, per causal.engine's own docstring).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_engine_bundle, get_investigation_store, get_requester_clearance
from api.serializers import causal_result_dict
from api.store import InvestigationStore

router = APIRouter(prefix="/api/investigations", tags=["causal"])


@router.get("/{investigation_id}/causal-analysis")
def get_causal_analysis(
    investigation_id: str, bundle=Depends(get_engine_bundle),
    store: InvestigationStore = Depends(get_investigation_store),
    requester_clearance: str = Depends(get_requester_clearance),
):
    from causal.engine import causal_hypothesis_from_step5, run_causal_analysis

    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")

    results = []
    for hypothesis in record.state.hypotheses:
        cached = record.causal_results.get(hypothesis.hypothesis_id)
        if cached is not None:
            results.append(cached)
            continue
        causal_hypothesis = causal_hypothesis_from_step5(hypothesis, record.state)
        if causal_hypothesis is None:
            continue
        try:
            causal_result = run_causal_analysis(
                causal_hypothesis, bundle.kpi_engine, bundle.registry,
                graph=bundle.ctx.graph, requester_clearance=requester_clearance,
            )
        except Exception as exc:  # noqa: BLE001 -- one hypothesis's failure must not block the others
            results.append({"hypothesis_id": hypothesis.hypothesis_id, "error": str(exc)})
            continue
        result_dict = causal_result_dict(causal_result)
        store.update_causal(investigation_id, hypothesis.hypothesis_id, result_dict)
        results.append(result_dict)

    return {
        "investigation_id": investigation_id,
        "causal_eligible_hypothesis_count": len(results),
        "results": results,
        "note": "Empty results means no Step 5 hypothesis bridged into a structurally valid causal "
                "hypothesis for this investigation (e.g. the investigation abstained) -- this is never "
                "backfilled with a fabricated hypothesis.",
    }
