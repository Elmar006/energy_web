from energy.optimizer import solve
from energy.contracts import PlanningInput


def test_city_selects_feasible_station(small_input):
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.selected == [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    assert result.served_kwh == {"base": 10.0}
    assert result.unmet_kwh == {"base": 0.0}
    assert result.investment_rub_by_year == [{"year": 2027, "rub": 1000.0}]
    audit = result.energy_audit[0]
    assert audit["served_kwh"] == audit["grid_kwh"] == 10
    assert audit["pv_used_kwh"] == audit["battery_discharge_kwh"] == 0
    assert result.verification["passed"] is True
    assert result.verification["max_hourly_energy_balance_error_kwh"] == 0


def test_zero_budget_cannot_build(small_input):
    small_input.parameters.annual_budgets_rub = [0]
    small_input.parameters.total_budget_rub = 0
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.selected == []
    assert result.unmet_kwh["base"] == 10
    assert result.energy_audit == []
    assert result.verification["passed"] is True


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


def test_unreachable_demand_is_reported_as_unserved_without_false_infeasibility(small_input):
    small_input.travel_edges = []
    city = solve(small_input)
    assert city.status == "optimal", city.diagnostic
    assert city.selected == []
    assert city.served_kwh == {"base": 0.0}
    assert city.unmet_kwh == {"base": 10.0}

    small_input.parameters.mode = "operator"
    operator = solve(small_input)
    assert operator.status == "optimal", operator.diagnostic
    assert operator.selected == []
    assert operator.cashflow_rub == {"base": 0.0}


def test_unreachable_zone_with_mandatory_coverage_is_explained(small_input):
    small_input.travel_edges = []
    small_input.parameters.minimum_zone_service = 0.5
    result = solve(small_input)
    assert result.status == "infeasible"
    assert "z1" in result.diagnostic


def test_reachable_zone_can_be_served_when_another_zone_is_unreachable(small_input):
    second = small_input.zones[0].model_copy(deep=True)
    second.id = "z-unreachable"
    small_input.zones.append(second)
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    assert result.served_kwh == {"base": 10.0}
    assert result.unmet_kwh == {"base": 10.0}


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


def test_two_sites_cannot_spend_shared_node_headroom_twice(small_input):
    raw = small_input.model_dump()
    raw["zones"].append({**raw["zones"][0], "id": "z2", "name": "Zone 2"})
    raw["sites"].append({**raw["sites"][0], "id": "s2", "name": "Station 2"})
    raw["travel_edges"].append({"zone_id": "z2", "site_id": "s2", "minutes": 5})
    limited = solve(PlanningInput.model_validate(raw))
    assert limited.status == "optimal", limited.diagnostic
    assert limited.served_kwh["base"] == 10
    assert limited.verification["max_grid_node_overload_kw"] == 0

    raw["grid_nodes"][0].update({"upgrade_kw": 10, "upgrade_capex_rub": 500})
    raw["parameters"].update({"annual_budgets_rub": [2500], "total_budget_rub": 2500})
    upgraded = solve(PlanningInput.model_validate(raw))
    assert upgraded.status == "optimal", upgraded.diagnostic
    assert upgraded.served_kwh["base"] == 20
    assert upgraded.grid_upgrades == [{"grid_node_id": "g1", "year": 2027}]
    assert upgraded.investment_rub_by_year == [{"year": 2027, "rub": 2500.0}]
    assert upgraded.verification["passed"] is True


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
    audit = result.energy_audit[0]
    assert audit["grid_kwh"] == 0
    assert audit["pv_used_kwh"] == audit["served_kwh"] == 10
    assert audit["pv_available_kwh"] >= audit["pv_used_kwh"]
    assert result.verification["passed"] is True


def test_battery_shift_has_real_grid_input_and_round_trip_loss(small_input):
    small_input.grid_nodes[0].headroom_kw = [0] * 11 + [20] + [0] * 12
    small_input.options[0].connection_kw = 20
    small_input.sites[0].battery_max_kwh = 20
    small_input.sites[0].battery_capex_per_kwh_rub = 0
    small_input.parameters.storage_max_hours = 1
    result = solve(small_input)
    assert result.status == "optimal", result.diagnostic
    audit = result.energy_audit[0]
    assert audit["served_kwh"] == 10
    assert audit["grid_kwh"] > audit["served_kwh"]
    assert audit["battery_charge_kwh"] > audit["battery_discharge_kwh"]
    assert audit["battery_soc_start_kwh"] == audit["battery_soc_end_kwh"]
    assert result.verification["passed"] is True


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


def test_operator_cvar_caps_downside_without_scenario_specific_construction(small_input):
    raw = small_input.model_dump()
    raw["parameters"].update({"mode": "operator", "risk": "expected", "sale_rub_per_kwh": 1,
                               "purchase_rub_per_kwh": 0})
    raw["scenarios"] = [
        {"id": "low", "demand_multiplier": [0], "probability": 0.1},
        {"id": "high", "demand_multiplier": [1], "probability": 0.9},
    ]
    expected = solve(PlanningInput.model_validate(raw))
    assert expected.status == "optimal", expected.diagnostic
    assert len(expected.selected) == 1
    assert expected.cashflow_rub["low"] == -1000

    raw["parameters"].update({"risk": "expected_cvar", "cvar_alpha": 0.9,
                               "max_cvar_loss_rub": 0})
    guarded = solve(PlanningInput.model_validate(raw))
    assert guarded.status == "optimal", guarded.diagnostic
    assert guarded.selected == []
    assert guarded.risk_metrics["cvar_loss_rub"] == 0

    raw["parameters"]["max_cvar_loss_rub"] = 1000
    permitted = solve(PlanningInput.model_validate(raw))
    assert permitted.status == "optimal", permitted.diagnostic
    assert len(permitted.selected) == 1
    assert permitted.risk_metrics["cvar_loss_rub"] == 1000

    raw["parameters"].update({"cvar_alpha": 0.5, "max_cvar_loss_rub": 200})
    partial_tail = solve(PlanningInput.model_validate(raw))
    assert partial_tail.status == "optimal", partial_tail.diagnostic
    assert len(partial_tail.selected) == 1
    assert partial_tail.risk_metrics["cvar_loss_rub"] == 200


def test_city_cvar_bounds_tail_of_unserved_energy(small_input):
    raw = small_input.model_dump()
    raw["parameters"].update({"risk": "expected_cvar", "cvar_alpha": 0.9,
                               "max_cvar_unmet_kwh": 10, "annual_budgets_rub": [1000],
                               "total_budget_rub": 1000})
    raw["scenarios"] = [
        {"id": "base", "demand_multiplier": [1], "probability": 0.9},
        {"id": "high", "demand_multiplier": [2], "probability": 0.1},
    ]
    feasible = solve(PlanningInput.model_validate(raw))
    assert feasible.status == "optimal", feasible.diagnostic
    assert feasible.selected == [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    assert feasible.unmet_kwh == {"base": 0.0, "high": 10.0}
    assert feasible.risk_metrics == {"cvar_alpha": 0.9, "cvar_unmet_kwh": 10.0}

    raw["parameters"]["max_cvar_unmet_kwh"] = 9
    infeasible = solve(PlanningInput.model_validate(raw))
    assert infeasible.status == "infeasible"
