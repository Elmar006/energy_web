from datetime import date
from types import SimpleNamespace

from energy.ingest_sessions import derive_demand
from energy.validation import compare_economics, compare_operations, describe_input_quality


def test_quality_report_never_equates_metered_charging_to_total_demand(small_input):
    assert describe_input_quality(small_input)["demand_scope"] == "scenario_assumptions"
    data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
            "one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n").encode()
    observed = derive_demand(small_input, data, source="operator export", kind="observed",
                             time_zone="Europe/Moscow", start_date=date(2027, 4, 1),
                             end_date=date(2027, 4, 1))
    report = describe_input_quality(observed)
    assert report["demand_scope"] == "served_sessions_only"
    assert report["observed_session_zone_ids"] == ["z1"]
    assert any("latent unmet demand" in warning for warning in report["warnings"])
    assert any("fewer than 7 days" in warning for warning in report["warnings"])
    assert report["unverified_coverage_zone_ids"] == ["z1"]
    assert report["claimed_complete_coverage_zone_ids"] == []


def test_operational_comparison_exposes_optimistic_hourly_coverage():
    optimization = SimpleNamespace(service_by_year=[
        {"scenario_id": "base", "year": 2027, "demand_kwh": 10, "served_kwh": 10}])
    simulations = [
        {"scenario_id": "base", "year": 2027, "requested_energy_kwh": 10,
         "energy_kwh": 5, "unserved_energy_kwh": 5},
        {"scenario_id": "base", "year": 2027, "requested_energy_kwh": 20,
         "energy_kwh": 10, "unserved_energy_kwh": 10},
    ]
    row = compare_operations(optimization, simulations)[0]
    assert row["optimized_service_fraction"] == 1
    assert row["simulated_service_fraction_mean"] == 0.5
    assert row["service_gap_percentage_points"] == 50
    assert row["requested_energy_kwh_mean"] == 15
    assert row["unserved_energy_kwh_mean"] == 7.5
    assert compare_operations(optimization, []) == []


def test_simulated_npv_reprices_actual_grid_and_storage_flows(small_input):
    small_input.options[0].annual_fixed_rub = 100
    small_input.parameters.storage_degradation_rub_per_kwh = 2
    optimization = SimpleNamespace(
        selected=[{"site_id": "s1", "option_id": "dc", "year": 2027}],
        investment_rub_by_year=[{"year": 2027, "rub": 1000}],
        cashflow_rub={"base": 60_000},
    )
    runs = [{"scenario_id": "base", "year": 2027, "seed": 1, "energy_kwh": 10,
             "dispatch_by_site": [{"grid_kwh": 12, "battery_discharge_kwh": 2}]}]
    row = compare_economics(small_input, optimization, runs)[0]
    assert row["simulated_npv_rub_mean"] == 48_540
    assert row["optimism_gap_rub"] == 11_460
    assert row["profitability_sign_changed"] is False
    assert compare_economics(small_input, optimization, []) == []
    small_input.parameters.sale_rub_per_kwh = 0
    optimization.cashflow_rub["base"] = 100
    assert compare_economics(small_input, optimization, runs)[0]["profitability_sign_changed"] is True


def test_multiday_energy_and_economics_are_normalized_to_a_day(small_input):
    optimization = SimpleNamespace(
        service_by_year=[{"scenario_id": "base", "year": 2027, "demand_kwh": 10, "served_kwh": 10}],
        selected=[{"site_id": "s1", "option_id": "dc", "year": 2027}],
        investment_rub_by_year=[{"year": 2027, "rub": 1000}],
        cashflow_rub={"base": 0},
    )
    one = {"scenario_id": "base", "year": 2027, "seed": 1,
           "simulation_days": 1, "requested_energy_kwh": 10, "energy_kwh": 8,
           "unserved_energy_kwh": 2,
           "dispatch_by_site": [{"grid_kwh": 9, "battery_discharge_kwh": 0}]}
    two = {**one, "simulation_days": 2, "requested_energy_kwh": 20,
           "energy_kwh": 16, "unserved_energy_kwh": 4,
           "dispatch_by_site": [{"grid_kwh": 18, "battery_discharge_kwh": 0}]}
    single = compare_operations(optimization, [one])[0]
    multi = compare_operations(optimization, [two])[0]
    assert single.pop("simulation_days") == 1
    assert multi.pop("simulation_days") == 2
    assert single == multi
    assert compare_economics(small_input, optimization, [one]) == compare_economics(small_input, optimization, [two])
