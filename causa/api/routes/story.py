"""
routes/story.py — GET /api/investigations/{id}/story?persona=.

Builds a real story.models.EvidencePackage from the investigation's own
evidence (via story.evidence_package.build_evidence_package, which only
wraps real EvidenceObject/CausalResult/ActionRecommendation instances --
never computes a number), then calls the REAL story.engine.generate_kpi_story.
Uses FakeLLMClient by default -- never a silent live Groq call (mirrors
investigations.py's own policy).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.dependencies import get_engine_bundle, get_investigation_store
from api.serializers import kpi_story_dict
from api.store import InvestigationStore

router = APIRouter(prefix="/api/investigations", tags=["story"])

VALID_PERSONAS = ("EXECUTIVE", "FINANCE", "OPERATIONS", "MARKETING")


@router.get("/{investigation_id}/story")
def get_story(
    investigation_id: str, persona: str = Query(default="EXECUTIVE"),
    bundle=Depends(get_engine_bundle), store: InvestigationStore = Depends(get_investigation_store),
):
    from story.evidence_package import build_evidence_package
    from story.engine import generate_kpi_story
    from story.models import Persona, StoryGenerationFailed

    if persona not in VALID_PERSONAS:
        raise HTTPException(status_code=400, detail=f"persona must be one of {VALID_PERSONAS}")

    record = store.get(investigation_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No investigation {investigation_id!r}")

    cached = record.story.get(persona)
    if cached is not None:
        return cached

    from evidence.schema import EvidenceObject

    evidence_objects = [
        bundle.ctx.evidence_store[eid] for eid in record.state.evidence_ids
        if eid in bundle.ctx.evidence_store and isinstance(bundle.ctx.evidence_store[eid], EvidenceObject)
    ]
    if not evidence_objects:
        response = {
            "investigation_id": investigation_id, "persona": persona, "headline": None, "sections": [],
            "verification_status": "NOT_GENERATED",
            "reason": "No structured evidence is attached to this investigation yet -- a narrative would have "
                      "nothing verified to cite, so none was generated.",
        }
        store.update_story(investigation_id, persona, response)
        return response

    package = build_evidence_package(
        kpi_id=record.kpi_id, period=record.state.period, evidence_objects=evidence_objects,
        package_id=f"pkg_{investigation_id}",
    )
    try:
        story = generate_kpi_story(Persona(persona), package)
    except StoryGenerationFailed as exc:
        response = {"investigation_id": investigation_id, "persona": persona, "headline": None, "sections": [],
                    "verification_status": "FAILED", "reason": str(exc)}
        store.update_story(investigation_id, persona, response)
        return response

    response = {"investigation_id": investigation_id, **kpi_story_dict(story)}
    store.update_story(investigation_id, persona, response)
    return response
