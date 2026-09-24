from fastapi.testclient import TestClient

from energy.api import app


def test_calculate_contract(small_input):
    response = TestClient(app).post("/v1/calculate", json={"input": small_input.model_dump(), "simulation_seeds": [3], "explain_top_n": 1})
    assert response.status_code == 200
    body = response.json()
    assert body["optimization"]["status"] == "optimal"
    assert body["optimization"]["verification"]["passed"] is True
    assert body["optimization"]["energy_audit"][0]["served_kwh"] == 10
    assert body["optimization"]["service_by_year"] == [
        {"scenario_id": "base", "year": 2027, "demand_kwh": 10, "served_kwh": 10, "unmet_kwh": 0}]
    assert len(body["simulation"]) == 1
    assert body["simulation"][0]["arrivals"] == body["simulation"][0]["served_sessions"] + body["simulation"][0]["refused_sessions"]
    assert body["explanations"][0]["site_id"] == "s1"
    assert body["explanations"][0]["lost_served_kwh"]["base"] == 10
    assert len(body["metadata"]["input_sha256"]) == 64
    assert body["metadata"]["model_version"] == "planner-mip-v2"
    assert [item["target_service_fraction"] for item in body["alternatives"]] == [0, 0.5, 1]
    assert body["alternatives"][0]["optimization"]["objective"] == 0
    assert body["alternatives"][2]["optimization"]["verification"]["passed"] is True
    assert body["alternatives"][2]["achieved_min_service_fraction"] == 1
    assert body["alternatives"][2]["same_investment_as_target"] == 0.5
    assert len(body["alternatives"][2]["simulation"]) == 1


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
    assert body["alternatives"][2]["optimization"]["status"] == "infeasible"
    assert body["alternatives"][2]["achieved_min_service_fraction"] is None
    assert body["alternatives"][2]["simulation"] == []


def test_alternative_targets_are_validated_and_can_be_disabled(small_input):
    client = TestClient(app)
    for targets in ([1, 0.5], [0.5, 0.5], [-0.1], [1.1]):
        invalid = client.post("/v1/calculate", json={"input": small_input.model_dump(),
                                                      "alternative_service_fractions": targets})
        assert invalid.status_code == 422
    result = client.post("/v1/calculate", json={"input": small_input.model_dump(),
                                                 "alternative_service_fractions": [],
                                                 "simulation_seeds": []})
    assert result.status_code == 200
    assert result.json()["alternatives"] == []


def test_operator_response_keeps_no_build_recommendation_and_service_alternative(small_input):
    small_input.parameters.mode = "operator"
    small_input.parameters.sale_rub_per_kwh = 0
    response = TestClient(app).post("/v1/calculate", json={"input": small_input.model_dump(),
                                                          "simulation_seeds": [7],
                                                          "alternative_service_fractions": [1]})
    assert response.status_code == 200
    body = response.json()
    assert body["optimization"]["selected"] == []
    alternative = body["alternatives"][0]
    assert alternative["optimization"]["selected"][0]["site_id"] == "s1"
    assert alternative["optimization"]["objective"] == 1000
    assert alternative["optimization"]["cashflow_rub"]["base"] < 0
    assert alternative["simulation"][0]["seed"] == 7
