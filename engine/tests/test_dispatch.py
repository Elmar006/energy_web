"""Physical counterexamples for causal one-minute station dispatch."""
import random

import pytest

from energy.dispatch import SiteSupply, dispatch_minute
from energy.simulation import simulate


def test_pv_charges_storage_then_storage_serves_zero_grid_demand():
    station = SiteSupply("grid", ports=1, charger_kw=10, connection_kw=10,
                         battery_kwh=10, pv_kw=10)
    sites = {"station": station}
    charged = 0
    for _ in range(60):
        flow = dispatch_minute(sites, {}, {"grid": 0}, pv_factor=1,
                               efficiency=1, storage_max_hours=1)["station"]
        charged += flow.charge_kw / 60
        assert flow.grid_kw == flow.load_kw == flow.discharge_kw == 0
    assert charged == pytest.approx(10)
    assert station.soc_kwh == pytest.approx(10)
    delivered = 0
    for _ in range(60):
        flow = dispatch_minute(sites, {"station": 10}, {"grid": 0}, pv_factor=0,
                               efficiency=1, storage_max_hours=1)["station"]
        delivered += flow.load_kw / 60
        assert flow.grid_kw == flow.pv_kw == flow.charge_kw == 0
    assert delivered == pytest.approx(10)
    assert station.soc_kwh == pytest.approx(0)
    assert dispatch_minute(sites, {"station": 10}, {"grid": 0}, pv_factor=0,
                           efficiency=1, storage_max_hours=1)["station"].load_kw == 0


def test_round_trip_loss_and_connection_apply_to_battery_charging():
    station = SiteSupply("grid", ports=1, charger_kw=20, connection_kw=5,
                         battery_kwh=9, pv_kw=0)
    sites = {"station": station}
    for _ in range(60):
        flow = dispatch_minute(sites, {}, {"grid": 100}, pv_factor=0,
                               efficiency=0.9, storage_max_hours=1)["station"]
        assert flow.grid_kw == pytest.approx(5)
        assert flow.charge_kw == pytest.approx(5)
    assert station.soc_kwh == pytest.approx(4.5)
    delivered = 0
    for _ in range(60):
        flow = dispatch_minute(sites, {"station": 20}, {"grid": 0}, pv_factor=0,
                               efficiency=0.9, storage_max_hours=1)["station"]
        delivered += flow.load_kw / 60
        assert flow.charge_kw == 0
    assert delivered == pytest.approx(4.05)
    assert station.soc_kwh == pytest.approx(0)


def test_two_stations_share_node_headroom_without_double_spending():
    sites = {sid: SiteSupply("shared", ports=1, charger_kw=20, connection_kw=20)
             for sid in ("a", "b")}
    flow = dispatch_minute(sites, {"a": 20, "b": 20}, {"shared": 12},
                           pv_factor=0, efficiency=0.9, storage_max_hours=2)
    assert flow["a"].grid_kw == flow["b"].grid_kw == pytest.approx(6)
    assert sum(item.grid_kw for item in flow.values()) == pytest.approx(12)
    sites["a"].connection_kw = 3
    flow = dispatch_minute(sites, {"a": 20, "b": 20}, {"shared": 12},
                           pv_factor=0, efficiency=0.9, storage_max_hours=2)
    assert flow["a"].grid_kw == pytest.approx(3)
    assert flow["b"].grid_kw == pytest.approx(9)


def test_randomized_dispatch_preserves_power_and_state_bounds():
    rng = random.Random(84)
    sites = {f"s{i}": SiteSupply(f"n{i % 2}", ports=2, charger_kw=30,
                                  connection_kw=15 + i, battery_kwh=8 + i,
                                  pv_kw=4 + i) for i in range(5)}
    for _ in range(500):
        limits = {"n0": rng.uniform(0, 70), "n1": rng.uniform(0, 50)}
        demand = {sid: rng.uniform(0, 80) for sid in sites}
        flow = dispatch_minute(sites, demand, limits, pv_factor=rng.random(),
                               efficiency=0.87, storage_max_hours=2)
        for node, limit in limits.items():
            assert sum(item.grid_kw for sid, item in flow.items()
                       if sites[sid].node_id == node) <= limit + 1e-8
        for sid, item in flow.items():
            site = sites[sid]
            assert item.grid_kw <= site.connection_kw + 1e-8
            assert item.load_kw <= min(demand[sid], site.ports * site.charger_kw) + 1e-8
            assert item.grid_kw + item.pv_kw + item.discharge_kw == pytest.approx(
                item.load_kw + item.charge_kw, abs=1e-8)
            assert 0 <= item.soc_kwh <= site.battery_kwh + 1e-8
            assert min(item.charge_kw, item.discharge_kw) < 1e-9


def test_simulation_uses_pv_and_causal_battery_without_grid(small_input):
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.parameters.pv_hourly_factor = [1] * 12 + [0] * 12
    small_input.parameters.storage_efficiency = 1
    small_input.parameters.storage_max_hours = 1
    small_input.zones[0].hourly_kwh = [0] * 12 + [10] + [0] * 11
    small_input.zones[0].mean_session_kwh = 1
    selection = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    no_assets = simulate(small_input, selection, year=2027, scenario_id="base", seed=7)
    with_assets = simulate(small_input, selection, year=2027, scenario_id="base", seed=7,
                           battery=[{"site_id": "s1", "year": 2027, "kwh": 10}],
                           solar=[{"site_id": "s1", "year": 2027, "kw": 10}])
    assert no_assets["served_sessions"] == 0
    assert with_assets["served_sessions"] > 0
    assert with_assets["dispatch_verification"]["passed"] is True
    row = with_assets["dispatch_by_site"][0]
    assert row["grid_kwh"] == 0
    assert row["pv_used_kwh"] > 0
    assert row["battery_discharge_kwh"] > 0
    assert row["battery_soc_start_kwh"] == 0
    assert row["battery_soc_end_kwh"] >= 0
    assert with_assets["energy_kwh"] == pytest.approx(row["load_kwh"], abs=0.001)


def test_storage_cannot_arrive_before_investment_year(small_input):
    small_input.parameters.years = [2027, 2028]
    small_input.parameters.annual_budgets_rub = [2000, 2000]
    small_input.scenarios[0].demand_multiplier = [1, 1]
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.parameters.pv_hourly_factor = [1] * 12 + [0] * 12
    small_input.zones[0].hourly_kwh = [0] * 12 + [10] + [0] * 11
    small_input.zones[0].mean_session_kwh = 1
    selection = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    assets = [{"site_id": "s1", "year": 2028, "kwh": 10}]
    solar = [{"site_id": "s1", "year": 2028, "kw": 10}]
    before = simulate(small_input, selection, year=2027, scenario_id="base", seed=7,
                      battery=assets, solar=solar)
    after = simulate(small_input, selection, year=2028, scenario_id="base", seed=7,
                     battery=assets, solar=solar)
    assert before["served_sessions"] == 0
    assert after["served_sessions"] > 0


def test_simulation_does_not_buy_idle_storage_energy_without_forecast_shortfall(small_input):
    selection = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    run = simulate(small_input, selection, year=2027, scenario_id="base", seed=7,
                   battery=[{"site_id": "s1", "year": 2027, "kwh": 10}])
    row = run["dispatch_by_site"][0]
    assert row["battery_charge_kwh"] == 0
    assert row["battery_soc_end_kwh"] == 0
    assert run["dispatch_verification"]["passed"]


def test_simulation_precharges_from_grid_only_for_future_bottleneck(small_input):
    small_input.grid_nodes[0].headroom_kw = [10] * 12 + [0] + [10] * 11
    small_input.parameters.storage_efficiency = 1
    small_input.parameters.storage_max_hours = 1
    small_input.zones[0].mean_session_kwh = 1
    selection = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    run = simulate(small_input, selection, year=2027, scenario_id="base", seed=7,
                   battery=[{"site_id": "s1", "year": 2027, "kwh": 10}])
    row = run["dispatch_by_site"][0]
    assert row["battery_charge_kwh"] > 0
    assert row["battery_discharge_kwh"] > 0
    assert run["energy_kwh"] > 0
    assert run["dispatch_verification"]["passed"]
