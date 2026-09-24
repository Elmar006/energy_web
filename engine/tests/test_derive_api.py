import base64
import hashlib
from copy import deepcopy

from fastapi.testclient import TestClient

from energy.api import app


VERSION = "01234567-89ab-4cde-8fab-0123456789ab"


def request(small_input, csv_bytes, *, role="demand_sessions", **overrides):
    payload = {
        "input": small_input.model_dump(mode="json"),
        "dataset_version_id": VERSION,
        "dataset_name": "Supplier upload",
        "csv_base64": base64.b64encode(csv_bytes).decode(),
        "role": role,
        "source": "operator export 2027-04",
        "kind": "observed",
        "time_zone": "Europe/Moscow",
        "start_date": "2027-04-01",
        "end_date": "2027-04-01",
    }
    payload.update(overrides)
    return TestClient(app).post("/v1/derive", json=payload)


def test_uploaded_sessions_change_actual_calculation_and_preserve_base(small_input):
    base = deepcopy(small_input.model_dump(mode="json"))
    csv_data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
                "real-1,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,20\n").encode()
    response = request(small_input, csv_data)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sha256"] == hashlib.sha256(csv_data).hexdigest()
    assert body["spec"]["zones"][0]["hourly_kwh"][15] == 20
    assert body["spec"]["zones"][0]["arrival_profile"]["hourly_sessions"][15] == 1
    assert body["spec"]["datasets"][-1]["version_id"] == VERSION
    assert body["spec"]["datasets"][-1]["transform_version"] == body["transform_version"]
    assert body["spec"]["datasets"][-1]["kind"] == "observed"
    assert small_input.model_dump(mode="json") == base

    calculation = TestClient(app).post("/v1/calculate", json={
        "input": body["spec"], "simulation_seeds": [3],
        "alternative_service_fractions": [],
    })
    assert calculation.status_code == 200, calculation.text
    result = calculation.json()
    assert result["optimization"]["service_by_year"][0]["demand_kwh"] == 20
    assert result["optimization"]["verification"]["passed"] is True
    assert result["metadata"]["input_quality"]["demand_scope"] == "served_sessions_only"


def test_uploaded_grid_headroom_changes_feasible_service(small_input):
    csv_data = ("grid_node_id,hour,headroom_kw\n" +
                "".join(f"g1,{hour},{0 if hour == 12 else 10}\n" for hour in range(24))).encode()
    response = request(small_input, csv_data, role="grid_headroom", start_date=None,
                       end_date=None, profile_date="2026-09-01")
    assert response.status_code == 200, response.text
    spec = response.json()["spec"]
    assert spec["grid_nodes"][0]["headroom_kw"][12] == 0
    assert spec["datasets"][-1]["version_id"] == VERSION
    assert spec["datasets"][-1]["role"] == "grid"
    calculation = TestClient(app).post("/v1/calculate", json={
        "input": spec, "simulation_seeds": [], "alternative_service_fractions": [],
    })
    assert calculation.status_code == 200, calculation.text
    assert calculation.json()["optimization"]["service_by_year"][0]["served_kwh"] == 0
    assert small_input.grid_nodes[0].headroom_kw[12] == 10


def test_bad_upload_is_rejected_without_fabricating_values(small_input):
    valid = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
             "one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n").encode()
    cases = [
        (valid, {"time_zone": "Europe/Berlin", "input": {
            **small_input.model_dump(mode="json"), "time_zone": "Europe/Moscow"}}, "differs"),
        (valid, {"start_date": None}, "start_date"),
        (valid.replace(b"z1", b"missing"), {}, "unknown zone_id"),
        (valid, {"csv_base64": "%%%"}, "base64"),
    ]
    for csv_data, changes, reason in cases:
        response = request(small_input, csv_data, **changes)
        assert response.status_code == 422, response.text
        assert reason in response.text


def test_session_gap_requires_explicit_coverage_assertion(small_input):
    csv_data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
                "one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n").encode()
    rejected = request(small_input, csv_data, end_date="2027-04-02")
    assert rejected.status_code == 422
    assert "coverage_complete" in rejected.text
    accepted = request(small_input, csv_data, end_date="2027-04-02", coverage_complete=True)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["spec"]["zones"][0]["arrival_profile"]["coverage_complete"] is True
    assert accepted.json()["spec"]["zones"][0]["hourly_kwh"][15] == 5
    grid = ("grid_node_id,hour,headroom_kw\n" +
            "".join(f"g1,{hour},10\n" for hour in range(24))).encode()
    invalid_grid = request(small_input, grid, role="grid_headroom", start_date=None,
                           end_date=None, profile_date="2026-09-01", coverage_complete=True)
    assert invalid_grid.status_code == 422
