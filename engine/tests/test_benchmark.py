import pytest

from energy.benchmark import (accessibility, benchmark, density_heuristic,
                              existing_network, interval, investment_by_year)


def test_density_baseline_respects_shared_grid_and_budget(small_input):
    spec = small_input.model_copy(deep=True)
    second = spec.sites[0].model_copy(deep=True)
    second.id = "s2"
    spec.sites.append(second)
    spec.travel_edges.append(spec.travel_edges[0].model_copy(update={"site_id": "s2"}))
    plan = density_heuristic(spec)
    assert len(plan.selected) == 1  # Two 10 kW connections cannot share 10 kW.
    assert sum(investment_by_year(spec, plan).values()) == 1000
    assert accessibility(spec, plan, 2027, "base")["demand_weighted_reachable_fraction"] == 1


def test_existing_asset_is_free_capex_but_still_reserves_connection(small_input):
    spec = small_input.model_copy(deep=True)
    spec.sites[0].existing_option_id = "dc"
    second = spec.sites[0].model_copy(deep=True)
    second.id = "s2"
    second.existing_option_id = None
    spec.sites.append(second)
    spec.travel_edges.append(spec.travel_edges[0].model_copy(update={"site_id": "s2"}))
    assert existing_network(spec).selected == [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    plan = density_heuristic(spec)
    assert plan.selected == existing_network(spec).selected
    assert investment_by_year(spec, plan)[2027] == 0


def test_density_never_builds_in_excluded_or_unavailable_period(small_input):
    spec = small_input.model_copy(deep=True)
    spec.excluded_site_ids = ["s1"]
    assert density_heuristic(spec).selected == []
    spec.excluded_site_ids = []
    spec.sites[0].earliest_period = 1
    assert density_heuristic(spec).selected == []


def test_bootstrap_interval_is_reproducible_and_exact_for_constant_values():
    assert interval([2.0] * 30) == {"mean": 2.0, "ci95_low": 2.0, "ci95_high": 2.0}
    assert interval([float(i) for i in range(30)]) == interval([float(i) for i in range(30)])


def test_benchmark_rejects_insufficient_seeds_before_solving(small_input):
    with pytest.raises(ValueError, match="30 unique"):
        benchmark(small_input, seeds=[1, 2, 3], year=2027, scenario_id="base")


def test_full_paired_benchmark_preserves_stream_and_physical_audit(small_input):
    spec = small_input.model_copy(deep=True)
    spec.parameters.simulation_days = 1
    result = benchmark(spec, seeds=list(range(30)), year=2027, scenario_id="base")
    assert result["solver"]["verification"]["passed"]
    assert result["plans"]["existing"]["capex_rub_total"] == 0
    assert result["plans"]["optimized"]["capex_rub_total"] <= spec.parameters.total_budget_rub
    assert len(result["seed_rows"]) == 540  # 3 plans × 30 seeds × (base + 5 stresses)
    assert result["stress"]["optimized"]["conditions"]["outage"]["p95_wait_minutes"]["mean"] is None
    assert result["stress"]["optimized"]["conditions"]["grid_x0_75"]["service_fraction"]["mean"] is not None
    assert result["paired_differences"]["optimized_minus_existing"]["energy_kwh_per_day"]["mean"] >= 0
