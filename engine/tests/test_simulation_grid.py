from energy.simulation import simulate


def test_grid_upgrade_enables_charging_in_simulation(small_input):
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.grid_nodes[0].upgrade_kw = 10
    small_input.zones[0].hourly_kwh = [0] * 12 + [300] + [0] * 11
    selected = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    without = simulate(small_input, selected, year=2027, scenario_id="base", seed=7)
    with_upgrade = simulate(small_input, selected, year=2027, scenario_id="base", seed=7,
                            grid_upgrades=[{"grid_node_id": "g1", "year": 2027}])
    assert without["served_sessions"] == 0
    assert with_upgrade["served_sessions"] > 0
    assert with_upgrade["energy_kwh"] > 0


def test_upgrade_year_is_respected(small_input):
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.grid_nodes[0].upgrade_kw = 10
    selected = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    result = simulate(small_input, selected, year=2027, scenario_id="base", seed=3,
                      grid_upgrades=[{"grid_node_id": "g1", "year": 2028}])
    assert result["served_sessions"] == 0


def test_commissioning_year_controls_simulated_headroom(small_input):
    small_input.parameters.years = [2027, 2028]
    small_input.parameters.annual_budgets_rub = [2000, 2000]
    small_input.scenarios[0].demand_multiplier = [1, 1]
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.grid_nodes[0].upgrade_kw = 10
    small_input.zones[0].hourly_kwh = [0] * 12 + [300] + [0] * 11
    selected = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    upgrade = [{"grid_node_id": "g1", "year": 2027, "commissioned_year": 2028}]
    before = simulate(small_input, selected, year=2027, scenario_id="base", seed=7,
                      grid_upgrades=upgrade)
    after = simulate(small_input, selected, year=2028, scenario_id="base", seed=7,
                     grid_upgrades=upgrade)
    assert before["served_sessions"] == 0
    assert after["served_sessions"] > 0
