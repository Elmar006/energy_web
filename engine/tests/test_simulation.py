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
