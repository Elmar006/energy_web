from fastapi.testclient import TestClient

from energy.api import app


def test_calculate_contract(small_input):
    response = TestClient(app).post("/v1/calculate", json={"input": small_input.model_dump(), "simulation_seeds": [3], "explain_top_n": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["optimization"]["status"] == "optimal"
    assert body["optimization"]["verification"]["passed"] is True
    assert body["optimization"]["energy_audit"][0]["served_kwh"] == 10
    assert len(body["simulation"]) == 1
    assert body["simulation"][0]["arrivals"] == body["simulation"][0]["served_sessions"] + body["simulation"][0]["refused_sessions"]
    assert body["explanations"][0]["site_id"] == "s1"
    assert body["explanations"][0]["lost_served_kwh"]["base"] == 10
    assert len(body["metadata"]["input_sha256"]) == 64
    assert body["metadata"]["model_version"] == "planner-mip-v1"


def test_validate_contract_rejects_broken_references(small_input):
    client = TestClient(app)
    valid = client.post("/v1/validate", json=small_input.model_dump())
    assert valid.status_code == 200
    assert valid.json()["valid"] is True
    broken = small_input.model_dump()
    broken["sites"][0]["grid_node_id"] = "missing"
    invalid = client.post("/v1/validate", json=broken)
    assert invalid.status_code == 422
    assert invalid.json()["detail"]


def test_no_reachable_station_returns_valid_unserved_plan_and_simulation(small_input):
    small_input.travel_edges = []
    response = TestClient(app).post("/v1/calculate", json={"input": small_input.model_dump(),
                                                          "simulation_seeds": [3]})
    assert response.status_code == 200
    body = response.json()
    assert body["optimization"]["status"] == "optimal"
    assert body["optimization"]["selected"] == []
    assert body["optimization"]["unmet_kwh"]["base"] == 10
    assert body["simulation"][0]["served_sessions"] == 0
    assert body["simulation"][0]["refused_sessions"] == body["simulation"][0]["arrivals"]
