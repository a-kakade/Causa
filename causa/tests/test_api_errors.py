"""test_api_errors.py — malformed requests map to a documented 4xx JSON
envelope, never a raw 500/traceback leak."""


def test_unknown_investigation_id_404(api_client):
    r = api_client.get("/api/investigations/does_not_exist?requester_role=ANALYST")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_unknown_evidence_id_404(api_client):
    r = api_client.get("/api/evidence/ev_does_not_exist?requester_role=ANALYST")
    assert r.status_code == 404


def test_unknown_requester_role_query_400(api_client):
    r = api_client.get("/api/overview?requester_role=NOT_A_ROLE")
    assert r.status_code == 400


def test_malformed_feedback_submission_400(api_client):
    r = api_client.post("/api/feedback", json={"rating": "NOT_A_RATING", "output_type": "STORY_CLAIM", "session_id": "s1"})
    assert r.status_code == 400


def test_error_envelope_never_leaks_raw_traceback(api_client):
    r = api_client.get("/api/investigations/does_not_exist?requester_role=ANALYST")
    body = r.json()
    text = str(body)
    assert "Traceback" not in text
    assert ".py\", line" not in text
