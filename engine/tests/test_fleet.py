import pytest
from pydantic import ValidationError

from energy.fleet import FleetInput, schedule_fleet


def fleet(window_end=2):
    return FleetInput.model_validate({
        "slot_minutes": 15, "horizon_slots": 4,
        "buses": [
            {"id": "bus-a", "battery_kwh": 20, "initial_kwh": 4, "minimum_kwh": 2},
            {"id": "bus-b", "battery_kwh": 20, "initial_kwh": 4, "minimum_kwh": 2},
        ],
        "sites": [{"id": "depot", "ports": 1, "charger_kw": 10, "grid_kw": 10}],
        "trips": [
            {"id": "trip-a", "bus_id": "bus-a", "start_slot": 2, "end_slot": 4, "energy_kwh": 4},
            {"id": "trip-b", "bus_id": "bus-b", "start_slot": 2, "end_slot": 4, "energy_kwh": 4},
        ],
        "windows": [
            {"bus_id": "bus-a", "site_id": "depot", "start_slot": 0, "end_slot": window_end},
            {"bus_id": "bus-b", "site_id": "depot", "start_slot": 0, "end_slot": window_end},
        ],
    })


def test_shared_port_requires_staggered_charge_slots():
    result = schedule_fleet(fleet())
    assert result["status"] == "optimal", result
    assert result["peak_kw"] <= 10
    assert set(result["trip_ids_served"]) == {"trip-a", "trip-b"}
    assert {x["slot"] for x in result["schedule"]} == {0, 1}
    assert all(value >= 2 for value in result["end_energy_kwh"].values())


def test_one_slot_is_infeasible_for_two_buses_and_one_port():
    result = schedule_fleet(fleet(window_end=1))
    assert result["status"] == "infeasible", result


def test_overlapping_trip_and_charge_window_is_rejected():
    raw = fleet().model_dump()
    raw["windows"][0]["end_slot"] = 3
    with pytest.raises(ValidationError, match="overlaps a trip"):
        FleetInput.model_validate(raw)
