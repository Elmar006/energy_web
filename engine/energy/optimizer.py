"""Multi-period charging, grid, storage and solar investment model.

Energy is kWh per one-hour slot. Investment and revenue are nominal rubles;
cash flows are discounted to the first planning year.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from math import isfinite
from time import monotonic

import pyomo.environ as pyo

from .contracts import PlanningInput

MAX_ENERGY_AUDIT_ROWS = 2000


@dataclass
class SolveResult:
    status: str
    objective: float | None
    gap: float | None
    selected: list[dict]
    grid_upgrades: list[dict]
    battery: list[dict]
    solar: list[dict]
    served_kwh: dict[str, float]
    unmet_kwh: dict[str, float]
    cashflow_rub: dict[str, float]
    diagnostic: str | None = None
    risk_metrics: dict[str, float] = field(default_factory=dict)
    investment_rub_by_year: list[dict] = field(default_factory=list)
    energy_audit: list[dict] = field(default_factory=list)
    verification: dict[str, float | bool] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return self.__dict__


def solve(spec: PlanningInput) -> SolveResult:
    d = spec
    par = d.parameters
    zones = {x.id: x for x in d.zones}
    sites = {x.id: x for x in d.sites}
    opts = {x.id: x for x in d.options}
    nodes = {x.id: x for x in d.grid_nodes}
    scenarios = {x.id: x for x in d.scenarios}
    np = len(par.years)
    periods = range(np)
    hours = range(24)
    edge_minutes = {(x.zone_id, x.site_id): x.minutes for x in d.travel_edges}
    edges = [(z, s) for (z, s), mins in edge_minutes.items() if mins <= zones[z].max_travel_minutes]
    edge_by_zone = defaultdict(list)
    edge_by_site = defaultdict(list)
    for z, s in edges:
        edge_by_zone[z].append((z, s))
        edge_by_site[s].append((z, s))
    if par.minimum_zone_service:
        for zone in d.zones:
            if not edge_by_zone[zone.id] and any(sum(zone.hourly_kwh) * scenario.demand_multiplier[p] > 0
                                                 for scenario in d.scenarios for p in periods):
                return SolveResult("infeasible", None, None, [], [], [], [], {}, {}, {},
                                   f"Зона {zone.id} недостижима при минимальном требовании обслуживания")
    site_options = [(s.id, oid) for s in d.sites for oid in s.option_ids]
    node_sites = defaultdict(list)
    for site in d.sites:
        node_sites[site.grid_node_id].append(site.id)

    m = pyo.ConcreteModel()
    m.Y = pyo.Var(site_options, periods, within=pyo.Binary)
    m.U = pyo.Var(nodes.keys(), periods, within=pyo.Binary)
    m.B = pyo.Var(sites.keys(), periods, within=pyo.NonNegativeReals)
    m.G = pyo.Var(sites.keys(), periods, within=pyo.NonNegativeReals)
    m.X = pyo.Var(edges, periods, scenarios.keys(), hours, within=pyo.NonNegativeReals)
    m.Draw = pyo.Var(sites.keys(), periods, scenarios.keys(), hours, within=pyo.NonNegativeReals)
    m.PVUsed = pyo.Var(sites.keys(), periods, scenarios.keys(), hours, within=pyo.NonNegativeReals)
    m.Charge = pyo.Var(sites.keys(), periods, scenarios.keys(), hours, within=pyo.NonNegativeReals)
    m.Discharge = pyo.Var(sites.keys(), periods, scenarios.keys(), hours, within=pyo.NonNegativeReals)
    m.SOC = pyo.Var(sites.keys(), periods, scenarios.keys(), range(25), within=pyo.NonNegativeReals)
    m.BMode = pyo.Var(sites.keys(), periods, scenarios.keys(), hours, within=pyo.Binary)
    m.C = pyo.ConstraintList()

    active = lambda s, o, p: sum(m.Y[s, o, k] for k in periods if k <= p)
    battery = lambda s, p: sum(m.B[s, k] for k in periods if k <= p)
    solar = lambda s, p: sum(m.G[s, k] for k in periods if k <= p)
    upgraded = lambda n, p: sum(m.U[n, k] for k in periods if k <= p)
    installed = lambda s, p: sum(active(s, o, p) for o in sites[s].option_ids)
    station_load = lambda s, p, q, h: sum(m.X[z, s, p, q, h] for z, _ in edge_by_site[s])

    for site in d.sites:
        s = site.id
        m.C.add(sum(m.Y[s, o, p] for o in site.option_ids for p in periods) <= 1)
        if site.existing_option_id:
            m.Y[s, site.existing_option_id, 0].fix(1)
        for o in site.option_ids:
            for p in periods:
                if par.years[p] < par.years[0] + site.earliest_period or s in d.excluded_site_ids:
                    if not (site.existing_option_id == o and p == 0):
                        m.Y[s, o, p].fix(0)
        if s in d.locked_site_ids:
            m.C.add(sum(m.Y[s, o, p] for o in site.option_ids for p in periods) == 1)
        for p in periods:
            m.C.add(battery(s, p) <= site.battery_max_kwh * installed(s, p))
            m.C.add(solar(s, p) <= site.pv_max_kw * installed(s, p))

    for node in d.grid_nodes:
        m.C.add(sum(m.U[node.id, p] for p in periods) <= 1)
        if node.upgrade_kw == 0:
            for p in periods:
                m.U[node.id, p].fix(0)

    def invest(p):
        return (
            sum(m.Y[s, o, p] * (0 if sites[s].existing_option_id == o else opts[o].capex_rub) for s, o in site_options)
            + sum(m.U[n, p] * nodes[n].upgrade_capex_rub for n in nodes)
            + sum(m.B[s, p] * sites[s].battery_capex_per_kwh_rub + m.G[s, p] * sites[s].pv_capex_per_kw_rub for s in sites)
        )

    for p in periods:
        m.C.add(invest(p) <= par.annual_budgets_rub[p])
    m.C.add(sum(invest(p) for p in periods) <= par.total_budget_rub)

    for q, scenario in scenarios.items():
        for p in periods:
            for h in hours:
                for z, zone in zones.items():
                    demand = zone.hourly_kwh[h] * scenario.demand_multiplier[p]
                    if edge_by_zone[z]:
                        m.C.add(sum(m.X[z0, s, p, q, h] for z0, s in edge_by_zone[z]) <= demand)
                for site in d.sites:
                    s = site.id
                    capacity = sum(active(s, o, p) * opts[o].ports * opts[o].charger_kw for o in site.option_ids)
                    connection = sum(active(s, o, p) * opts[o].connection_kw for o in site.option_ids)
                    m.C.add(station_load(s, p, q, h) <= capacity)
                    m.C.add(m.Draw[s, p, q, h] <= connection)
                    m.C.add(m.SOC[s, p, q, h] <= battery(s, p))
                    m.C.add(m.Charge[s, p, q, h] <= battery(s, p) / par.storage_max_hours)
                    m.C.add(m.Discharge[s, p, q, h] <= battery(s, p) / par.storage_max_hours)
                    m.C.add(m.Charge[s, p, q, h] <= site.battery_max_kwh / par.storage_max_hours * m.BMode[s, p, q, h])
                    m.C.add(m.Discharge[s, p, q, h] <= site.battery_max_kwh / par.storage_max_hours * (1 - m.BMode[s, p, q, h]))
                    m.C.add(m.SOC[s, p, q, h + 1] == m.SOC[s, p, q, h] + par.storage_efficiency * m.Charge[s, p, q, h] - m.Discharge[s, p, q, h] / par.storage_efficiency)
                    m.C.add(m.PVUsed[s, p, q, h] <= solar(s, p) * par.pv_hourly_factor[h] * scenario.pv_multiplier)
                    m.C.add(m.Draw[s, p, q, h] + m.Discharge[s, p, q, h] + m.PVUsed[s, p, q, h] == station_load(s, p, q, h) + m.Charge[s, p, q, h])
                for n, node in nodes.items():
                    m.C.add(sum(m.Draw[s, p, q, h] for s in node_sites[n]) <= node.headroom_kw[h] + upgraded(n, p) * node.upgrade_kw)
                for z, s in edges:
                    compatible = sum(active(s, o, p) for o in sites[s].option_ids if zones[z].group in opts[o].allowed_groups)
                    m.C.add(m.X[z, s, p, q, h] <= zones[z].hourly_kwh[h] * scenario.demand_multiplier[p] * compatible)
            for s in sites:
                m.C.add(m.SOC[s, p, q, 24] == m.SOC[s, p, q, 0])
                m.C.add(m.SOC[s, p, q, 24] <= battery(s, p))
            if par.minimum_zone_service:
                for z, zone in zones.items():
                    if edge_by_zone[z]:
                        m.C.add(sum(m.X[z0, s, p, q, h] for z0, s in edge_by_zone[z] for h in hours) >= par.minimum_zone_service * sum(zone.hourly_kwh) * scenario.demand_multiplier[p])

    served = lambda q: sum(m.X[z, s, p, q, h] for z, s in edges for p in periods for h in hours)
    total_demand = {q: sum(sum(z.hourly_kwh) * scenarios[q].demand_multiplier[p]
                           for z in zones.values() for p in periods) for q in scenarios}
    cash = {}
    for q, scenario in scenarios.items():
        annual = []
        for p in periods:
            revenue = sum(m.X[z, s, p, q, h] for z, s in edges for h in hours) * 365 * par.sale_rub_per_kwh * scenario.tariff_multiplier
            purchase = sum(m.Draw[s, p, q, h] for s in sites for h in hours) * 365 * par.purchase_rub_per_kwh
            degrade = sum(m.Discharge[s, p, q, h] for s in sites for h in hours) * 365 * par.storage_degradation_rub_per_kwh
            fixed = sum(active(s, o, p) * opts[o].annual_fixed_rub for s, o in site_options)
            annual.append((revenue - purchase - degrade - fixed - invest(p)) / ((1 + par.discount_rate) ** p))
        cash[q] = sum(annual)

    if par.risk == "expected_cvar":
        # Rockafellar-Uryasev linearization of the upper tail of losses.
        # Investment decisions remain common across all scenarios.
        m.CVaRThreshold = pyo.Var(within=pyo.NonNegativeReals)
        m.CVaRExcess = pyo.Var(scenarios.keys(), within=pyo.NonNegativeReals)
        if par.mode == "operator":
            m.Downside = pyo.Var(scenarios.keys(), within=pyo.NonNegativeReals)
            for q in scenarios:
                m.C.add(m.Downside[q] >= -cash[q])
            losses = {q: m.Downside[q] for q in scenarios}
            risk_limit = par.max_cvar_loss_rub
        else:
            losses = {q: total_demand[q] - served(q) for q in scenarios}
            risk_limit = par.max_cvar_unmet_kwh
        for q in scenarios:
            m.C.add(m.CVaRExcess[q] >= losses[q] - m.CVaRThreshold)
        m.C.add(m.CVaRThreshold + sum(scenarios[q].probability * m.CVaRExcess[q]
                                      for q in scenarios) / (1 - par.cvar_alpha) <= risk_limit)

    if par.mode == "operator":
        if par.risk == "worst_case":
            m.Worst = pyo.Var(within=pyo.Reals)
            for q in scenarios:
                m.C.add(m.Worst <= cash[q])
            m.Objective = pyo.Objective(expr=m.Worst, sense=pyo.maximize)
        else:
            m.Objective = pyo.Objective(expr=sum(scenarios[q].probability * cash[q] for q in scenarios), sense=pyo.maximize)
    else:
        if par.risk == "worst_case":
            m.Worst = pyo.Var(within=pyo.NonNegativeReals)
            for q in scenarios:
                m.C.add(m.Worst <= served(q))
            m.Objective = pyo.Objective(expr=m.Worst, sense=pyo.maximize)
        else:
            m.Objective = pyo.Objective(expr=sum(scenarios[q].probability * served(q) for q in scenarios), sense=pyo.maximize)

    solver = pyo.SolverFactory("appsi_highs")
    deadline = monotonic() + par.solver_seconds
    try:
        outcome = solver.solve(m, timelimit=par.solver_seconds, load_solutions=False)
    except Exception as exc:
        return SolveResult("error", None, None, [], [], [], [], {}, {}, {}, str(exc))
    term = str(outcome.solver.termination_condition)
    if term not in ("optimal", "maxTimeLimit"):
        return SolveResult("infeasible" if "infeasible" in term.lower() else "error", None, None, [], [], [], [], {}, {}, {}, term)
    if term == "maxTimeLimit" and getattr(outcome.solver, "best_feasible_objective", None) is None:
        return SolveResult("error", None, None, [], [], [], [], {}, {}, {}, "time limit without a feasible solution")
    m.solutions.load_from(outcome)
    primary_objective = pyo.value(m.Objective)

    if par.mode == "city" and term == "optimal":
        # Lexicographic priorities avoid dimension-dependent arbitrary weights.
        # First retain primary robust/expected coverage. Among its optima,
        # maximize total scenario coverage, then minimize road detour, then
        # maximize discounted cash flow. All tiers use one shared investment plan.
        weighted_served = sum((scenarios[q].probability if par.risk in ("expected", "expected_cvar") else 1 / len(scenarios)) * served(q)
                              for q in scenarios)
        weighted_travel = sum((scenarios[q].probability if par.risk in ("expected", "expected_cvar") else 1 / len(scenarios))
                              * edge_minutes[z, s] * m.X[z, s, p, q, h]
                              for q in scenarios for z, s in edges for p in periods for h in hours)
        weighted_cash = sum((scenarios[q].probability if par.risk in ("expected", "expected_cvar") else 1 / len(scenarios)) * cash[q]
                            for q in scenarios)
        tiers = []
        if par.risk == "worst_case" and edges:
            tiers.append(("total_service", weighted_served, pyo.maximize))
        if edges:
            tiers.append(("travel", weighted_travel, pyo.minimize))
        tiers.append(("economy", weighted_cash, pyo.maximize))
        previous = m.Objective
        previous_value = primary_objective
        previous_sense = pyo.maximize
        for name, expression, sense in tiers:
            remaining = deadline - monotonic()
            if remaining < 0.25:
                break
            tolerance = 1e-6 * max(1, abs(previous_value))
            if edges or par.risk == "worst_case":
                m.C.add(previous.expr >= previous_value - tolerance if previous_sense == pyo.maximize
                        else previous.expr <= previous_value + tolerance)
            previous.deactivate()
            tier_objective = pyo.Objective(expr=expression, sense=sense)
            setattr(m, f"Tier_{name}", tier_objective)
            try:
                tier_outcome = solver.solve(m, timelimit=remaining, load_solutions=False)
            except Exception:
                tier_objective.deactivate()
                previous.activate()
                break
            if str(tier_outcome.solver.termination_condition) != "optimal":
                tier_objective.deactivate()
                previous.activate()
                break
            m.solutions.load_from(tier_outcome)
            previous_value = pyo.value(tier_objective)
            previous_sense = sense
            previous = tier_objective
            outcome = tier_outcome
    selected = [dict(site_id=s, option_id=o, year=par.years[p]) for s, o in site_options for p in periods if pyo.value(m.Y[s, o, p]) > 0.5]
    upgrades = [dict(grid_node_id=n, year=par.years[p]) for n in nodes for p in periods if pyo.value(m.U[n, p]) > 0.5]
    batteries = [dict(site_id=s, year=par.years[p], kwh=round(pyo.value(m.B[s, p]), 4)) for s in sites for p in periods if pyo.value(m.B[s, p]) > 1e-6]
    pv = [dict(site_id=s, year=par.years[p], kw=round(pyo.value(m.G[s, p]), 4)) for s in sites for p in periods if pyo.value(m.G[s, p]) > 1e-6]
    served_raw = {q: pyo.value(served(q)) for q in scenarios}
    unmet_raw = {q: max(0, total_demand[q] - served_raw[q]) for q in scenarios}
    served_out = {q: round(value, 4) for q, value in served_raw.items()}
    unmet = {q: round(value, 4) for q, value in unmet_raw.items()}
    gap = None
    if hasattr(outcome.solver, "best_feasible_objective") and hasattr(outcome.solver, "best_objective_bound"):
        primal, dual = outcome.solver.best_feasible_objective, outcome.solver.best_objective_bound
        if primal is not None and dual is not None and isfinite(primal) and isfinite(dual):
            gap = abs(primal - dual) / max(1, abs(primal))
    cash_raw = {q: pyo.value(cash[q]) for q in scenarios}
    cash_out = {q: round(value, 2) for q, value in cash_raw.items()}
    risk_metrics = {}
    if par.risk == "expected_cvar":
        losses_out = ({q: max(0, -cash_raw[q]) for q in scenarios} if par.mode == "operator"
                      else unmet_raw)
        alpha = par.cvar_alpha
        probabilities = {q: scenarios[q].probability for q in scenarios}
        realized_cvar = min(eta + sum(probabilities[q] * max(0, loss - eta)
                                      for q, loss in losses_out.items()) / (1 - alpha)
                            for eta in [0, *losses_out.values()])
        risk_metrics = {"cvar_alpha": alpha,
                        ("cvar_loss_rub" if par.mode == "operator" else "cvar_unmet_kwh"):
                            round(realized_cvar, 4)}

    investment_raw = [pyo.value(invest(p)) for p in periods]
    investment_by_year = [{"year": par.years[p], "rub": round(value, 2)}
                          for p, value in enumerate(investment_raw)]
    max_budget_overrun = max(
        [max(0, value - par.annual_budgets_rub[p]) for p, value in enumerate(investment_raw)]
        + [max(0, sum(investment_raw) - par.total_budget_rub)]
    )
    energy_audit = []
    energy_audit_rows_total = 0
    max_balance_error = 0.0
    max_relative_balance_error = 0.0
    max_node_overload = 0.0
    max_connection_overload = 0.0
    max_equipment_overload = 0.0
    max_pv_overuse = 0.0
    max_soc_transition_error = 0.0
    max_soc_bound_violation = 0.0
    max_soc_cycle_error = 0.0
    max_storage_power_overload = 0.0
    max_simultaneous_storage = 0.0
    max_demand_oversupply = 0.0
    for q, scenario in scenarios.items():
        for p in periods:
            for site in d.sites:
                s = site.id
                if pyo.value(installed(s, p)) < 0.5:
                    continue
                capacity = pyo.value(sum(active(s, o, p) * opts[o].ports * opts[o].charger_kw
                                         for o in site.option_ids))
                connection = pyo.value(sum(active(s, o, p) * opts[o].connection_kw
                                           for o in site.option_ids))
                pv_capacity = pyo.value(solar(s, p))
                battery_capacity = pyo.value(battery(s, p))
                totals = {"served_kwh": 0.0, "grid_kwh": 0.0, "pv_used_kwh": 0.0,
                          "pv_available_kwh": 0.0, "battery_charge_kwh": 0.0,
                          "battery_discharge_kwh": 0.0}
                peak_grid = 0.0
                peak_station = 0.0
                for h in hours:
                    load = pyo.value(station_load(s, p, q, h))
                    draw = pyo.value(m.Draw[s, p, q, h])
                    pv_used = pyo.value(m.PVUsed[s, p, q, h])
                    charge = pyo.value(m.Charge[s, p, q, h])
                    discharge = pyo.value(m.Discharge[s, p, q, h])
                    soc_now = pyo.value(m.SOC[s, p, q, h])
                    soc_next = pyo.value(m.SOC[s, p, q, h + 1])
                    pv_available = pv_capacity * par.pv_hourly_factor[h] * scenario.pv_multiplier
                    lhs, rhs = draw + pv_used + discharge, load + charge
                    error = abs(lhs - rhs)
                    max_balance_error = max(max_balance_error, error)
                    max_relative_balance_error = max(max_relative_balance_error,
                                                     error / max(1, lhs, rhs))
                    max_connection_overload = max(max_connection_overload, draw - connection)
                    max_equipment_overload = max(max_equipment_overload, load - capacity)
                    max_pv_overuse = max(max_pv_overuse, pv_used - pv_available)
                    max_soc_transition_error = max(max_soc_transition_error,
                                                   abs(soc_next - soc_now - par.storage_efficiency * charge
                                                       + discharge / par.storage_efficiency))
                    max_soc_bound_violation = max(max_soc_bound_violation, -soc_now,
                                                  soc_now - battery_capacity)
                    max_storage_power_overload = max(max_storage_power_overload,
                                                     charge - battery_capacity / par.storage_max_hours,
                                                     discharge - battery_capacity / par.storage_max_hours)
                    max_simultaneous_storage = max(max_simultaneous_storage, min(charge, discharge))
                    for key, value in (("served_kwh", load), ("grid_kwh", draw),
                                       ("pv_used_kwh", pv_used), ("pv_available_kwh", pv_available),
                                       ("battery_charge_kwh", charge), ("battery_discharge_kwh", discharge)):
                        totals[key] += value
                    peak_grid = max(peak_grid, draw)
                    peak_station = max(peak_station, load)
                energy_audit_rows_total += 1
                max_soc_bound_violation = max(max_soc_bound_violation,
                                              -pyo.value(m.SOC[s, p, q, 24]),
                                              pyo.value(m.SOC[s, p, q, 24]) - battery_capacity)
                max_soc_cycle_error = max(max_soc_cycle_error,
                                          abs(pyo.value(m.SOC[s, p, q, 24])
                                              - pyo.value(m.SOC[s, p, q, 0])))
                if len(energy_audit) < MAX_ENERGY_AUDIT_ROWS:
                    energy_audit.append({"scenario_id": q, "year": par.years[p], "site_id": s,
                                         **{key: round(value, 4) for key, value in totals.items()},
                                         "peak_grid_kw": round(peak_grid, 4),
                                         "peak_station_kw": round(peak_station, 4),
                                         "battery_soc_start_kwh": round(pyo.value(m.SOC[s, p, q, 0]), 4),
                                         "battery_soc_end_kwh": round(pyo.value(m.SOC[s, p, q, 24]), 4)})
            for node in d.grid_nodes:
                for h in hours:
                    used = sum(pyo.value(m.Draw[s, p, q, h]) for s in node_sites[node.id])
                    available = node.headroom_kw[h] + pyo.value(upgraded(node.id, p)) * node.upgrade_kw
                    max_node_overload = max(max_node_overload, used - available)
            for zone in d.zones:
                for h in hours:
                    assigned = sum(pyo.value(m.X[z, s, p, q, h]) for z, s in edge_by_zone[zone.id])
                    demand = zone.hourly_kwh[h] * scenario.demand_multiplier[p]
                    max_demand_oversupply = max(max_demand_oversupply, assigned - demand)
    verification = {
        "max_hourly_energy_balance_error_kwh": round(max_balance_error, 8),
        "max_relative_energy_balance_error": round(max_relative_balance_error, 10),
        "max_grid_node_overload_kw": round(max(0, max_node_overload), 8),
        "max_station_connection_overload_kw": round(max(0, max_connection_overload), 8),
        "max_station_equipment_overload_kw": round(max(0, max_equipment_overload), 8),
        "max_pv_overuse_kw": round(max(0, max_pv_overuse), 8),
        "max_soc_transition_error_kwh": round(max_soc_transition_error, 8),
        "max_soc_bound_violation_kwh": round(max(0, max_soc_bound_violation), 8),
        "max_soc_cycle_error_kwh": round(max_soc_cycle_error, 8),
        "max_storage_power_overload_kw": round(max(0, max_storage_power_overload), 8),
        "max_simultaneous_storage_kw": round(max(0, max_simultaneous_storage), 8),
        "max_demand_oversupply_kwh": round(max(0, max_demand_oversupply), 8),
        "max_budget_overrun_rub": round(max_budget_overrun, 8),
        "energy_audit_rows_total": energy_audit_rows_total,
        "energy_audit_truncated": energy_audit_rows_total > len(energy_audit),
    }
    verification["passed"] = (max_relative_balance_error <= 1e-6
                              and max_node_overload <= 1e-6
                              and max_connection_overload <= 1e-6
                              and max_equipment_overload <= 1e-6
                              and max_pv_overuse <= 1e-6
                              and max_soc_transition_error <= 1e-6
                              and max_soc_bound_violation <= 1e-6
                              and max_soc_cycle_error <= 1e-6
                              and max_storage_power_overload <= 1e-6
                              and max_simultaneous_storage <= 1e-6
                              and max_demand_oversupply <= 1e-6
                              and max_budget_overrun <= 1e-4)
    if not verification["passed"]:
        return SolveResult("error", None, None, [], [], [], [], {}, {}, {},
                           "solver returned a plan violating physical or budget checks",
                           verification=verification)
    return SolveResult("optimal" if term == "optimal" else "feasible", round(primary_objective, 4), gap,
                       selected, upgrades, batteries, pv, served_out, unmet, cash_out,
                       risk_metrics=risk_metrics, investment_rub_by_year=investment_by_year,
                       energy_audit=energy_audit, verification=verification)
