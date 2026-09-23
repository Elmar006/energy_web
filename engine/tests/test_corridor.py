import pytest
from pydantic import ValidationError

from energy.corridor import CorridorInput, check_corridor


def route(**overrides):
    raw = {
        "route_km": 300, "battery_usable_kwh": 60,
        "initial_soc": 1, "reserve_soc": 0.1,
        "consumption_kwh_per_km": 0.2,
        "stations": [{"id": "a", "km": 100}, {"id": "b", "km": 200}],
    }
    raw.update(overrides)
    return CorridorInput.model_validate(raw)


def test_cold_weather_requires_additional_stop():
    mild = check_corridor(route())
    cold = check_corridor(route(consumption_multiplier=1.5))
    assert mild["reachable"]
    assert len(mild["stops"]) == 1
    assert cold["reachable"]
    assert cold["stops"] == ["a", "b"]
    assert all(leg["arrival_soc"] >= 0.1 for leg in cold["legs"])


def test_single_station_failure_breaks_cold_route():
    result = check_corridor(route(consumption_multiplier=1.5))
    assert result["station_failure_impacts"]["a"]["reachable"] is False
    assert result["station_failure_impacts"]["b"]["reachable"] is False


def test_unreachable_route_reports_reachable_frontier():
    result = check_corridor(route(stations=[]))
    assert result["reachable"] is False
    assert result["farthest_reachable_km"] == 0


def test_duplicate_station_positions_rejected():
    with pytest.raises(ValidationError, match="positions must be unique"):
        route(stations=[{"id": "a", "km": 100}, {"id": "b", "km": 100}])
