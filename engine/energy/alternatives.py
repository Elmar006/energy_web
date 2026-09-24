"""Epsilon-constraint plans with explicit service floors and common test streams."""

from __future__ import annotations

import json

from .contracts import PlanningInput
from .optimizer import solve
from .simulation import simulate
from .validation import compare_economics, compare_operations


def calculate_alternatives(spec: PlanningInput, fractions: list[float],
                           seeds: list[int], solver_seconds: int) -> list[dict]:
    plans = []
    investment_targets = {}
    simulations_by_investment = {}
    for fraction in fractions:
        # Give each alternative its own bounded solve. The planning input is an
        # immutable snapshot for the caller; only the computational cap changes.
        candidate = spec.model_copy(deep=True)
        candidate.parameters.solver_seconds = min(spec.parameters.solver_seconds, solver_seconds)
        result = solve(candidate, minimum_service_fraction=fraction)
        service_ratios = [min(1, max(0, row["served_kwh"] / row["demand_kwh"]))
                          for row in result.service_by_year if row["demand_kwh"] > 0]
        item = {"target_service_fraction": fraction,
                "objective_kind": "minimum_investment_rub",
                "achieved_min_service_fraction": (round(min(service_ratios, default=1), 6)
                                                   if result.status in ("optimal", "feasible") else None),
                "same_investment_as_target": None,
                "optimization": result.as_dict(), "simulation": [],
                "operational_validation": [], "operational_economics": []}
        if result.status in ("optimal", "feasible"):
            signature = json.dumps([result.selected, result.grid_upgrades, result.battery, result.solar],
                                   sort_keys=True, separators=(",", ":"))
            if signature in investment_targets:
                item["same_investment_as_target"] = investment_targets[signature]
                item["simulation"] = simulations_by_investment[signature]
            else:
                investment_targets[signature] = fraction
                for scenario in spec.scenarios:
                    for year in spec.parameters.years:
                        for seed in seeds:
                            run = simulate(spec, result.selected, year=year,
                                           scenario_id=scenario.id, seed=seed,
                                           grid_upgrades=result.grid_upgrades,
                                           battery=result.battery, solar=result.solar)
                            if not run["dispatch_verification"]["passed"]:
                                raise RuntimeError("alternative operational dispatch failed physical verification")
                            item["simulation"].append(run)
                simulations_by_investment[signature] = item["simulation"]
            item["operational_validation"] = compare_operations(result, item["simulation"])
            item["operational_economics"] = compare_economics(spec, result, item["simulation"])
        plans.append(item)
    return plans
