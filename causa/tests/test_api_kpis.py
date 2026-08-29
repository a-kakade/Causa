"""test_api_kpis.py — KPI endpoints cross-checked against the real,
independently-documented November 2017 numbers (same REQUIRED_* targets
scripts/step5_investigate_november_2017.py itself asserts against)."""

REQUIRED_REVENUE_PCT = 52.1
REQUIRED_REVENUE_ABSOLUTE = 346051.94


def test_list_kpi_movements_matches_known_revenue_numbers(api_client):
    r = api_client.get("/api/kpis?period=2017-11&previous_period=2017-10")
    assert r.status_code == 200
    body = r.json()
    revenue = next(m for m in body["movements"] if m["kpi_id"] == "revenue")
    assert abs(revenue["percentage_change"] - REQUIRED_REVENUE_PCT) < 0.1
    assert abs(revenue["absolute_change"] - REQUIRED_REVENUE_ABSOLUTE) < 1.0


def test_get_single_kpi_movement(api_client):
    r = api_client.get("/api/kpis/revenue?period=2017-11&previous_period=2017-10")
    assert r.status_code == 200
    assert r.json()["kpi_id"] == "revenue"


def test_unknown_kpi_id_404(api_client):
    r = api_client.get("/api/kpis/not_a_real_kpi")
    assert r.status_code == 404


def test_kpi_timeseries(api_client):
    r = api_client.get("/api/kpis/revenue/timeseries?months=2017-10,2017-11")
    assert r.status_code == 200
    points = r.json()["points"]
    assert len(points) == 2
    assert all("value" in p for p in points)
