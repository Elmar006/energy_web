from energy.optimizer import solve
from energy.contracts import PlanningInput


def test_city_selects_feasible_station(small_input):
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.selected == [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    assert result.served_kwh == {"base": 10.0}
    assert result.unmet_kwh == {"base": 0.0}


def test_zero_budget_cannot_build(small_input):
    small_input.parameters.annual_budgets_rub = [0]
    small_input.parameters.total_budget_rub = 0
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.selected == []
    assert result.unmet_kwh["base"] == 10


def test_no_grid_capacity_requires_upgrade(small_input):
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.grid_nodes[0].upgrade_kw = 10
    small_input.grid_nodes[0].upgrade_capex_rub = 500
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.grid_upgrades == [{"grid_node_id": "g1", "year": 2027}]
    assert result.served_kwh["base"] == 10


def test_operator_may_decline_unprofitable_station(small_input):
    small_input.parameters.mode = "operator"
    small_input.parameters.sale_rub_per_kwh = 0
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.selected == []


def test_nonanticipative_investment_under_two_scenarios(small_input):
    small_input.scenarios.append(small_input.scenarios[0].model_copy(update={"id": "high", "demand_multiplier": [2]}))
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert len(result.selected) == 1
    assert result.served_kwh["base"] == 10
    assert result.unmet_kwh["high"] == 10


def test_optimizer_matches_exhaustive_search_on_two_sites(small_input):
    raw = small_input.model_dump()
    raw["zones"].append({**raw["zones"][0], "id": "z2", "name": "Zone 2"})
    raw["sites"].append({**raw["sites"][0], "id": "s2", "name": "Station 2", "grid_node_id": "g2"})
    raw["grid_nodes"].append({**raw["grid_nodes"][0], "id": "g2"})
    raw["travel_edges"].append({"zone_id": "z2", "site_id": "s2", "minutes": 5})
    for budget in (0, 1000, 2000):
        raw["parameters"]["total_budget_rub"] = budget
        raw["parameters"]["annual_budgets_rub"] = [budget]
        result = solve(PlanningInput.model_validate(raw))
        exhaustive = max(
            10 * ((mask & 1) > 0) + 10 * ((mask & 2) > 0)
            for mask in range(4) if 1000 * mask.bit_count() <= budget
        )
        assert result.status == "optimal", result.diagnostic
        assert result.served_kwh["base"] == exhaustive


def test_storage_cannot_create_energy_without_a_source(small_input):
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.sites[0].battery_max_kwh = 100
    small_input.sites[0].battery_capex_per_kwh_rub = 0
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.served_kwh["base"] == 0


def test_pv_can_supply_charging_with_zero_grid_headroom(small_input):
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.sites[0].pv_max_kw = 10
    small_input.sites[0].pv_capex_per_kw_rub = 50
    small_input.parameters.pv_hourly_factor[12] = 1
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.served_kwh["base"] == 10
    assert result.solar[0]["kw"] == 10


def test_city_uses_road_accessibility_then_cost_for_equal_coverage(small_input):
    raw = small_input.model_dump()
    raw["sites"].append({**raw["sites"][0], "id": "near", "name": "Near"})
    raw["travel_edges"].append({"zone_id": "z1", "site_id": "near", "minutes": 2})
    near_plan = solve(PlanningInput.model_validate(raw))
    assert near_plan.status == "optimal", near_plan.diagnostic
    assert [x["site_id"] for x in near_plan.selected] == ["near"]

    raw["travel_edges"][1]["minutes"] = 5
    raw["sites"][1]["option_ids"] = ["cheap"]
    raw["options"].append({**raw["options"][0], "id": "cheap", "capex_rub": 100})
    cheap_plan = solve(PlanningInput.model_validate(raw))
    assert cheap_plan.status == "optimal", cheap_plan.diagnostic
    assert [x["site_id"] for x in cheap_plan.selected] == ["near"]
