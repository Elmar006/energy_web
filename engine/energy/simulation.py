"""Independent event simulation of arrivals, queues and causal energy dispatch."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from statistics import mean

import numpy as np
import simpy

from .contracts import PlanningInput
from .dispatch import SiteSupply, dispatch_minute

ENERGY_QUANTILE_PROBABILITIES = np.linspace(0, 1, 101)
FLOW_KEYS = ("load_kwh", "grid_kwh", "pv_used_kwh", "pv_curtailed_kwh",
             "battery_charge_kwh", "battery_discharge_kwh")


def _flow_totals() -> dict[str, float]:
    return {key: 0.0 for key in FLOW_KEYS}


@dataclass
class _Session:
    zone_id: str
    remaining_kwh: float
    done: simpy.Event
    delivered_kwh: float = 0.0


def simulate(spec: PlanningInput, selected: list[dict], *, year: int, scenario_id: str,
             seed: int = 1, grid_upgrades: list[dict] | None = None,
             battery: list[dict] | None = None, solar: list[dict] | None = None) -> dict:
    params = spec.parameters
    if year not in params.years:
        raise ValueError("unknown planning year")
    scenario = next((s for s in spec.scenarios if s.id == scenario_id), None)
    if scenario is None:
        raise ValueError("unknown scenario")
    period = params.years.index(year)
    sites = {s.id: s for s in spec.sites}
    options = {o.id: o for o in spec.options}
    nodes = {n.id: n for n in spec.grid_nodes}
    active = {x["site_id"]: options[x["option_id"]] for x in selected if x["year"] <= year}
    upgraded_nodes = {x["grid_node_id"] for x in (grid_upgrades or [])
                      if x.get("commissioned_year", x["year"]) <= year}
    travel = {(e.zone_id, e.site_id): e.minutes for e in spec.travel_edges}
    supply = {
        sid: SiteSupply(
            node_id=sites[sid].grid_node_id, ports=option.ports,
            charger_kw=option.charger_kw, connection_kw=option.connection_kw,
            battery_kwh=sum(x["kwh"] for x in (battery or [])
                            if x["site_id"] == sid and x["year"] <= year),
            pv_kw=sum(x["kw"] for x in (solar or [])
                      if x["site_id"] == sid and x["year"] <= year),
        ) for sid, option in active.items()
    }
    node_ports = defaultdict(int)
    for station in supply.values():
        node_ports[station.node_id] += station.ports
    env = simpy.Environment()
    resources = {sid: simpy.Resource(env, capacity=o.ports) for sid, o in active.items()}
    rng = np.random.default_rng(seed)
    waits = []
    served = defaultdict(int)
    refused = defaultdict(int)
    arrivals = defaultdict(int)
    arrivals_by_hour = [0] * 24
    arrivals_by_day_hour = [[0] * 24 for _ in range(params.simulation_days)]
    requested_energy_kwh = 0.0
    partial_energy = defaultdict(float)
    energy = defaultdict(float)
    in_charge: dict[str, list[_Session]] = {sid: [] for sid in supply}
    totals = {sid: _flow_totals() for sid in supply}
    max_balance_error = 0.0
    max_node_overload = 0.0
    max_connection_overload = 0.0
    max_equipment_overload = 0.0
    max_soc_violation = 0.0
    max_simultaneous_storage = 0.0
    last_completion = 0.0
    horizon_minutes = params.simulation_days * 24 * 60
    day_dispatch = []

    def headroom(node_id: str, hour: int) -> float:
        node = nodes[node_id]
        return node.headroom_kw[hour] + (node.upgrade_kw if node_id in upgraded_nodes else 0)

    # Use only the known representative demand profile to schedule grid
    # charging. Otherwise idle batteries would buy power every night, even
    # after the final demand of a simulated day, and falsely depress NPV.
    forecast = {sid: [0.0] * 24 for sid in supply}
    for zone in spec.zones:
        eligible = sorted((minutes, sid) for (zone_id, sid), minutes in travel.items()
                          if zone_id == zone.id and sid in active
                          and minutes <= zone.max_travel_minutes
                          and zone.group in active[sid].allowed_groups)
        if eligible:
            sid = eligible[0][1]
            for hour, value in enumerate(zone.hourly_kwh):
                forecast[sid][hour] += value * scenario.demand_multiplier[period]
    grid_charge_hours = {sid: [False] * (24 * params.simulation_days) for sid in supply}
    for sid, station in supply.items():
        needed_later = False
        for absolute_hour in reversed(range(24 * params.simulation_days)):
            hour = absolute_hour % 24
            direct_grid = min(station.connection_kw,
                              headroom(station.node_id, hour) * station.ports
                              / node_ports[station.node_id])
            direct_pv = station.pv_kw * params.pv_hourly_factor[hour] * scenario.pv_multiplier
            direct = min(station.ports * station.charger_kw, direct_grid + direct_pv)
            needed_later = needed_later or forecast[sid][hour] > direct + 1e-9
            grid_charge_hours[sid][absolute_hour] = needed_later

    def vehicle(zone, arrived: float, requested: float):
        nonlocal last_completion, requested_energy_kwh
        yield env.timeout(max(0, arrived - env.now))
        arrivals[zone.id] += 1
        arrival_day = min(int(env.now // 1440), params.simulation_days - 1)
        hour = int(env.now // 60) % 24
        arrivals_by_hour[hour] += 1
        arrivals_by_day_hour[arrival_day][hour] += 1
        requested_energy_kwh += requested
        eligible = []
        for sid, option in active.items():
            minutes = travel.get((zone.id, sid))
            if minutes is None or minutes > zone.max_travel_minutes or zone.group not in option.allowed_groups:
                continue
            station = supply[sid]
            pv = station.pv_kw * params.pv_hourly_factor[hour] * scenario.pv_multiplier
            storage = min(station.battery_kwh / params.storage_max_hours,
                          station.soc_kwh * params.storage_efficiency * 60)
            grid = min(option.connection_kw / option.ports,
                       headroom(station.node_id, hour) / node_ports[station.node_id])
            estimated_power = min(option.charger_kw, grid + (pv + storage) / option.ports)
            if estimated_power <= 1e-9:
                continue
            resource = resources[sid]
            queue_delay = len(resource.queue) * requested / estimated_power * 60 / option.ports
            eligible.append((minutes + queue_delay, sid, minutes))
        if not eligible:
            refused[zone.id] += 1
            return
        _, sid, travel_minutes = min(eligible)
        yield env.timeout(travel_minutes)
        if env.now >= horizon_minutes:
            refused[zone.id] += 1
            return
        station = resources[sid]
        queued_at = env.now
        with station.request() as request:
            response = yield request | env.timeout(min(45, horizon_minutes - env.now))
            if request not in response or env.now >= horizon_minutes:
                refused[zone.id] += 1
                return
            waits.append(env.now - queued_at)
            session = _Session(zone.id, requested, env.event())
            in_charge[sid].append(session)
            completed = yield session.done
            if completed:
                served[zone.id] += 1
                energy[sid] += session.delivered_kwh
                last_completion = max(last_completion, env.now)
            else:
                refused[zone.id] += 1
                partial_energy[sid] += session.delivered_kwh

    def dispatcher():
        nonlocal max_balance_error, max_node_overload, max_connection_overload
        nonlocal max_equipment_overload, max_soc_violation, max_simultaneous_storage
        day_start_soc = {sid: 0.0 for sid in supply}
        day_totals = {sid: _flow_totals() for sid in supply}
        for minute in range(horizon_minutes):
            if env.now < minute:
                yield env.timeout(minute - env.now)
            hour = (minute // 60) % 24
            absolute_hour = minute // 60
            demand = {sid: sum(min(active[sid].charger_kw, session.remaining_kwh * 60)
                               for session in sessions)
                      for sid, sessions in in_charge.items()}
            node_limits = {node_id: headroom(node_id, hour) for node_id in nodes}
            flows = dispatch_minute(supply, demand, node_limits,
                                    pv_factor=params.pv_hourly_factor[hour] * scenario.pv_multiplier,
                                    efficiency=params.storage_efficiency,
                                    storage_max_hours=params.storage_max_hours,
                                    grid_charge_allowed={sid: grid_charge_hours[sid][absolute_hour]
                                                         for sid in supply})
            for node_id, limit in node_limits.items():
                draw = sum(flow.grid_kw for sid, flow in flows.items()
                           if supply[sid].node_id == node_id)
                max_node_overload = max(max_node_overload, draw - limit)
            for sid, flow in flows.items():
                station = supply[sid]
                max_balance_error = max(max_balance_error,
                    abs(flow.grid_kw + flow.pv_kw + flow.discharge_kw
                        - flow.load_kw - flow.charge_kw) / 60)
                max_connection_overload = max(max_connection_overload,
                                              flow.grid_kw - station.connection_kw)
                max_equipment_overload = max(max_equipment_overload,
                                             flow.load_kw - station.ports * station.charger_kw)
                max_soc_violation = max(max_soc_violation, -flow.soc_kwh,
                                        flow.soc_kwh - station.battery_kwh)
                max_simultaneous_storage = max(max_simultaneous_storage,
                                               min(flow.charge_kw, flow.discharge_kw))
                for key, power in (("load_kwh", flow.load_kw), ("grid_kwh", flow.grid_kw),
                                   ("pv_used_kwh", flow.pv_kw),
                                   ("pv_curtailed_kwh", flow.pv_curtailed_kw),
                                   ("battery_charge_kwh", flow.charge_kw),
                                   ("battery_discharge_kwh", flow.discharge_kw)):
                    totals[sid][key] += power / 60
                    day_totals[sid][key] += power / 60
                remaining_power = flow.load_kw
                for session in in_charge[sid]:
                    delivered = min(session.remaining_kwh * 60, active[sid].charger_kw,
                                    remaining_power) / 60
                    session.remaining_kwh = max(0.0, session.remaining_kwh - delivered)
                    session.delivered_kwh += delivered
                    remaining_power -= delivered * 60
            yield env.timeout(1)
            for sid, sessions in in_charge.items():
                for session in sessions[:]:
                    if session.remaining_kwh <= 1e-9:
                        sessions.remove(session)
                        session.done.succeed(True)
            if (minute + 1) % 1440 == 0:
                day = minute // 1440
                per_site = [{"site_id": sid,
                             **{key: round(value, 4) for key, value in day_totals[sid].items()},
                             "battery_soc_start_kwh": round(day_start_soc[sid], 4),
                             "battery_soc_end_kwh": round(supply[sid].soc_kwh, 4)}
                            for sid in sorted(supply)]
                day_dispatch.append({"day_index": day, "arrivals": sum(arrivals_by_day_hour[day]),
                                     "dispatch_by_site": per_site,
                                     "charging_sessions_at_boundary": sum(len(s) for s in in_charge.values()),
                                     "queued_sessions_at_boundary": sum(len(r.queue) for r in resources.values())})
                day_start_soc = {sid: supply[sid].soc_kwh for sid in supply}
                day_totals = {sid: _flow_totals() for sid in supply}
        for sessions in in_charge.values():
            for session in sessions:
                session.done.succeed(False)
            sessions.clear()

    for day in range(params.simulation_days):
        for zone in spec.zones:
            for hour, hourly_kwh in enumerate(zone.hourly_kwh):
                profile = zone.arrival_profile
                baseline = (profile.hourly_sessions[hour] if profile is not None
                            else hourly_kwh / zone.mean_session_kwh)
                expected = baseline * scenario.demand_multiplier[period]
                if (profile is not None and profile.observation_days >= 7 and profile.sample_count >= 30
                        and baseline > 0 and profile.hourly_count_variance[hour] > baseline):
                    # Preserve measured overdispersion; scaling the mean keeps the
                    # fitted negative-binomial dispersion constant across scenarios.
                    shape = baseline * baseline / (profile.hourly_count_variance[hour] - baseline)
                    count = rng.negative_binomial(shape, shape / (shape + expected)) if expected > 0 else 0
                else:
                    count = rng.poisson(expected)
                for _ in range(count):
                    arrival = day * 1440 + hour * 60 + rng.uniform(0, 60)
                    if profile is not None:
                        requested = float(np.interp(rng.random(), ENERGY_QUANTILE_PROBABILITIES,
                                                    profile.energy_quantiles_kwh))
                    else:
                        # Positive parametric fallback with exactly the stated mean.
                        requested = float(rng.gamma(1 / 0.15**2, zone.mean_session_kwh * 0.15**2))
                    env.process(vehicle(zone, arrival, requested))
    env.process(dispatcher())
    env.run()
    total_energy = sum(energy.values()) + sum(partial_energy.values())
    dispatched_energy = sum(row["load_kwh"] for row in totals.values())
    energy_mismatch = abs(total_energy - dispatched_energy)
    storage_balance_error = max((abs(supply[sid].soc_kwh -
        params.storage_efficiency * totals[sid]["battery_charge_kwh"] +
        totals[sid]["battery_discharge_kwh"] / params.storage_efficiency)
        for sid in supply), default=0.0)
    audit = {
        "max_energy_balance_error_kwh_per_minute": round(max_balance_error, 9),
        "max_grid_node_overload_kw": round(max(0.0, max_node_overload), 9),
        "max_station_connection_overload_kw": round(max(0.0, max_connection_overload), 9),
        "max_equipment_overload_kw": round(max(0.0, max_equipment_overload), 9),
        "max_storage_soc_violation_kwh": round(max(0.0, max_soc_violation), 9),
        "max_simultaneous_storage_kw": round(max(0.0, max_simultaneous_storage), 9),
        "session_dispatch_energy_mismatch_kwh": round(energy_mismatch, 9),
        "storage_energy_balance_error_kwh": round(storage_balance_error, 9),
    }
    audit["passed"] = all(value <= 1e-6 for value in audit.values())
    site_dispatch = [{"site_id": sid, **{key: round(value, 4) for key, value in totals[sid].items()},
                      "battery_soc_start_kwh": 0,
                      "battery_soc_end_kwh": round(supply[sid].soc_kwh, 4)}
                     for sid in sorted(supply)]
    return {
        "year": year, "scenario_id": scenario_id, "seed": seed,
        "simulation_days": params.simulation_days,
        "arrivals": sum(arrivals.values()), "served_sessions": sum(served.values()),
        "refused_sessions": sum(refused.values()),
        "arrivals_by_hour": arrivals_by_hour,
        "arrivals_by_day_hour": arrivals_by_day_hour,
        "day_dispatch": day_dispatch,
        "requested_energy_kwh": round(requested_energy_kwh, 3),
        "unserved_energy_kwh": round(max(0.0, requested_energy_kwh - total_energy), 3),
        "mean_wait_minutes": round(mean(waits), 3) if waits else None,
        "p95_wait_minutes": round(float(np.percentile(waits, 95)), 3) if waits else None,
        "energy_kwh": round(total_energy, 3),
        "partial_energy_kwh": round(sum(partial_energy.values()), 3),
        "last_completion_minute": round(last_completion, 3) if last_completion else None,
        "served_by_zone": dict(served), "refused_by_zone": dict(refused),
        "energy_by_site_kwh": {sid: round(energy[sid] + partial_energy[sid], 3)
                               for sid in sorted(supply)},
        "dispatch_by_site": site_dispatch, "dispatch_verification": audit,
        "assumptions": ["empirical session starts and energy quantiles where arrival_profile is supplied; otherwise hourly load divided by assumed mean session size",
                        "negative-binomial arrivals for measured overdispersion with at least 7 days and 30 sessions, otherwise Poisson; independent hours",
                        "15% coefficient-of-variation gamma energy only for zones without session observations",
                        "observed sessions omit unserved latent demand", "45-minute patience",
                        "sessions and queues continue across midnight; only those unfinished at the final horizon are refused",
                        "one-minute causal power dispatch; zero initial battery charge",
                        "PV serves vehicles before charging batteries; grid fills demand before batteries discharge",
                        "spare PV and then spare grid charge batteries; grid sharing is max-min fair",
                        "grid charging of storage is enabled only before forecast hours with direct-supply shortfall",
                        "the same representative-day demand profile repeats independently each day; no day-of-week, seasonal or AC power-flow validation"],
    }
