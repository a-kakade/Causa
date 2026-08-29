"""test_api_evidence_rbac.py — the security-critical one: same evidence/graph
fetched under different roles must return properly redacted payloads,
verified against calling evidence.access_control.py directly (not a
hand-rolled expected value)."""

from evidence.access_control import filter_evidence_objects, filter_graph
from evidence.schema import EvidenceObject


def test_evidence_list_matches_access_control_output_per_role(api_client, agent_ctx):
    real_objects = [v for v in agent_ctx.evidence_store.values() if isinstance(v, EvidenceObject)]

    for role, clearance in (("EXECUTIVE", "PUBLIC_ANALYTICAL"), ("ANALYST", "INTERNAL"), ("INTERNAL", "RESTRICTED")):
        expected = filter_evidence_objects(real_objects, clearance)
        r = api_client.get(f"/api/evidence?requester_role={role}")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == len(expected)
        assert {e["evidence_id"] for e in body["evidence"]} == {e.evidence_id for e in expected}


def test_executive_sees_strictly_less_than_analyst(api_client):
    exec_count = api_client.get("/api/evidence?requester_role=EXECUTIVE").json()["count"]
    analyst_count = api_client.get("/api/evidence?requester_role=ANALYST").json()["count"]
    assert exec_count < analyst_count


def test_evidence_graph_matches_filter_graph(api_client, agent_ctx):
    expected = filter_graph(agent_ctx.graph, "PUBLIC_ANALYTICAL")
    r = api_client.get("/api/evidence/graph/full?requester_role=EXECUTIVE")
    assert r.status_code == 200
    body = r.json()
    assert body["node_count"] == expected.number_of_nodes()
    assert body["edge_count"] == expected.number_of_edges()


def test_unauthorized_segment_request_is_403(api_client):
    r = api_client.get("/api/kpis/revenue/segments?dimension=seller&requester_role=EXECUTIVE")
    assert r.status_code == 403


def test_authorized_segment_request_succeeds_for_analyst(api_client):
    r = api_client.get("/api/kpis/revenue/segments?dimension=seller&requester_role=ANALYST")
    assert r.status_code == 200
