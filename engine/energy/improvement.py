"""Bounded plan search on development streams, before sealed holdout validation.

This is an engineering heuristic, not a proof of a Pareto optimum. It only
forces feasible additional sites and keeps the best physically verified plan
under the declared development-service thresholds. Holdout seeds are never
passed to this module.
"""
from __future__ import annotations

from collections import defaultdict
from math import inf, isfinite
from statistics import mean
from typing import Callable

from .acceptance import ServiceRequirements
from .contracts import PlanningInput
from .optimizer import SolveResult


def simulate_plan(spec: PlanningInput, result: SolveResult, seeds: list[int],
                  simulate_fn: Callable) -> list[dict]:
    """Run the same external seed identities for every candidate plan."""
    rows: list[dict] = []
    for scenario in spec.scenarios:
        for year in spec.parameters.years:
            for seed in seeds:
                run = simulate_fn(spec, result.selected, year=year,
                                  scenario_id=scenario.id, seed=seed,
                                  grid_upgrades=result.grid_upgrades,
                                  battery=result.battery, solar=result.solar)
                if run.get("dispatch_verification", {}).get("passed") is not True:
                    raise ValueError("development simulation failed physical dispatch verification")
                rows.append(run)
    return rows


def _development_score(rows: list[dict], spec: PlanningInput,
                       requirements: ServiceRequirements, seeds: list[int]) -> tuple[float, dict]:
    """Deterministic screening score; no confidence or acceptance claim."""
    expected = {(scenario.id, year, seed) for scenario in spec.scenarios
                for year in spec.parameters.years for seed in seeds}
    actual = {(row.get("scenario_id"), row.get("year"), row.get("seed")) for row in rows}
    if len(actual) != len(rows) or actual != expected:
        return inf, {"reason": "incomplete_development_coverage"}
    by_condition: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        by_condition[(row["scenario_id"], row["year"])].append(row)
    worst_penalty = 0.0
    details = []
    for (scenario_id, year), condition_rows in sorted(by_condition.items()):
        values = defaultdict(list)
        for row in condition_rows:
            arrivals = row.get("arrivals")
            served = row.get("served_sessions")
            refused = row.get("refused_sessions")
            requested = row.get("requested_energy_kwh")
            delivered = row.get("energy_kwh")
            if not all(isinstance(v, (float, int)) and not isinstance(v, bool)
                       and isfinite(v) and v >= 0 for v in
                       (arrivals, served, refused, requested, delivered)):
                return inf, {"reason": "invalid_development_metrics"}
            if served + refused != arrivals or delivered > requested + 0.002:
                return inf, {"reason": "invalid_development_totals"}
            if requested > 0:
                values["energy_fraction"].append(delivered / requested)
            if arrivals > 0:
                values["session_fraction"].append(served / arrivals)
                values["refusal_fraction"].append(refused / arrivals)
            wait = row.get("p95_wait_minutes")
            if served > 0 and isinstance(wait, (float, int)) and not isinstance(wait, bool) and isfinite(wait) and wait >= 0:
                values["p95_wait_minutes"].append(wait)
        metrics = {}
        for name, threshold, direction in (
            ("energy_fraction", requirements.min_energy_fraction, "min"),
            ("session_fraction", requirements.min_session_fraction, "min"),
            ("refusal_fraction", requirements.max_refusal_fraction, "max"),
            ("p95_wait_minutes", requirements.max_mean_seed_p95_wait_minutes, "max"),
        ):
            if threshold is None:
                continue
            if len(values[name]) != len(condition_rows):
                return inf, {"reason": "development_metric_unavailable", "metric": name}
            observed = mean(values[name])
            penalty = (max(0.0, threshold - observed) if direction == "min"
                       else max(0.0, observed - threshold)) / max(1.0, abs(threshold))
            worst_penalty = max(worst_penalty, penalty)
            metrics[name] = {"mean": round(observed, 6), "threshold": threshold,
                             "direction": direction, "shortfall": round(penalty, 6)}
        details.append({"scenario_id": scenario_id, "year": year, "metrics": metrics})
    return worst_penalty, {"conditions": details, "scope": "development_seeds_only",
                           "not_independent_validation": True}


def _candidate_sites(spec: PlanningInput, result: SolveResult, rows: list[dict],
                     attempted: set[str]) -> list[str]:
    selected = {item["site_id"] for item in result.selected}
    pressure = defaultdict(float)
    for row in rows:
        for zone_id, count in row.get("refused_by_zone", {}).items():
            pressure[zone_id] += count
    if not pressure:
        pressure.update({zone.id: sum(zone.hourly_kwh) for zone in spec.zones})
    zones = {zone.id: zone for zone in spec.zones}
    options = {option.id: option for option in spec.options}
    reachable = defaultdict(float)
    for edge in spec.travel_edges:
        zone = zones[edge.zone_id]
        if edge.minutes <= zone.max_travel_minutes:
            reachable[edge.site_id] += pressure[zone.id] / (1.0 + edge.minutes)
    eligible = []
    for site in spec.sites:
        if (site.id in selected or site.id in attempted or site.id in spec.excluded_site_ids
                or site.id in spec.locked_site_ids or reachable[site.id] <= 0):
            continue
        compatible = any(zones[edge.zone_id].group in options[option_id].allowed_groups
                         for edge in spec.travel_edges if edge.site_id == site.id
                         and edge.minutes <= zones[edge.zone_id].max_travel_minutes
                         for option_id in site.option_ids)
        if compatible:
            cheapest = min(options[oid].capex_rub for oid in site.option_ids)
            eligible.append((-reachable[site.id], cheapest, site.id))
    return [site_id for _, _, site_id in sorted(eligible)]


def improve_plan(spec: PlanningInput, initial: SolveResult, *, seeds: list[int],
                 requirements: ServiceRequirements, max_iterations: int,
                 solve_fn: Callable, simulate_fn: Callable) -> tuple[SolveResult, list[dict]]:
    """Select at most one extra locked site per solve on development seeds.

    A failed or worse candidate does not replace the previous best. Final
    service acceptance must be calculated separately on disjoint holdout seeds.
    """
    history = []
    best = initial
    best_rows: list[dict] = []
    if initial.status not in ("optimal", "feasible") or initial.verification.get("passed") is not True:
        return initial, [{"iteration": 0, "status": "not_tested", "reason": "initial_plan_not_physically_feasible"}]
    best_rows = simulate_plan(spec, initial, seeds, simulate_fn)
    best_score, summary = _development_score(best_rows, spec, requirements, seeds)
    history.append({"iteration": 0, "forced_site_id": None,
                    "optimization_status": initial.status,
                    "physical_verification_passed": True,
                    "development_score": best_score if isfinite(best_score) else None,
                    "development": summary, "selected_for_holdout": True})
    attempted: set[str] = set()
    for iteration in range(1, max_iterations + 1):
        if best_score <= 0:
            break
        candidates = _candidate_sites(spec, best, best_rows, attempted)
        if not candidates:
            history.append({"iteration": iteration, "status": "no_additional_reachable_site",
                            "selected_for_holdout": False})
            break
        site_id = candidates[0]
        attempted.add(site_id)
        candidate_spec = spec.model_copy(deep=True)
        candidate_spec.locked_site_ids = sorted(set(candidate_spec.locked_site_ids) | {site_id})
        candidate = solve_fn(candidate_spec)
        item = {"iteration": iteration, "forced_site_id": site_id,
                "optimization_status": candidate.status,
                "physical_verification_passed": candidate.verification.get("passed") is True,
                "selected_for_holdout": False}
        if candidate.status in ("optimal", "feasible") and candidate.verification.get("passed") is True:
            rows = simulate_plan(spec, candidate, seeds, simulate_fn)
            score, summary = _development_score(rows, spec, requirements, seeds)
            item.update({"development_score": score if isfinite(score) else None,
                         "development": summary})
            if score < best_score:
                history[-1]["selected_for_holdout"] = False
                item["selected_for_holdout"] = True
                best, best_rows, best_score = candidate, rows, score
        history.append(item)
    return best, history
