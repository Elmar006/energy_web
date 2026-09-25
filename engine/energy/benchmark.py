"""Reproducible, paired operational benchmark for a planning scenario.

The benchmark does not train/tune on the simulation stream. Its baselines use
only the public planning input; all plans receive the same random arrivals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from time import monotonic

import numpy as np

from .contracts import PlanningInput
from .benchmark_protocol import BenchmarkProtocol, input_sha256, load_locked_protocol
from .optimizer import solve
from .simulation import simulate


@dataclass
class Plan:
    name: str
    selected: list[dict] = field(default_factory=list)
    grid_upgrades: list[dict] = field(default_factory=list)
    battery: list[dict] = field(default_factory=list)
    solar: list[dict] = field(default_factory=list)


def existing_network(spec: PlanningInput) -> Plan:
    first_year = spec.parameters.years[0]
    return Plan("existing", [
        {"site_id": site.id, "option_id": site.existing_option_id, "year": first_year}
        for site in spec.sites if site.existing_option_id
    ])


def density_heuristic(spec: PlanningInput) -> Plan:
    """Place stations by reachable daily demand per ruble, with conservative grid checks.

    This intentionally simple comparator has no future scenario optimization,
    storage or grid upgrades. It respects site access, compatibility, lead
    period, budget and the *minimum* hourly node headroom without double use.
    """
    plan = existing_network(spec)
    site_by_id = {site.id: site for site in spec.sites}
    options = {option.id: option for option in spec.options}
    edges = {(edge.zone_id, edge.site_id): edge.minutes for edge in spec.travel_edges}
    remaining_node_kw = {node.id: min(node.headroom_kw) for node in spec.grid_nodes}
    for item in plan.selected:
        site = site_by_id[item["site_id"]]
        remaining_node_kw[site.grid_node_id] -= options[item["option_id"]].connection_kw
    # An existing connection can be throttled by a smaller stated headroom.
    # It consumes all conservative room for *new* equipment at that node.
    remaining_node_kw = {node_id: max(0.0, value)
                         for node_id, value in remaining_node_kw.items()}
    spent_total = 0.0
    selected_sites = {item["site_id"] for item in plan.selected}
    scenario = spec.scenarios[0]
    for period, year in enumerate(spec.parameters.years):
        remaining_year = spec.parameters.annual_budgets_rub[period]
        while True:
            candidates = []
            for site in spec.sites:
                if (site.id in selected_sites or site.id in spec.excluded_site_ids
                        or period < site.earliest_period):
                    continue
                for option_id in site.option_ids:
                    option = options[option_id]
                    if option.capex_rub <= 0 or option.capex_rub > remaining_year + 1e-6:
                        continue
                    if spent_total + option.capex_rub > spec.parameters.total_budget_rub + 1e-6:
                        continue
                    if option.connection_kw > remaining_node_kw[site.grid_node_id] + 1e-6:
                        continue
                    weighted = 0.0
                    for zone in spec.zones:
                        minutes = edges.get((zone.id, site.id))
                        if (minutes is None or minutes > zone.max_travel_minutes
                                or zone.group not in option.allowed_groups):
                            continue
                        daily = sum(zone.hourly_kwh) * scenario.demand_multiplier[period]
                        weighted += daily * max(0.0, 1 - minutes / zone.max_travel_minutes)
                    # Limit the density score by an eight-hour charging day;
                    # this is ranking only, not an operational capacity claim.
                    weighted = min(weighted, 8 * option.ports * option.charger_kw)
                    if weighted > 0:
                        candidates.append((weighted / option.capex_rub, site.id, option_id))
            if not candidates:
                break
            _, site_id, option_id = max(candidates, key=lambda row: (row[0], row[1], row[2]))
            option = options[option_id]
            plan.selected.append({"site_id": site_id, "option_id": option_id, "year": year})
            selected_sites.add(site_id)
            remaining_node_kw[site_by_id[site_id].grid_node_id] -= option.connection_kw
            remaining_year -= option.capex_rub
            spent_total += option.capex_rub
    if not set(spec.locked_site_ids).issubset(selected_sites):
        raise ValueError("density heuristic cannot satisfy locked-site constraints")
    return plan


def investment_by_year(spec: PlanningInput, plan: Plan) -> dict[int, float]:
    sites = {site.id: site for site in spec.sites}
    options = {option.id: option for option in spec.options}
    nodes = {node.id: node for node in spec.grid_nodes}
    amounts = {year: 0.0 for year in spec.parameters.years}
    for item in plan.selected:
        if sites[item["site_id"]].existing_option_id != item["option_id"]:
            amounts[item["year"]] += options[item["option_id"]].capex_rub
    for item in plan.grid_upgrades:
        amounts[item["year"]] += nodes[item["grid_node_id"]].upgrade_capex_rub
    for item in plan.battery:
        amounts[item["year"]] += item["kwh"] * sites[item["site_id"]].battery_capex_per_kwh_rub
    for item in plan.solar:
        amounts[item["year"]] += item["kw"] * sites[item["site_id"]].pv_capex_per_kw_rub
    return amounts


def accessibility(spec: PlanningInput, plan: Plan, year: int, scenario_id: str) -> dict:
    sites = {site.id: site for site in spec.sites}
    options = {option.id: option for option in spec.options}
    active = {item["site_id"]: options[item["option_id"]]
              for item in plan.selected if item["year"] <= year}
    edges = {(edge.zone_id, edge.site_id): edge.minutes for edge in spec.travel_edges}
    scenario = next(s for s in spec.scenarios if s.id == scenario_id)
    multiplier = scenario.demand_multiplier[spec.parameters.years.index(year)]
    total = reachable = weighted_minutes = 0.0
    for zone in spec.zones:
        demand = sum(zone.hourly_kwh) * multiplier
        total += demand
        minutes = [edge for sid, option in active.items()
                   if zone.group in option.allowed_groups
                   if (edge := edges.get((zone.id, sid))) is not None
                   and edge <= zone.max_travel_minutes]
        if minutes:
            reachable += demand
            weighted_minutes += demand * min(minutes)
    return {"demand_weighted_reachable_fraction": round(reachable / total, 6) if total else 1.0,
            "weighted_nearest_road_minutes": round(weighted_minutes / reachable, 3) if reachable else None}


def interval(values: list[float], *, bootstrap_seed: int = 20260924) -> dict:
    if not values:
        return {"mean": None, "ci95_low": None, "ci95_high": None}
    array = np.asarray(values, dtype=float)
    if len(array) == 1:
        low = high = float(array[0])
    else:
        rng = np.random.default_rng(bootstrap_seed)
        draws = rng.integers(0, len(array), size=(5000, len(array)))
        means = array[draws].mean(axis=1)
        low, high = np.percentile(means, [2.5, 97.5])
    return {"mean": round(float(array.mean()), 4),
            "ci95_low": round(float(low), 4), "ci95_high": round(float(high), 4)}


def _run(spec: PlanningInput, plan: Plan, year: int, scenario_id: str, seed: int) -> dict:
    run = simulate(spec, plan.selected, year=year, scenario_id=scenario_id, seed=seed,
                   grid_upgrades=plan.grid_upgrades, battery=plan.battery, solar=plan.solar)
    if not run["dispatch_verification"]["passed"]:
        raise ValueError(f"physical dispatch audit failed: {plan.name}, {year}, seed {seed}")
    return run


def _metrics(spec: PlanningInput, plan: Plan, run: dict, *, cost_plan: Plan | None = None) -> dict:
    options = {option.id: option for option in spec.options}
    active = {item["site_id"]: options[item["option_id"]]
              for item in plan.selected if item["year"] <= run["year"]}
    capacity = sum(option.ports * option.charger_kw for option in active.values())
    grid = sum(row["grid_kwh"] for row in run["dispatch_by_site"])
    discharged = sum(row["battery_discharge_kwh"] for row in run["dispatch_by_site"])
    fixed_items = (cost_plan or plan).selected
    fixed = sum(options[item["option_id"]].annual_fixed_rub for item in fixed_items
                if item["year"] <= run["year"])
    scenario = next(s for s in spec.scenarios if s.id == run["scenario_id"])
    annual_revenue = 365 / run["simulation_days"] * (
        run["energy_kwh"] * spec.parameters.sale_rub_per_kwh * scenario.tariff_multiplier
        - grid * spec.parameters.purchase_rub_per_kwh
        - discharged * spec.parameters.storage_degradation_rub_per_kwh)
    return {
        "requested_kwh_per_day": run["requested_energy_kwh"] / run["simulation_days"],
        "energy_kwh_per_day": run["energy_kwh"] / run["simulation_days"],
        "service_fraction": run["energy_kwh"] / run["requested_energy_kwh"]
        if run["requested_energy_kwh"] else 1.0,
        "refused_sessions": float(run["refused_sessions"]),
        "p95_wait_minutes": (float(run["p95_wait_minutes"])
                             if run["p95_wait_minutes"] is not None else None),
        "nameplate_energy_utilization": run["energy_kwh"] / (capacity * 24 * run["simulation_days"])
        if capacity else 0.0,
        "annual_operating_cash_proxy_rub": annual_revenue - fixed,
    }


def _git_head() -> str | None:
    if os.environ.get("ENERGY_SOURCE_GIT_HEAD"):
        return os.environ["ENERGY_SOURCE_GIT_HEAD"]
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL,
                                       text=True).strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def benchmark(spec: PlanningInput, *, seeds: list[int] | None = None,
              year: int | None = None, scenario_id: str | None = None,
              protocol: BenchmarkProtocol | None = None) -> dict:
    if protocol is not None:
        if seeds is not None or year is not None or scenario_id is not None:
            raise ValueError("ad-hoc seed, year and scenario overrides are forbidden with a protocol")
        protocol.verify_input(spec)
        seeds = list(protocol.split.evaluation_seeds)
        year = protocol.evaluation_year
        scenario_id = protocol.evaluation_scenario_id
    elif seeds is None or year is None or scenario_id is None:
        raise ValueError("seeds, year and scenario_id are required without a protocol")
    assert seeds is not None and year is not None and scenario_id is not None
    if len(seeds) < 30 or len(set(seeds)) != len(seeds) or any(seed < 0 for seed in seeds):
        raise ValueError("benchmark requires at least 30 unique nonnegative seeds")
    if year not in spec.parameters.years or scenario_id not in {s.id for s in spec.scenarios}:
        raise ValueError("unknown year or scenario")
    started = monotonic()
    optimized = solve(spec)
    if optimized.status not in ("optimal", "feasible") or not optimized.verification.get("passed"):
        raise ValueError(f"optimizer did not return a physically verified plan: {optimized.status}: {optimized.diagnostic}")
    plans = {
        "existing": existing_network(spec),
        "density": density_heuristic(spec),
        "optimized": Plan("optimized", optimized.selected, optimized.grid_upgrades,
                          optimized.battery, optimized.solar),
    }
    annual_capex = {name: investment_by_year(spec, plan) for name, plan in plans.items()}
    for name, costs in annual_capex.items():
        if (sum(costs.values()) > spec.parameters.total_budget_rub + 1e-4
                or any(costs[y] > spec.parameters.annual_budgets_rub[p] + 1e-4
                       for p, y in enumerate(spec.parameters.years))):
            raise ValueError(f"{name} exceeds investment budget")
    base_runs: dict[str, dict[tuple[int, int], dict]] = {name: {} for name in plans}
    for y in spec.parameters.years:
        for seed in seeds:
            reference = None
            for name, plan in plans.items():
                run = _run(spec, plan, y, scenario_id, seed)
                stream = (run["arrivals_by_day_hour"], run["requested_energy_kwh"])
                if reference is not None and stream != reference:
                    raise ValueError("comparison plans received different arrival streams")
                reference = stream
                base_runs[name][(y, seed)] = run
    summaries = {}
    seed_rows = []
    for name, plan in plans.items():
        years = {}
        for y in spec.parameters.years:
            rows = [_metrics(spec, plan, base_runs[name][(y, seed)]) for seed in seeds]
            active = [item for item in plan.selected if item["year"] <= y]
            site_utilization = {}
            option_map = {option.id: option for option in spec.options}
            for item in active:
                option = option_map[item["option_id"]]
                daily = [base_runs[name][(y, seed)]["energy_by_site_kwh"].get(item["site_id"], 0.0)
                         / spec.parameters.simulation_days for seed in seeds]
                site_utilization[item["site_id"]] = {
                    "energy_kwh_per_day": interval(daily),
                    "nameplate_energy_utilization": interval([
                        value / (24 * option.ports * option.charger_kw) for value in daily]),
                }
            years[str(y)] = {
                "accessibility": accessibility(spec, plan, y, scenario_id),
                "site_utilization": site_utilization,
                "metrics": {key: interval([row[key] for row in rows if row[key] is not None])
                            for key in rows[0]},
            }
            for seed, values in zip(seeds, rows):
                seed_rows.append({"plan": name, "condition": "base", "year": y,
                                  "scenario_id": scenario_id, "seed": seed, **values})
        npvs = []
        for seed in seeds:
            npv = sum((
                _metrics(spec, plan, base_runs[name][(y, seed)])["annual_operating_cash_proxy_rub"]
                - annual_capex[name][y]) / ((1 + spec.parameters.discount_rate) ** p)
                for p, y in enumerate(spec.parameters.years))
            npvs.append(npv)
        summaries[name] = {
            "selected": plan.selected, "grid_upgrades": plan.grid_upgrades,
            "battery": plan.battery, "solar": plan.solar,
            "capex_rub_by_year": {str(y): round(value, 2) for y, value in annual_capex[name].items()},
            "capex_rub_total": round(sum(annual_capex[name].values()), 2),
            "scenario_npv_proxy_rub": interval(npvs),
            "years": years,
        }
    paired = {}
    for comparator in ("existing", "density"):
        differences = {}
        for key in ("energy_kwh_per_day", "service_fraction", "refused_sessions",
                    "p95_wait_minutes", "annual_operating_cash_proxy_rub"):
            matched = [(_metrics(spec, plans["optimized"], base_runs["optimized"][(year, seed)])[key],
                        _metrics(spec, plans[comparator], base_runs[comparator][(year, seed)])[key])
                       for seed in seeds]
            differences[key] = interval([primary - baseline for primary, baseline in matched
                                         if primary is not None and baseline is not None])
        paired[f"optimized_minus_{comparator}"] = differences

    # One failed station for each plan: highest mean energy in the base runs.
    # The failure spans the entire simulated window and triggers no rebuild.
    def scale_demand(factor: float) -> PlanningInput:
        changed = spec.model_copy(deep=True)
        for scenario in changed.scenarios:
            if scenario.id == scenario_id:
                scenario.demand_multiplier[changed.parameters.years.index(year)] *= factor
        return changed

    def scale_grid(factor: float) -> PlanningInput:
        changed = spec.model_copy(deep=True)
        for node in changed.grid_nodes:
            node.headroom_kw = [power * factor for power in node.headroom_kw]
        return changed

    stress_inputs = {
        "demand_x0_75": scale_demand(0.75),
        "demand_x1_25": scale_demand(1.25),
        "grid_x0_75": scale_grid(0.75),
        "grid_x1_25": scale_grid(1.25),
    }
    stress = {}
    stress_streams: dict[tuple[str, int], tuple] = {}
    for name, plan in plans.items():
        by_site: dict[str, float] = {}
        for seed in seeds:
            for sid, value in base_runs[name][(year, seed)]["energy_by_site_kwh"].items():
                by_site[sid] = by_site.get(sid, 0.0) + value
        failed_site = max(sorted(by_site), key=by_site.get) if by_site else None
        outage_plan = Plan(name + "_outage", [item for item in plan.selected
                                             if item["site_id"] != failed_site],
                           plan.grid_upgrades, [item for item in plan.battery if item["site_id"] != failed_site],
                           [item for item in plan.solar if item["site_id"] != failed_site])
        conditions = {}
        for label, scenario_spec, current_plan in [
            ("outage", spec, outage_plan),
            *((label, changed, plan) for label, changed in stress_inputs.items()),
        ]:
            rows = []
            for seed in seeds:
                run = _run(scenario_spec, current_plan, year, scenario_id, seed)
                stream = (run["arrivals_by_day_hour"], run["requested_energy_kwh"])
                key = (label, seed)
                if key in stress_streams and stream != stress_streams[key]:
                    raise ValueError("stress plans received different arrival streams")
                stress_streams[key] = stream
                rows.append(_metrics(scenario_spec, current_plan, run, cost_plan=plan))
                seed_rows.append({"plan": name, "condition": label, "year": year,
                                  "scenario_id": scenario_id, "seed": seed, **rows[-1]})
            conditions[label] = {key: interval([row[key] for row in rows if row[key] is not None])
                                 for key in rows[0]}
        stress[name] = {"failed_site_id": failed_site, "conditions": conditions}
    source_digest = hashlib.sha256()
    source_files = sorted(Path(__file__).parent.rglob("*.py"))
    for source_file in source_files:
        name = source_file.relative_to(Path(__file__).parent).as_posix()
        content = source_file.read_bytes()
        source_digest.update(name.encode())
        source_digest.update(len(content).to_bytes(8, "big"))
        source_digest.update(content)
    return {
        "metadata": {
            "input_sha256": input_sha256(spec),
            "protocol": ({"status": "manifest_validated", "sha256": protocol.sha256,
                          "spec": protocol.model_dump(mode="json")}
                         if protocol is not None else {"status": "unregistered"}),
            "engine_source_sha256": source_digest.hexdigest(),
            "engine_source_files": [path.relative_to(Path(__file__).parent).as_posix()
                                    for path in source_files],
            "git_head": _git_head(), "year": year, "scenario_id": scenario_id,
            "seeds": seeds, "simulation_days": spec.parameters.simulation_days,
            "python": platform.python_version(), "pyomo": version("pyomo"),
            "highspy": version("highspy"), "simpy": version("simpy"),
            "numpy": version("numpy"), "elapsed_seconds": round(monotonic() - started, 2),
            "interval_method": "paired nonparametric bootstrap, 5000 resamples, seed 20260924",
            "demand_label": "scenario/assumed unless independently supported by input datasets",
        },
        "solver": {"status": optimized.status, "gap": optimized.gap,
                   "objective": optimized.objective, "verification": optimized.verification},
        "primary_result": ({
            "comparison": protocol.primary_comparison,
            "metric": protocol.primary_metric,
            "difference_direction": "optimized_minus_density; positive means higher served fraction",
            "difference": paired[protocol.primary_comparison][protocol.primary_metric],
        } if protocol is not None else None),
        "plans": summaries, "paired_differences": paired, "stress": stress,
        "seed_rows": seed_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--protocol-lock", type=Path)
    parser.add_argument("--year", type=int)
    parser.add_argument("--scenario")
    parser.add_argument("--seeds", type=int)
    args = parser.parse_args()
    spec = PlanningInput.model_validate_json(args.input.read_bytes())
    if args.protocol is not None or args.protocol_lock is not None:
        if args.protocol is None or args.protocol_lock is None:
            parser.error("--protocol and --protocol-lock must be supplied together")
        if args.year is not None or args.scenario is not None or args.seeds is not None:
            parser.error("--year, --scenario and --seeds cannot override a locked protocol")
        result = benchmark(spec, protocol=load_locked_protocol(args.protocol, args.protocol_lock))
    else:
        if args.year is None or args.scenario is None:
            parser.error("--year and --scenario are required without a protocol")
        count = 30 if args.seeds is None else args.seeds
        result = benchmark(spec, seeds=list(range(1, count + 1)),
                           year=args.year, scenario_id=args.scenario)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
