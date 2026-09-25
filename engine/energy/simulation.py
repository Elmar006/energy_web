"""Independent event simulation of arrivals, queues and causal energy dispatch."""
from __future__ import annotations

from collections import defaultdict
from bisect import bisect_right
from dataclasses import dataclass
from datetime import timezone
import hashlib
import json
from statistics import mean

import numpy as np
import simpy

from .contracts import OperationalOutage, PlanningInput
from .dated import DatedHorizon
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
    max_vehicle_kw: float | None = None
    deadline_minute: float | None = None
    delivered_kwh: float = 0.0


def simulate(spec: PlanningInput, selected: list[dict], *, year: int, scenario_id: str,
              seed: int = 1, grid_upgrades: list[dict] | None = None,
              battery: list[dict] | None = None, solar: list[dict] | None = None,
              outages: list[OperationalOutage | dict] | None = None,
              max_reroutes: int = 1) -> dict:
    params = spec.parameters
    if year not in params.years:
        raise ValueError("unknown planning year")
    scenario = next((s for s in spec.scenarios if s.id == scenario_id), None)
    if scenario is None:
        raise ValueError("unknown scenario")
    if not 0 <= max_reroutes <= 3:
        raise ValueError("max_reroutes must be between zero and three")
    period = params.years.index(year)
    horizon = DatedHorizon.from_calendar(spec.service_calendar) if spec.service_calendar else None
    day_count = len(spec.service_calendar.covered_dates) if horizon else params.simulation_days
    day_boundaries = (horizon.day_boundaries_minutes if horizon else
                      tuple(day * 1440 for day in range(day_count + 1)))
    hour_count = len(horizon.slot_starts_utc) if horizon else 24 * day_count
    request_zone_ids = set(spec.service_calendar.request_zone_ids) if horizon else set()

    def local_hour(minute: float) -> int:
        slot = min(int(minute // 60), hour_count - 1)
        return horizon.local_hours[slot] if horizon else slot % 24

    def local_day(minute: float) -> int:
        return min(day_count - 1, bisect_right(day_boundaries, minute) - 1)
    sites = {s.id: s for s in spec.sites}
    options = {o.id: o for o in spec.options}
    nodes = {n.id: n for n in spec.grid_nodes}
    active = {x["site_id"]: options[x["option_id"]] for x in selected if x["year"] <= year}
    upgraded_nodes = {x["grid_node_id"] for x in (grid_upgrades or [])
                      if x.get("commissioned_year", x["year"]) <= year}
    travel = {(e.zone_id, e.site_id): e.minutes for e in spec.travel_edges}
    site_travel = {(e.from_site_id, e.to_site_id): e.minutes
                   for e in spec.site_travel_edges}
    configured_outages = (spec.operational_outages if outages is None else
                          [OperationalOutage.model_validate(item) for item in outages])
    if any(item.site_id not in sites for item in configured_outages):
        raise ValueError("outage references unknown site")
    outage_windows = defaultdict(list)
    for item in configured_outages:
        outage_windows[item.site_id].append((item.start_minute, item.repair_minute))
    for windows in outage_windows.values():
        windows.sort()
        if any(right[0] < left[1] for left, right in zip(windows, windows[1:])):
            raise ValueError("outage windows overlap at one site")

    def site_down(site_id: str, minute: float) -> bool:
        return any(start <= minute < repair for start, repair in outage_windows[site_id])
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
    arrivals_by_day_hour = [[0] * 24 for _ in range(day_count)]
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
    rerouted_arrivals = 0
    rerouted_served = 0
    outage_station_minutes = defaultdict(int)
    horizon_minutes = day_boundaries[-1]
    day_dispatch = []

    def headroom(node_id: str, hour: int) -> float:
        node = nodes[node_id]
        return node.headroom_kw[hour] + (node.upgrade_kw if node_id in upgraded_nodes else 0)

    # Use only the known representative demand profile to schedule grid
    # charging. Otherwise idle batteries would buy power every night, even
    # after the final demand of a simulated day, and falsely depress NPV.
    forecast = {sid: [0.0] * hour_count for sid in supply}
    for zone in spec.zones:
        if zone.id in request_zone_ids:
            continue
        eligible = sorted((minutes, sid) for (zone_id, sid), minutes in travel.items()
                          if zone_id == zone.id and sid in active
                          and minutes <= zone.max_travel_minutes
                          and zone.group in active[sid].allowed_groups)
        if eligible:
            sid = eligible[0][1]
            for absolute_hour in range(hour_count):
                hour = local_hour(absolute_hour * 60)
                forecast[sid][absolute_hour] += (zone.hourly_kwh[hour] *
                                                  scenario.demand_multiplier[period])
    if horizon:
        for request in spec.charging_requests:
            zone = next(item for item in spec.zones if item.id == request.zone_id)
            eligible = sorted((minutes, sid) for (zone_id, sid), minutes in travel.items()
                              if zone_id == zone.id and sid in active
                              and minutes <= zone.max_travel_minutes
                              and zone.group in active[sid].allowed_groups)
            if not eligible:
                continue
            travel_minutes, sid = eligible[0]
            overlaps = [horizon.overlap_hours(request, h, travel_minutes)
                        for h in range(hour_count)]
            total_overlap = sum(overlaps)
            if total_overlap:
                weighted = (request.energy_from_charger_kwh * request.population_weight *
                            scenario.demand_multiplier[period])
                for h, overlap in enumerate(overlaps):
                    forecast[sid][h] += weighted * overlap / total_overlap
    grid_charge_hours = {sid: [False] * hour_count for sid in supply}
    for sid, station in supply.items():
        needed_later = False
        for absolute_hour in reversed(range(hour_count)):
            hour = local_hour(absolute_hour * 60)
            direct_grid = min(station.connection_kw,
                              headroom(station.node_id, hour) * station.ports
                              / node_ports[station.node_id])
            direct_pv = station.pv_kw * params.pv_hourly_factor[hour] * scenario.pv_multiplier
            direct = min(station.ports * station.charger_kw, direct_grid + direct_pv)
            needed_later = needed_later or forecast[sid][absolute_hour] > direct + 1e-9
            grid_charge_hours[sid][absolute_hour] = needed_later

    def vehicle(zone, arrived: float, requested: float, *,
                deadline_minute: float | None = None,
                max_vehicle_kw: float | None = None):
        nonlocal last_completion, requested_energy_kwh
        yield env.timeout(max(0, arrived - env.now))
        arrivals[zone.id] += 1
        arrival_day = local_day(env.now)
        hour = local_hour(env.now)
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
            estimated_power = min(option.charger_kw, grid + (pv + storage) / option.ports,
                                  max_vehicle_kw or option.charger_kw)
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
        if env.now >= horizon_minutes or (deadline_minute is not None and env.now >= deadline_minute):
            refused[zone.id] += 1
            return
        station = resources[sid]
        queued_at = env.now
        with station.request() as request:
            patience = min(45, horizon_minutes - env.now,
                           deadline_minute - env.now if deadline_minute is not None else 45)
            response = yield request | env.timeout(patience)
            if (request not in response or env.now >= horizon_minutes or
                    (deadline_minute is not None and env.now >= deadline_minute)):
                refused[zone.id] += 1
                return
            waits.append(env.now - queued_at)
            session = _Session(zone.id, requested, env.event(), max_vehicle_kw,
                               deadline_minute)
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
            hour = local_hour(minute)
            absolute_hour = minute // 60
            demand = {sid: sum(min(active[sid].charger_kw,
                                   session.max_vehicle_kw or active[sid].charger_kw,
                                   session.remaining_kwh * 60,
                                   (session.max_vehicle_kw or active[sid].charger_kw) *
                                   min(1, max(0, session.deadline_minute - minute))
                                   if session.deadline_minute is not None else float("inf"))
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
                                    session.max_vehicle_kw or active[sid].charger_kw,
                                    (session.max_vehicle_kw or active[sid].charger_kw) *
                                    min(1, max(0, session.deadline_minute - minute))
                                    if session.deadline_minute is not None else float("inf"),
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
                    elif session.deadline_minute is not None and env.now >= session.deadline_minute:
                        sessions.remove(session)
                        session.done.succeed(False)
            if minute + 1 in day_boundaries[1:]:
                day = day_boundaries.index(minute + 1) - 1
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

    external_arrivals = []
    for absolute_hour in range(hour_count):
        hour = local_hour(absolute_hour * 60)
        for zone in spec.zones:
            if zone.id in request_zone_ids:
                continue
            hourly_kwh = zone.hourly_kwh[hour]
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
                arrival = absolute_hour * 60 + rng.uniform(0, 60)
                if profile is not None:
                    requested = float(np.interp(rng.random(), ENERGY_QUANTILE_PROBABILITIES,
                                                profile.energy_quantiles_kwh))
                else:
                    # Positive parametric fallback with exactly the stated mean.
                    requested = float(rng.gamma(1 / 0.15**2, zone.mean_session_kwh * 0.15**2))
                external_arrivals.append((zone.id, round(arrival, 6), round(requested, 6), None))
                env.process(vehicle(zone, arrival, requested))
    if horizon:
        zones = {zone.id: zone for zone in spec.zones}
        for request in spec.charging_requests:
            expected_count = request.population_weight * scenario.demand_multiplier[period]
            whole = int(expected_count)
            count = whole + int(rng.random() < expected_count - whole)
            arrival = ((request.arrival_at.astimezone(timezone.utc) - horizon.start_utc)
                       .total_seconds() / 60)
            deadline = ((request.deadline_at.astimezone(timezone.utc) - horizon.start_utc)
                        .total_seconds() / 60)
            for _ in range(count):
                external_arrivals.append((request.zone_id, round(arrival, 6),
                                          round(request.energy_from_charger_kwh, 6),
                                          round(deadline, 6)))
                env.process(vehicle(zones[request.zone_id], arrival,
                                    request.energy_from_charger_kwh,
                                    deadline_minute=deadline,
                                    max_vehicle_kw=request.max_vehicle_kw))
    arrival_stream_sha256 = hashlib.sha256(json.dumps(
        sorted(external_arrivals), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
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
        "simulation_days": day_count,
        "demand_basis": "dated_requests" if horizon else "representative_day",
        "calendar_covered_dates": ([day.isoformat() for day in spec.service_calendar.covered_dates]
                                   if horizon else None),
        "arrival_stream_sha256": arrival_stream_sha256,
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
                        ("dated request arrivals/deadlines are replayed; fractional population weights and demand multipliers use seeded stochastic rounding; explicitly marked legacy zones repeat their profile"
                         if horizon else
                         "the same representative-day demand profile repeats independently each day; no day-of-week, seasonal or AC power-flow validation")],
    }
