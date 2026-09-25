from copy import deepcopy
from datetime import datetime
import hashlib

import pytest
from fastapi.testclient import TestClient

from energy.api import app
from energy.mobility import MobilityInput, compile_mobility
from energy.contracts import PlanningInput
from energy.optimizer import solve
from energy.validation import describe_input_quality


@pytest.fixture
def mobility_spec(small_input):
    small_input.zones[0].group = "taxi"
    return small_input


def _trace():
    return {
        "schema_version": "mobility-v1", "time_zone": "Europe/Moscow",
        "covered_dates": ["2027-05-03", "2027-05-04"],
        "replace_zone_ids": ["z1"], "source": "explicit test itinerary",
        "source_kind": "assumed",
        "vehicles": [{
            "id": "vehicle-1", "segment": "taxi", "initial_zone_id": "z1",
            "battery_kwh": 40, "initial_kwh": 10, "reserve_kwh": 2,
            "consumption_kwh_per_km": 0.2, "max_charge_kw": 22,
            "charging_efficiency": 0.9, "population_weight": 2,
            "population_weight_basis": "two vehicles per sampled taxi",
            "activities": [
                {"kind": "park", "start_at": "2027-05-03T08:00:00+03:00",
                 "end_at": "2027-05-03T09:00:00+03:00", "zone_id": "z1",
                 "public_allowed": True},
                {"kind": "drive", "start_at": "2027-05-03T09:00:00+03:00",
                 "end_at": "2027-05-03T10:00:00+03:00",
                 "destination_zone_id": "z1", "distance_km": 60},
                {"kind": "park", "start_at": "2027-05-03T10:00:00+03:00",
                 "end_at": "2027-05-03T12:00:00+03:00", "zone_id": "z1",
                 "private_charger_kw": 7},
                {"kind": "drive", "start_at": "2027-05-03T12:00:00+03:00",
                 "end_at": "2027-05-03T13:00:00+03:00",
                 "destination_zone_id": "z1", "distance_km": 50},
            ]}]
    }


def test_potential_demand_does_not_require_an_existing_station(mobility_spec):
    mobility_spec.travel_edges = []
    original = mobility_spec.model_dump(mode="json")
    result = compile_mobility(mobility_spec, MobilityInput.model_validate(_trace()))
    request = result["requests"][0]
    assert request["vehicle_id"] == "vehicle-1"
    assert request["energy_from_charger_kwh"] == pytest.approx(4 / 0.9)
    assert request["soc_before_kwh"] == 10
    assert result["spec"]["zones"][0]["hourly_kwh"][8] == pytest.approx(4 / 0.9)
    assert sum(result["spec"]["zones"][0]["hourly_kwh"]) == pytest.approx(4 / 0.9)
    assert result["calendar_profiles"][1]["zone_hourly_kwh"] == {}
    assert result["audit"]["vehicles"][0]["driving_kwh"] == 22
    assert result["audit"]["vehicles"][0]["private_metered_kwh"] == pytest.approx(10 / 0.9)
    assert result["audit"]["vehicles"][0]["weighted_public_requested_kwh"] == pytest.approx(8 / 0.9)
    assert result["audit"]["vehicles"][0]["balance_error_kwh"] == pytest.approx(0)
    assert result["spec"]["zones"][0]["arrival_profile"] is None
    assert result["spec"]["zones"][0]["provenance"]["kind"] == "derived"
    assert result["spec"]["datasets"][-1]["sha256"] == result["source_sha256"]
    assert hashlib.sha256(result["source_canonical_json"].encode("utf-8")).hexdigest() == result["source_sha256"]
    assert len(result["compiler_source_sha256"]) == 64
    assert result["compiler_pydantic_version"]
    assert result["spec"]["datasets"][-1]["source_kind"] == "assumed"
    quality = describe_input_quality(PlanningInput.model_validate(result["spec"]))
    assert quality["demand_scope"] == "mobility_potential"
    assert quality["mobility_derived_zone_ids"] == ["z1"]
    assert quality["mobility_sources"][0]["source_kind"] == "assumed"
    assert mobility_spec.model_dump(mode="json") == original


def test_dated_request_is_part_of_saved_spec_and_solver_uses_its_full_window(mobility_spec):
    compiled = compile_mobility(mobility_spec, MobilityInput.model_validate(_trace()))
    spec = PlanningInput.model_validate(compiled["spec"])
    assert spec.charging_requests[0].request_id == "vehicle-1:0"
    assert spec.service_calendar.covered_dates[1].isoformat() == "2027-05-04"
    assert spec.service_calendar.days[0].day_type == "weekday"
    assert spec.service_calendar.annualization_basis == "assumed_repeat"
    result = solve(spec)
    expected = compiled["requests"][0]["energy_from_charger_kwh"] * 2
    assert result.status == "optimal", result.diagnostic
    assert result.demand_basis == "dated_requests"
    assert result.calendar_covered_days == 2
    assert result.service_by_year[0]["demand_kwh"] == pytest.approx(expected)
    assert result.service_by_year[0]["served_kwh"] == pytest.approx(expected)
    assert result.verification["passed"] is True


def test_public_request_survives_when_private_access_is_missing(mobility_spec):
    source = _trace()
    source["vehicles"][0]["activities"][2]["private_charger_kw"] = 0
    source["vehicles"][0]["activities"][2]["public_allowed"] = True
    result = compile_mobility(mobility_spec, MobilityInput.model_validate(source))
    assert len(result["requests"]) == 2
    assert result["spec"]["zones"][0]["hourly_kwh"][10] == pytest.approx(10 / 0.9)


def test_earlier_parking_charges_for_later_drive_without_access(mobility_spec):
    source = _trace()
    vehicle = source["vehicles"][0]
    vehicle.update(initial_kwh=10, charging_efficiency=1, population_weight=1)
    vehicle.pop("population_weight_basis")
    vehicle["activities"] = [
        {"kind": "park", "start_at": "2027-05-03T08:00:00+03:00",
         "end_at": "2027-05-03T09:00:00+03:00", "zone_id": "z1",
         "private_charger_kw": 7},
        {"kind": "drive", "start_at": "2027-05-03T09:00:00+03:00",
         "end_at": "2027-05-03T10:00:00+03:00",
         "destination_zone_id": "z1", "distance_km": 25},
        {"kind": "park", "start_at": "2027-05-03T10:00:00+03:00",
         "end_at": "2027-05-03T11:00:00+03:00", "zone_id": "z1"},
        {"kind": "drive", "start_at": "2027-05-03T11:00:00+03:00",
         "end_at": "2027-05-03T12:00:00+03:00",
         "destination_zone_id": "z1", "distance_km": 50},
    ]
    result = compile_mobility(mobility_spec, MobilityInput.model_validate(source))
    audit = result["audit"]["vehicles"][0]
    assert result["requests"] == []
    assert audit["private_metered_kwh"] == pytest.approx(7)
    assert audit["driving_kwh"] == pytest.approx(15)
    assert audit["projected_final_kwh"] == pytest.approx(2)
    assert audit["balance_error_kwh"] == pytest.approx(0)


def test_private_then_public_share_one_parking_window_without_overlap(mobility_spec):
    source = _trace()
    vehicle = source["vehicles"][0]
    vehicle.update(initial_kwh=2, charging_efficiency=1, population_weight=1)
    vehicle.pop("population_weight_basis")
    vehicle["activities"] = [
        {"kind": "park", "start_at": "2027-05-03T08:00:00+03:00",
         "end_at": "2027-05-03T09:00:00+03:00", "zone_id": "z1",
         "private_charger_kw": 5, "public_allowed": True},
        {"kind": "drive", "start_at": "2027-05-03T09:00:00+03:00",
         "end_at": "2027-05-03T10:00:00+03:00",
         "destination_zone_id": "z1", "distance_km": 75},
    ]
    result = compile_mobility(mobility_spec, MobilityInput.model_validate(source))
    request = result["requests"][0]
    audit = result["audit"]["vehicles"][0]
    private_hours = audit["private_metered_kwh"] / 5
    public_hours = request["energy_from_charger_kwh"] / vehicle["max_charge_kw"]
    assert private_hours > 0 and public_hours > 0
    assert private_hours + public_hours <= 1 + 1e-9
    assert (datetime.fromisoformat(request["arrival_at"]) -
            datetime.fromisoformat("2027-05-03T08:00:00+03:00")).total_seconds() / 3600 == pytest.approx(private_hours)
    assert request["soc_before_kwh"] == pytest.approx(2 + audit["private_metered_kwh"])
    assert audit["private_metered_kwh"] + audit["public_requested_metered_kwh"] == pytest.approx(15)
    assert audit["projected_final_kwh"] == pytest.approx(2)


def test_source_metadata_size_is_validated_before_persistence():
    trace = _trace()
    trace["source"] = "x" * 2049
    with pytest.raises(ValueError, match="2048"):
        MobilityInput.model_validate(trace)
    trace = _trace()
    trace["license"] = "x" * 2049
    with pytest.raises(ValueError, match="2048"):
        MobilityInput.model_validate(trace)


def test_home_charging_removes_public_request_without_erasing_drive_energy(small_input):
    source = _trace()
    source["vehicles"][0]["segment"] = "private"
    source["vehicles"][0]["activities"][0]["private_charger_kw"] = 7
    source["vehicles"][0]["activities"][0]["public_allowed"] = False
    result = compile_mobility(small_input, MobilityInput.model_validate(source))
    assert result["requests"] == []
    assert sum(result["spec"]["zones"][0]["hourly_kwh"]) == 0
    audit = result["audit"]["vehicles"][0]
    assert audit["driving_kwh"] == pytest.approx(22)
    assert audit["private_metered_kwh"] == pytest.approx(14 / 0.9)
    assert audit["balance_error_kwh"] == pytest.approx(0)


def test_fleet_segment_is_preserved_for_equipment_compatibility(small_input):
    source = _trace()
    source["vehicles"][0]["segment"] = "fleet"
    small_input.zones[0].group = "fleet"
    result = compile_mobility(small_input, MobilityInput.model_validate(source))
    assert result["requests"][0]["segment"] == "fleet"
    assert result["spec"]["zones"][0]["group"] == "fleet"


@pytest.mark.parametrize("mutate,expected", [
    (lambda row: row["vehicles"][0]["activities"][0].update(public_allowed=False), "no feasible charging access"),
    (lambda row: row["vehicles"][0]["activities"][0].update(end_at="2027-05-03T08:05:00+03:00"), "parking window"),
    (lambda row: row["vehicles"][0]["activities"][1].update(start_at="2027-05-03T08:30:00+03:00"), "activity time"),
    (lambda row: row["vehicles"][0]["activities"][0].update(zone_id="other"), "parking zone"),
    (lambda row: row["vehicles"][0]["activities"][0].update(start_at="2027-05-03T08:00:00+02:00"), "correct UTC offset"),
    (lambda row: row["vehicles"][0]["activities"][0].update(end_at="2027-05-05T01:00:00+03:00"), "date coverage"),
    (lambda row: row["vehicles"][0]["activities"][1].update(distance_km=250), "battery capacity"),
    (lambda row: row["vehicles"][0]["activities"][1].update(end_at="2027-05-03T09:05:00+03:00"), "max_average_speed_kmh"),
])
def test_invalid_or_physically_impossible_itinerary_is_rejected(mobility_spec, mutate, expected):
    source = _trace()
    mutate(source)
    with pytest.raises(ValueError, match=expected):
        compile_mobility(mobility_spec, MobilityInput.model_validate(source))


def test_dst_calendar_uses_elapsed_utc_hours(mobility_spec):
    source = _trace()
    source["time_zone"] = "Europe/Berlin"
    source["covered_dates"] = ["2027-03-28"]
    source["vehicles"][0]["activities"] = [
        {"kind": "park", "start_at": "2027-03-28T03:00:00+02:00",
         "end_at": "2027-03-28T04:00:00+02:00", "zone_id": "z1", "public_allowed": True},
        {"kind": "drive", "start_at": "2027-03-28T04:00:00+02:00",
         "end_at": "2027-03-28T05:00:00+02:00",
         "destination_zone_id": "z1", "distance_km": 60},
    ]
    result = compile_mobility(mobility_spec, MobilityInput.model_validate(source))
    assert result["calendar_profiles"][0]["physical_hours"] == 23
    source["vehicles"][0]["activities"][0]["start_at"] = "2027-03-28T02:30:00+01:00"
    with pytest.raises(ValueError, match="correct UTC offset"):
        compile_mobility(mobility_spec, MobilityInput.model_validate(source))


def test_http_compile_returns_uploadable_versioned_spec(mobility_spec):
    response = TestClient(app).post("/v1/mobility/compile", json={
        "input": mobility_spec.model_dump(mode="json"), "mobility": _trace()})
    assert response.status_code == 200, response.text
    compiled = response.json()
    validated = TestClient(app).post("/v1/validate", json=compiled["spec"])
    assert validated.status_code == 200, validated.text
    assert validated.json()["valid"] is True


def test_segment_cannot_silently_change_charger_compatibility(small_input):
    with pytest.raises(ValueError, match="segment does not match"):
        compile_mobility(small_input, MobilityInput.model_validate(_trace()))


def test_population_scaling_requires_an_explicit_basis():
    trace = _trace()
    trace["vehicles"][0].pop("population_weight_basis")
    with pytest.raises(ValueError, match="population_weight_basis"):
        MobilityInput.model_validate(trace)
