"""test_api_health.py — liveness."""


def test_health_ok(api_client):
    r = api_client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["engine_bundle_ready"] is True
