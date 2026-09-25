"""Service gating tests use independent, explicit simulation evidence."""
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from energy import api
from energy.acceptance import ServiceRequirements, assess_service


def _rows(*, served: int = 95, arrivals: int = 100, energy: float = 95,
          requested: float = 100, wait: float = 5, seeds=range(30)):
    return [{"scenario_id": "base", "year": 2027, "seed": seed,
             "arrivals": arrivals, "served_sessions": served,
             "refused_sessions": arrivals - served,
             "requested_energy_kwh": requested, "energy_kwh": energy,
             "p95_wait_minutes": wait, "dispatch_verification": {"passed": True}}
            for seed in seeds]


def _optimization(status="optimal", passed=True):
    return {"status": status, "verification": {"passed": passed}}


def test_accepted_and_rejected_have_distinct_physical_and_service_reasons(small_input):
    requirement = ServiceRequirements(min_energy_fraction=0.9,
                                      max_mean_seed_p95_wait_minutes=10)
    good = assess_service(small_input, _optimization(), _rows(), requirement,
                          validation_mode=True, expected_seeds=list(range(30)))
    assert good["status"] == "accepted"
    assert good["conditions"][0]["metrics"]["energy_fraction"]["lower_95"] == pytest.approx(0.95)
    assert good["interval_scope"] == "simulation_randomness_only"
    bad = assess_service(small_input, _optimization(), _rows(energy=75), requirement,
                         validation_mode=True, expected_seeds=list(range(30)))
    assert bad["status"] == "rejected"
    assert bad["reason"] == "service_threshold_failed"
    physical = assess_service(small_input, _optimization(passed=False), _rows(), requirement,
                              validation_mode=True, expected_seeds=list(range(30)))
    assert physical["status"] == "rejected"
    assert physical["reason"] == "physical_verification_failed"


def test_missing_or_inadequate_evidence_cannot_be_accepted(small_input):
    requirement = ServiceRequirements(min_energy_fraction=0.9, min_seeds_per_condition=30)
    def assess(rows, seeds=list(range(30)), validation=True):
        return assess_service(small_input, _optimization(), rows, requirement,
                              validation_mode=validation, expected_seeds=seeds)
    assert assess(_rows(seeds=range(29)))["reason"] == "incomplete_simulation_coverage"
    assert assess(_rows(seeds=range(29)), list(range(29)))["reason"] == "insufficient_declared_seeds"
    assert assess(_rows(), validation=False)["reason"] == "validation_mode_required"
    assert assess(_rows(requested=0, energy=0))["status"] == "inconclusive"
    assert assess(_rows(requested=0, energy=0))["conditions"][0]["metrics"]["energy_fraction"]["reason"] == "metric_unavailable"
    assert assess(_rows() + _rows(seeds=[0]))["reason"] == "invalid_simulation_coverage"
    malformed = _rows()
    malformed[0]["dispatch_verification"]["passed"] = False
    assert assess(malformed)["reason"] == "invalid_simulation_coverage"


def test_uncertain_interval_does_not_pass_or_fail_without_evidence(small_input):
    rows = _rows(energy=89.9)
    for row in rows[15:]:
        row["energy_kwh"] = 90.1
    requirement = ServiceRequirements(min_energy_fraction=0.9)
    result = assess_service(small_input, _optimization(), rows, requirement,
                            validation_mode=True, expected_seeds=list(range(30)))
    assert result["status"] == "inconclusive"
    metric = result["conditions"][0]["metrics"]["energy_fraction"]
    assert metric["lower_95"] < 0.9 < metric["upper_95"]


@pytest.mark.parametrize("values", [
    {}, {"min_energy_fraction": True}, {"min_energy_fraction": 1.01},
    {"min_energy_fraction": float("nan")},
    {"min_energy_fraction": 0.8, "min_seeds_per_condition": 1},
    {"min_session_fraction": 0.9, "unknown_field": 1},
])
def test_requirements_reject_ambiguous_or_invalid_thresholds(values):
    with pytest.raises(ValidationError):
        ServiceRequirements.model_validate(values)


def test_http_calculation_exposes_acceptance_with_saved_run_spec(small_input, monkeypatch):
    original_simulate = api.simulate

    def stable_simulation(*args, year, scenario_id, seed, **kwargs):
        row = _rows(seeds=[seed])[0]
        row["year"] = year
        row["scenario_id"] = scenario_id
        row["simulation_days"] = 1
        return row

    monkeypatch.setattr(api, "simulate", stable_simulation)
    monkeypatch.setattr(api, "compare_operations", lambda *_: [])
    monkeypatch.setattr(api, "compare_economics", lambda *_: [])
    response = TestClient(api.app).post("/v1/calculate", json={
        "input": small_input.model_dump(),
        "run_spec": {"mode": "validation", "simulation_days": 1,
                     "simulation_seeds": list(range(30)),
                     "explain_top_n": 0, "alternative_service_fractions": [],
                     "service_requirements": {"min_energy_fraction": 0.9}},
    })
    monkeypatch.setattr(api, "simulate", original_simulate)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["service_acceptance"]["status"] == "accepted"
    assert result["metadata"]["run_spec"]["service_requirements"] == {"min_energy_fraction": 0.9}
