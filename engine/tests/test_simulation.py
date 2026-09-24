from datetime import date

import pytest

from energy import simulation as simulation_module
from energy.contracts import SessionArrivalProfile, Provenance
from energy.ingest_sessions import derive_demand
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
    small_input.parameters.simulation_days = 1
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


def test_observed_start_hour_and_energy_size_drive_simulation(small_input):
    rows = ["session_id,zone_id,started_at,ended_at,energy_kwh"]
    rows.extend(f"{i},z1,2027-04-01T06:59:00+00:00,2027-04-01T07:59:00+00:00,25"
                for i in range(20))
    observed = derive_demand(small_input, ("\n".join(rows) + "\n").encode(),
                             source="metered operator export", kind="observed",
                             time_zone="Europe/Moscow", start_date=date(2027, 4, 1),
                             end_date=date(2027, 4, 1))
    zone = observed.zones[0]
    assert zone.hourly_kwh[10] > zone.hourly_kwh[9] * 50
    assert zone.mean_session_kwh == 25
    result = simulate(observed, [], year=2027, scenario_id="base", seed=7)
    assert result["arrivals"] > 0
    assert result["arrivals_by_hour"][9] == result["arrivals"]
    assert result["arrivals_by_hour"][10] == 0
    assert result["requested_energy_kwh"] == pytest.approx(25 * result["arrivals"])
    assert result["unserved_energy_kwh"] == result["requested_energy_kwh"]


def test_overdispersed_history_uses_fitted_negative_binomial_only_with_enough_data(small_input, monkeypatch):
    small_input.parameters.simulation_days = 1
    class DeterministicRNG:
        def __init__(self):
            self.negative_binomial_args = []

        def negative_binomial(self, shape, probability):
            self.negative_binomial_args.append((shape, probability))
            return 2

        def poisson(self, expected):
            return 0

        def uniform(self, low, high):
            return 30

        def random(self):
            return 0.5

    rng = DeterministicRNG()
    monkeypatch.setattr(simulation_module.np.random, "default_rng", lambda seed: rng)
    zone = small_input.zones[0]
    zone.hourly_kwh = [0] * 12 + [100] + [0] * 11
    zone.arrival_profile = SessionArrivalProfile(
        hourly_sessions=[0] * 12 + [10] + [0] * 11,
        hourly_count_variance=[0] * 12 + [30] + [0] * 11,
        energy_quantiles_kwh=[10] * 101,
        sample_count=100, observation_days=10, source_kind="observed",
        hourly_load_method="uniform_session_duration",
        provenance=Provenance(source="test", kind="derived"),
    )
    result = simulate(small_input, [], year=2027, scenario_id="base", seed=1)
    assert rng.negative_binomial_args == [pytest.approx((5, 1 / 3))]
    assert result["arrivals"] == 2
    assert result["requested_energy_kwh"] == 20

    zone.arrival_profile.observation_days = 1
    zone.arrival_profile.sample_count = 10
    rng.negative_binomial_args.clear()
    assert simulate(small_input, [], year=2027, scenario_id="base", seed=1)["arrivals"] == 0
    assert rng.negative_binomial_args == []


def test_sessions_continue_across_midnight_and_only_final_horizon_truncates(small_input, monkeypatch):
    class FixedRNG:
        def poisson(self, expected):
            return 1 if expected else 0

        def uniform(self, low, high):
            return 30

        def gamma(self, shape, scale):
            return 10

    monkeypatch.setattr(simulation_module.np.random, "default_rng", lambda seed: FixedRNG())
    small_input.parameters.simulation_days = 2
    small_input.travel_edges[0].minutes = 0
    small_input.zones[0].hourly_kwh = [0] * 23 + [10]
    chosen = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    run = simulate(small_input, chosen, year=2027, scenario_id="base")
    assert run["arrivals"] == 2
    assert run["served_sessions"] == 1
    assert run["refused_sessions"] == 1
    assert run["last_completion_minute"] == pytest.approx(1471)
    assert run["day_dispatch"][0]["charging_sessions_at_boundary"] == 1
    assert run["day_dispatch"][1]["charging_sessions_at_boundary"] == 1
    assert run["arrivals_by_day_hour"][0][23] == 1
    assert run["arrivals_by_day_hour"][1][23] == 1
    assert run["dispatch_verification"]["passed"] is True


def test_pv_charge_from_previous_day_supplies_next_day_without_free_soc(small_input, monkeypatch):
    class FixedRNG:
        def poisson(self, expected):
            return 1 if expected else 0

        def uniform(self, low, high):
            return 30

        def gamma(self, shape, scale):
            return 5

    monkeypatch.setattr(simulation_module.np.random, "default_rng", lambda seed: FixedRNG())
    small_input.parameters.simulation_days = 2
    small_input.travel_edges[0].minutes = 0
    small_input.grid_nodes[0].headroom_kw = [0] * 24
    small_input.parameters.pv_hourly_factor[23] = 1
    small_input.zones[0].hourly_kwh = [5] + [0] * 23
    small_input.zones[0].mean_session_kwh = 5
    chosen = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    run = simulate(small_input, chosen, year=2027, scenario_id="base",
                   battery=[{"site_id": "s1", "year": 2027, "kwh": 20}],
                   solar=[{"site_id": "s1", "year": 2027, "kw": 10}])
    first = run["day_dispatch"][0]["dispatch_by_site"][0]
    second = run["day_dispatch"][1]["dispatch_by_site"][0]
    assert first["battery_soc_start_kwh"] == 0
    assert first["load_kwh"] == 0
    assert first["battery_soc_end_kwh"] == second["battery_soc_start_kwh"]
    assert second["battery_soc_start_kwh"] > 0
    assert second["load_kwh"] == pytest.approx(5, abs=0.01)
    assert run["served_sessions"] == 1
    assert run["dispatch_verification"]["storage_energy_balance_error_kwh"] <= 1e-6
