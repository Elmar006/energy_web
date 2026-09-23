from fastapi.testclient import TestClient

from energy.api import app


def test_calculate_contract(small_input):
    response = TestClient(app).post("/v1/calculate", json={"input": small_input.model_dump(), "simulation_seeds": [3], "explain_top_n": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["optimization"]["status"] == "optimal"
    assert len(body["simulation"]) == 1
    assert body["simulation"][0]["arrivals"] == body["simulation"][0]["served_sessions"] + body["simulation"][0]["refused_sessions"]
    assert body["explanations"][0]["site_id"] == "s1"
    assert body["explanations"][0]["lost_served_kwh"]["base"] == 10
    assert len(body["metadata"]["input_sha256"]) == 64
    assert body["metadata"]["model_version"] == "planner-mip-v1"
