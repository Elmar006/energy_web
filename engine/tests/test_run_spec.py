import hashlib
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from energy import api, run_spec as run_spec_module
from energy.api import CalculationRequest, app
from energy.run_spec import RunSpec, engine_source_manifest, input_sha256


def test_legacy_input_identity_ignores_absent_additive_demand_fields(small_input):
    snapshot = small_input.model_dump(mode="json")
    assert snapshot["demand_dataset"] is None
    assert snapshot["service_calendar"] is None
    assert snapshot["charging_requests"] == []
    for name in ("demand_dataset", "service_calendar", "charging_requests"):
        snapshot.pop(name)
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    assert input_sha256(small_input) == hashlib.sha256(canonical).hexdigest()


def test_defaults_inherit_execution_parameters_without_changing_scenario(small_input):
    small_input.parameters.simulation_days = 7
    original = small_input.model_dump()
    request = CalculationRequest(input=small_input, run_spec={})
    resolved = request.run_spec
    assert resolved is not None
    assert resolved.model_dump() == {
        "schema_version": "run-spec-v1", "model_version": "planner-mip-v3",
        "simulation_version": "simpy-multiday-v1", "mode": "exploratory",
        "simulation_seeds": [1, 2, 3], "explain_top_n": 3,
        "alternative_service_fractions": [0.0, 0.5, 1.0],
        "alternative_solver_seconds": 20, "solver_seconds": 15, "simulation_days": 7,
        "service_requirements": None,
    }
    effective = resolved.apply(small_input)
    effective.zones[0].hourly_kwh[0] = 99
    assert small_input.model_dump() == original


@pytest.mark.parametrize("override", [
    {"model_version": "future-model"},
    {"simulation_version": "future-simulation"}, {"mode": "accepted"},
    {"mode": "validation"}, {"mode": "validation", "simulation_seeds": list(range(29))},
    {"simulation_seeds": []}, {"simulation_seeds": list(range(101))},
    {"simulation_seeds": [1, 1]}, {"simulation_seeds": [-1]},
    {"simulation_seeds": [2_147_483_648]}, {"simulation_seeds": [True]},
    {"simulation_seeds": [1.0]}, {"simulation_seeds": ["1"]},
    {"simulation_seeds": None}, {"solver_seconds": 0}, {"solver_seconds": 3601},
    {"solver_seconds": 1.0}, {"solver_seconds": True}, {"solver_seconds": "10"},
    {"solver_seconds": None}, {"simulation_days": 0}, {"simulation_days": 15},
    {"simulation_days": 3.0}, {"simulation_days": True}, {"simulation_days": None},
    {"explain_top_n": -1}, {"explain_top_n": 11}, {"explain_top_n": False},
    {"explain_top_n": 0.0}, {"explain_top_n": None},
    {"alternative_solver_seconds": 0}, {"alternative_solver_seconds": 61},
    {"alternative_solver_seconds": True}, {"alternative_solver_seconds": None},
    {"alternative_service_fractions": [0.5, 0.5]},
    {"alternative_service_fractions": [1, 0]}, {"alternative_service_fractions": [-0.1]},
    {"alternative_service_fractions": [1.1]}, {"alternative_service_fractions": [True]},
    {"alternative_service_fractions": ["0.5"]},
    {"alternative_service_fractions": [0, 0.1, 0.2, 0.3, 0.4, 0.5]},
    {"alternative_service_fractions": None}, {"typo": 30},
    {"mode": "validation", "simulation_seeds": list(range(30)),
     "service_requirements": {"min_energy_fraction": 0.9,
                              "min_seeds_per_condition": 31}},
    {"development_seeds": [4]},
    {"schema_version": "run-spec-v2", "development_seeds": [1]},
    {"schema_version": "run-spec-v2", "max_improvement_iterations": 4},
    {"schema_version": "run-spec-v2", "development_seeds": [4, 4]},
    {"schema_version": "run-spec-v2", "mode": "validation",
     "simulation_seeds": list(range(30)), "development_seeds": [30, 31],
     "max_improvement_iterations": 1},
])
def test_invalid_run_spec_rejected_by_http_contract(small_input, override):
    response = TestClient(app).post("/v1/calculate", json={
        "input": small_input.model_dump(), "run_spec": override,
    })
    assert response.status_code == 422


@pytest.mark.parametrize("fraction", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_alternative_targets_rejected(fraction):
    with pytest.raises(ValidationError):
        RunSpec(alternative_service_fractions=[fraction])


def test_run_spec_accepts_inclusive_configuration_boundaries():
    configured = RunSpec(
        mode="validation", simulation_seeds=[*range(99), 2_147_483_647],
        solver_seconds=3600, simulation_days=14, explain_top_n=10,
        alternative_solver_seconds=60, alternative_service_fractions=[0, 0.25, 0.5, 0.75, 1],
    )
    assert len(configured.simulation_seeds) == 100
    assert configured.alternative_service_fractions == [0.0, 0.25, 0.5, 0.75, 1.0]


@pytest.mark.parametrize("legacy", [
    {"simulation_seeds": [1]}, {"explain_top_n": 0},
    {"alternative_service_fractions": []}, {"alternative_solver_seconds": 20},
])
def test_explicit_run_spec_cannot_be_combined_with_legacy_fields(small_input, legacy):
    response = TestClient(app).post("/v1/calculate", json={
        "input": small_input.model_dump(), "run_spec": {}, **legacy,
    })
    assert response.status_code == 422
    assert "legacy execution fields" in response.text


def test_null_run_spec_and_unknown_request_fields_are_rejected(small_input):
    client = TestClient(app)
    for fields in ({"run_spec": None}, {"simulation_seed": [1]}):
        response = client.post("/v1/calculate", json={"input": small_input.model_dump(), **fields})
        assert response.status_code == 422


def test_validation_executes_every_seed_and_propagates_overrides_to_all_stages(small_input, monkeypatch):
    calls = {name: [] for name in ("solve", "simulate", "economics", "explanations", "alternatives")}
    original = small_input.model_dump()
    original_solve = api.solve

    def capture(name, spec):
        calls[name].append((spec.parameters.solver_seconds, spec.parameters.simulation_days))
        assert spec is not small_input

    def solve(spec):
        capture("solve", spec)
        return original_solve(spec)

    def simulate(spec, selected, *, year, scenario_id, seed, **_):
        capture("simulate", spec)
        return {"seed": seed, "year": year, "scenario_id": scenario_id,
                "dispatch_verification": {"passed": True}}

    def economics(spec, result, simulations):
        capture("economics", spec)
        return []

    def explanations(spec, result, count):
        capture("explanations", spec)
        assert count == 1
        return []

    def alternatives(spec, fractions, seeds, seconds):
        capture("alternatives", spec)
        assert fractions == [0.75]
        assert seeds == list(range(30))
        assert seconds == 9
        return []

    monkeypatch.setattr(api, "solve", solve)
    monkeypatch.setattr(api, "simulate", simulate)
    monkeypatch.setattr(api, "compare_operations", lambda *_: [])
    monkeypatch.setattr(api, "compare_economics", economics)
    monkeypatch.setattr(api, "explain_selected_sites", explanations)
    monkeypatch.setattr(api, "calculate_alternatives", alternatives)
    response = TestClient(app).post("/v1/calculate", json={
        "input": original,
        "run_spec": {"mode": "validation", "simulation_seeds": list(range(30)),
                     "solver_seconds": 17, "simulation_days": 7, "explain_top_n": 1,
                     "alternative_service_fractions": [0.75], "alternative_solver_seconds": 9},
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert [run["seed"] for run in body["simulation"]] == list(range(30))
    assert {name: len(rows) for name, rows in calls.items()} == {
        "solve": 1, "simulate": 30, "economics": 1, "explanations": 1, "alternatives": 1,
    }
    assert all(row == (17, 7) for rows in calls.values() for row in rows)
    metadata = body["metadata"]
    assert metadata["configuration_source"] == "run_spec"
    assert metadata["engine_request_sha256"] == hashlib.sha256(response.request.content).hexdigest()
    assert len(metadata["engine_source_sha256"]) == 64
    assert "run_spec.py" in metadata["engine_source_files"]
    assert "optimizer.py" in metadata["engine_source_files"]
    assert "simulation.py" in metadata["engine_source_files"]
    assert metadata["run_spec"]["mode"] == "validation"
    assert metadata["run_spec"]["solver_seconds"] == 17
    assert metadata["run_spec"]["simulation_days"] == 7
    # Hash the validated input, as the existing engine contract does. Pydantic
    # normalizes numeric input (including unvalidated model defaults) on ingress.
    normalized_source = CalculationRequest.model_validate({"input": original}).input
    source_snapshot = normalized_source.model_dump(mode="json")
    for name in ("demand_dataset", "service_calendar", "charging_requests"):
        source_snapshot.pop(name)
    source_canonical = json.dumps(source_snapshot, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":")).encode("utf-8")
    assert metadata["source_input_sha256"] == hashlib.sha256(source_canonical).hexdigest()
    effective = normalized_source.model_copy(deep=True)
    effective.parameters.solver_seconds = 17
    effective.parameters.simulation_days = 7
    assert metadata["input_sha256"] == input_sha256(effective)
    assert metadata["input_sha256"] != metadata["source_input_sha256"]
    assert body["service_acceptance"] == {
        "status": "not_evaluated", "reason": "service_requirements_not_configured",
    }
    assert small_input.model_dump() == original


def test_explicit_zero_and_empty_optional_work_are_honored(small_input, monkeypatch):
    def forbidden(*_, **__):
        pytest.fail("disabled work was executed")

    monkeypatch.setattr(api, "explain_selected_sites", forbidden)
    monkeypatch.setattr(api, "calculate_alternatives", forbidden)
    response = TestClient(app).post("/v1/calculate", json={
        "input": small_input.model_dump(),
        "run_spec": {"simulation_seeds": [0], "explain_top_n": 0,
                     "alternative_service_fractions": [], "simulation_days": 1},
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanations"] == body["alternatives"] == []
    assert len(body["simulation"]) == 1
    assert body["simulation"][0]["seed"] == 0
    assert body["simulation"][0]["simulation_days"] == 1
    assert body["simulation"][0]["dispatch_verification"]["passed"] is True
    assert body["metadata"]["run_spec"]["solver_seconds"] == 15


def test_legacy_empty_seeds_and_explanation_default_preserved(small_input):
    request = CalculationRequest(input=small_input)
    assert request.explain_top_n == 0
    assert request.run_spec is None
    response = TestClient(app).post("/v1/calculate", json={
        "input": small_input.model_dump(), "simulation_seeds": [],
        "alternative_service_fractions": [],
    })
    assert response.status_code == 200
    body = response.json()
    assert body["simulation"] == []
    assert body["metadata"]["run_spec"] is None
    assert body["metadata"]["configuration_source"] == "legacy_fields"
    assert body["metadata"]["explain_top_n"] == 0
    assert body["metadata"]["input_sha256"] == body["metadata"]["source_input_sha256"]


def test_failed_optimization_still_records_effective_configuration(small_input):
    small_input.parameters.minimum_zone_service = 1
    small_input.travel_edges = []
    response = TestClient(app).post("/v1/calculate", json={
        "input": small_input.model_dump(), "run_spec": {"solver_seconds": 4},
    })
    assert response.status_code == 200
    body = response.json()
    assert body["optimization"]["status"] == "infeasible"
    assert body["metadata"]["run_spec"]["solver_seconds"] == 4
    assert body["service_acceptance"]["status"] == "not_evaluated"
    assert body["simulation"] == []


def test_source_manifest_includes_nested_python_files_and_changes_with_source(tmp_path, monkeypatch):
    (tmp_path / "run_spec.py").write_text("source", encoding="utf-8")
    (tmp_path / "nested").mkdir()
    source = tmp_path / "nested" / "dispatch.py"
    source.write_text("first", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("irrelevant", encoding="utf-8")
    monkeypatch.setattr(run_spec_module, "__file__", str(tmp_path / "run_spec.py"))
    first_digest, names = engine_source_manifest()
    assert names == ["nested/dispatch.py", "run_spec.py"]
    assert engine_source_manifest()[0] == first_digest
    source.write_text("changed", encoding="utf-8")
    assert engine_source_manifest()[0] != first_digest
