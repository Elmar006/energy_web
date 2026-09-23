from energy.optimizer import solve
from energy.simulation import simulate


def test_simulation_is_reproducible_and_conserves_arrivals(small_input):
    chosen = solve(small_input).selected
    first = simulate(small_input, chosen, year=2027, scenario_id="base", seed=5)
    second = simulate(small_input, chosen, year=2027, scenario_id="base", seed=5)
    assert first == second
    assert first["arrivals"] == first["served_sessions"] + first["refused_sessions"]


def test_no_station_refuses_all_arrivals(small_input):
    small_input.zones[0].hourly_kwh[12] = 200
    result = simulate(small_input, [], year=2027, scenario_id="base", seed=9)
    assert result["arrivals"] > 0
    assert result["refused_sessions"] == result["arrivals"]


def test_late_sessions_cannot_charge_beyond_modelled_day(small_input):
    small_input.zones[0].hourly_kwh = [0] * 23 + [1000]
    small_input.zones[0].mean_session_kwh = 100
    selected = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    result = simulate(small_input, selected, year=2027, scenario_id="base", seed=4)
    assert result["arrivals"] > 0
    assert result["served_sessions"] == 0
    assert result["refused_sessions"] == result["arrivals"]
    assert result["last_completion_minute"] is None
    assert 0 <= result["energy_kwh"] <= 10
    assert result["partial_energy_kwh"] == result["energy_kwh"]
    assert abs(sum(result["energy_by_site_kwh"].values()) - result["energy_kwh"]) < 0.002
