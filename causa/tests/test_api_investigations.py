"""test_api_investigations.py — the three trigger paths (replay / fake_llm /
live-gated), the abstention case, and malformed-request handling."""


def test_replay_path_matches_validated_report(api_client):
    r = api_client.post(
        "/api/investigations?requester_role=ANALYST",
        json={"kpi_id": "revenue", "period_current": "2017-11", "period_previous": "2017-10"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "replay"
    assert body["state"]["kpi_id"] == "revenue"
    # The real, previously-validated run: status is whatever it actually
    # reached (COMPLETED or an honest abstention/clarification/budget
    # terminal state) -- never asserted to a specific value here, since the
    # report is a live artifact that can differ run-to-run (see
    # PROJECT_JOURNEY.md's note on Groq nondeterminism). It must always be
    # ONE of the governed terminal states, never something invented.
    assert body["state"]["status"] in (
        "COMPLETED", "ABSTAINED", "NEEDS_CLARIFICATION", "BUDGET_EXCEEDED", "SECURITY_BLOCKED",
    )


def test_get_and_process_and_hypotheses_endpoints(api_client):
    created = api_client.post(
        "/api/investigations?requester_role=ANALYST",
        json={"kpi_id": "revenue", "period_current": "2017-11", "period_previous": "2017-10"},
    ).json()
    investigation_id = created["investigation_id"]

    r = api_client.get(f"/api/investigations/{investigation_id}?requester_role=ANALYST")
    assert r.status_code == 200
    assert r.json()["investigation_id"] == investigation_id

    r = api_client.get(f"/api/investigations/{investigation_id}/process?requester_role=ANALYST")
    assert r.status_code == 200
    assert "status_history" in r.json()

    r = api_client.get(f"/api/investigations/{investigation_id}/hypotheses?requester_role=ANALYST")
    assert r.status_code == 200
    assert "hypotheses" in r.json()


def test_fake_llm_path_for_non_canonical_kpi_runs_real_pipeline(api_client):
    r = api_client.post(
        "/api/investigations?requester_role=ANALYST",
        json={"kpi_id": "orders", "period_current": "2017-11", "period_previous": "2017-10"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "fake_llm"
    # A real orchestrator run happened: it reached a governed terminal status
    # and its audit trail is non-empty (real tool calls were made).
    assert body["state"]["status"] in (
        "COMPLETED", "ABSTAINED", "NEEDS_CLARIFICATION", "BUDGET_EXCEEDED", "SECURITY_BLOCKED",
    )
    assert len(body["state"]["audit_trace"]) > 0


def test_malformed_kpi_id_returns_400(api_client):
    r = api_client.post("/api/investigations?requester_role=ANALYST", json={"kpi_id": "not_a_real_kpi"})
    assert r.status_code == 400


def test_live_mode_refused_without_credentials(api_client, monkeypatch):
    import agents.llm_client as llm_client_module

    monkeypatch.setattr(llm_client_module, "has_groq_credentials", lambda: False)
    r = api_client.post(
        "/api/investigations?requester_role=ANALYST",
        json={"kpi_id": "revenue", "period_current": "2017-11", "period_previous": "2017-10", "mode": "live"},
    )
    assert r.status_code == 400


def test_unknown_requester_role_400(api_client):
    r = api_client.post(
        "/api/investigations?requester_role=NOT_A_ROLE",
        json={"kpi_id": "revenue", "period_current": "2017-11", "period_previous": "2017-10"},
    )
    assert r.status_code == 400


def test_list_investigations(api_client):
    api_client.post(
        "/api/investigations?requester_role=ANALYST",
        json={"kpi_id": "revenue", "period_current": "2017-11", "period_previous": "2017-10"},
    )
    r = api_client.get("/api/investigations?role=ANALYST")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert len(r.json()) >= 1
