"""Dated demand must not regress into average-hour or repeated-day demand."""
from copy import deepcopy

import pytest

from energy.contracts import PlanningInput
from energy.dated import DatedHorizon
from energy.optimizer import solve
from energy.simulation import simulate


def _dated(small_input, *, request_start="2027-05-03T12:30:00+03:00",
           request_end="2027-05-03T13:30:00+03:00"):
    raw = small_input.model_dump(mode="json")
    raw["time_zone"] = "Europe/Moscow"
    raw["service_calendar"] = {
        "time_zone": "Europe/Moscow", "covered_dates": ["2027-05-03"],
        "request_zone_ids": ["z1"], "legacy_profile_zone_ids": [],
        "annualization_factor": 365, "annualization_basis": "assumed_repeat",
    }
    raw["charging_requests"] = [{
        "request_id": "v:1", "vehicle_id": "v", "segment": "private",
        "zone_id": "z1", "arrival_at": request_start,
        "deadline_at": request_end, "energy_from_charger_kwh": 10,
        "battery_kwh": 40, "soc_before_kwh": 0,
        "max_vehicle_kw": 20, "charging_efficiency": 1,
        "population_weight": 1,
        "provenance": {"source": "dated test", "kind": "assumed"},
    }]
    return raw


def test_dated_solver_limits_service_to_real_window_after_travel(small_input):
    spec = PlanningInput.model_validate(_dated(small_input))
    result = solve(spec)
    assert result.status == "optimal", result.diagnostic
    assert result.service_by_year[0]["demand_kwh"] == pytest.approx(10)
    # Arrival 12:30, road 5 min, departure 13:30: at most 55 min at 10 kW.
    assert result.service_by_year[0]["served_kwh"] == pytest.approx(10 * 55 / 60, abs=0.001)
    assert result.verification["passed"] is True
    assert result.demand_basis == "dated_requests"
    assert result.annualization_factor == 365


def test_dated_simulation_replays_same_request_across_plans(small_input):
    spec = PlanningInput.model_validate(_dated(small_input))
    built = simulate(spec, [{"site_id": "s1", "option_id": "dc", "year": 2027}],
                     year=2027, scenario_id="base", seed=42)
    empty = simulate(spec, [], year=2027, scenario_id="base", seed=42)
    assert built["demand_basis"] == "dated_requests"
    assert built["simulation_days"] == 1
    assert built["arrivals_by_hour"][12] == 1
    assert built["arrival_stream_sha256"] == empty["arrival_stream_sha256"]
    assert built["requested_energy_kwh"] == empty["requested_energy_kwh"] == 10
    assert 0 < built["energy_kwh"] <= 10 * 55 / 60 + 0.001
    assert empty["energy_kwh"] == 0
    assert built["dispatch_verification"]["passed"] is True
    assert len(built["day_dispatch"]) == 1


def test_dst_day_has_actual_23_hour_execution(small_input):
    raw = _dated(small_input, request_start="2027-03-28T03:00:00+02:00",
                 request_end="2027-03-28T04:00:00+02:00")
    raw["time_zone"] = "Europe/Berlin"
    raw["service_calendar"]["time_zone"] = "Europe/Berlin"
    raw["service_calendar"]["covered_dates"] = ["2027-03-28"]
    spec = PlanningInput.model_validate(raw)
    assert len(DatedHorizon.from_calendar(spec.service_calendar).slot_starts_utc) == 23
    run = simulate(spec, [], year=2027, scenario_id="base", seed=1)
    assert run["simulation_days"] == 1
    assert len(run["day_dispatch"]) == 1
    assert run["arrivals_by_hour"][3] == 1


@pytest.mark.parametrize("change,problem", [
    (lambda raw: raw["service_calendar"].update(request_zone_ids=[]), "request_zone_ids"),
    (lambda raw: raw["service_calendar"].update(legacy_profile_zone_ids=["z1"]), "zone modes"),
    (lambda raw: raw["charging_requests"][0].update(deadline_at="2027-05-03T12:00:00+03:00"), "deadline"),
    (lambda raw: raw["charging_requests"][0].update(max_vehicle_kw=5), "vehicle power"),
    (lambda raw: raw["charging_requests"][0].update(energy_from_charger_kwh=20), "representative zone energy"),
])
def test_invalid_dated_input_is_rejected(small_input, change, problem):
    raw = _dated(small_input)
    change(raw)
    with pytest.raises(ValueError, match=problem):
        PlanningInput.model_validate(raw)
