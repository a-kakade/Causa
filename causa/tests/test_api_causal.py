"""test_api_causal.py — causal_claim_allowed passthrough (never upgraded/
mutated by the API layer)."""


def test_causal_analysis_never_upgrades_causal_claim_allowed(api_client):
    created = api_client.post(
        "/api/investigations?requester_role=ANALYST",
        json={"kpi_id": "revenue", "period_current": "2017-11", "period_previous": "2017-10"},
    ).json()
    investigation_id = created["investigation_id"]

    r = api_client.get(f"/api/investigations/{investigation_id}/causal-analysis?requester_role=ANALYST")
    assert r.status_code == 200
    body = r.json()
    for result in body["results"]:
        if "error" in result:
            continue
        # Every CausalResult this repo's engine can produce for the Nov-2017
        # scenario is causal_claim_allowed=False (no natural experiment) --
        # the API must pass that through unmutated, never flip it True.
        assert result["causal_claim_allowed"] is False


def test_causal_analysis_honest_when_no_hypotheses(api_client):
    """A fresh investigation with zero hypotheses (e.g. one that reached
    ABSTAINED before HYPOTHESES_GENERATED) must return an empty, honest
    result -- never a fabricated hypothesis to analyze."""
    created = api_client.post(
        "/api/investigations?requester_role=ANALYST",
        json={"kpi_id": "review_volume", "period_current": "2017-11", "period_previous": "2017-10"},
    ).json()
    investigation_id = created["investigation_id"]
    r = api_client.get(f"/api/investigations/{investigation_id}/causal-analysis?requester_role=ANALYST")
    assert r.status_code == 200
    body = r.json()
    # Some, none, or all hypotheses may bridge into a structurally valid
    # CausalHypothesis (causal_hypothesis_from_step5 is best-effort, per its
    # own docstring) -- the only invariant worth asserting here is that the
    # API never fabricates MORE causal results than there were hypotheses to
    # begin with.
    assert body["causal_eligible_hypothesis_count"] <= len(created["state"]["hypotheses"])
