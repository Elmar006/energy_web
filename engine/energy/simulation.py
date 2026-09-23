"""Independent event simulation of public charger arrivals and queues."""
from __future__ import annotations

from collections import defaultdict
from statistics import mean

import numpy as np
import simpy

from .contracts import PlanningInput


def simulate(spec: PlanningInput, selected: list[dict], *, year: int, scenario_id: str,
             seed: int = 1, grid_upgrades: list[dict] | None = None) -> dict:
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
    selected = {x["site_id"]: options[x["option_id"]] for x in selected if x["year"] <= year}
    upgraded_nodes = {x["grid_node_id"] for x in (grid_upgrades or []) if x["year"] <= year}
    travel = {(e.zone_id, e.site_id): e.minutes for e in spec.travel_edges}
    node_ports = defaultdict(int)
    for sid, option in selected.items():
        node_ports[sites[sid].grid_node_id] += option.ports
    env = simpy.Environment()
    resources = {sid: simpy.Resource(env, capacity=o.ports) for sid, o in selected.items()}
    rng = np.random.default_rng(seed)
    waits = []
    served = defaultdict(int)
    refused = defaultdict(int)
    energy = defaultdict(float)
    partial_energy = defaultdict(float)
    arrivals = defaultdict(int)
    last_completion = 0.0
    horizon_minutes = 24 * 60

    def vehicle(zone, arrived, requested):
        nonlocal last_completion
        yield env.timeout(max(0, arrived - env.now))
        arrivals[zone.id] += 1
        h = min(int(env.now // 60), 23)
        eligible = []
        for sid, option in selected.items():
            mins = travel.get((zone.id, sid))
            if mins is None or mins > zone.max_travel_minutes or zone.group not in option.allowed_groups:
                continue
            node = nodes[sites[sid].grid_node_id]
            # This conservative guaranteed-power bound cannot exceed the grid
            # limit even when every charger on the node is simultaneously busy.
            headroom = node.headroom_kw[h] + (node.upgrade_kw if node.id in upgraded_nodes else 0)
            power = min(option.charger_kw, option.connection_kw / option.ports,
                        headroom / max(1, node_ports[node.id]))
            if power <= 0:
                continue
            r = resources[sid]
            estimate = len(r.queue) * requested / power * 60 / option.ports
            eligible.append((mins + estimate, sid, power, mins))
        if not eligible:
            refused[zone.id] += 1
            return
        _, sid, power, travel_mins = min(eligible)
        yield env.timeout(travel_mins)
        if env.now >= horizon_minutes:
            refused[zone.id] += 1
            return
        station = resources[sid]
        queued_at = env.now
        with station.request() as req:
            response = yield req | env.timeout(min(45, horizon_minutes - env.now))
            if req not in response or env.now >= horizon_minutes:
                refused[zone.id] += 1
                return
            waits.append(env.now - queued_at)
            # Re-evaluate node headroom at start of charge.
            hour = min(int(env.now // 60), 23)
            node = nodes[sites[sid].grid_node_id]
            option = selected[sid]
            headroom = node.headroom_kw[hour] + (node.upgrade_kw if node.id in upgraded_nodes else 0)
            power = min(option.charger_kw, option.connection_kw / option.ports,
                        headroom / max(1, node_ports[node.id]))
            if power <= 0:
                refused[zone.id] += 1
                return
            remaining = requested
            delivered = 0.0
            # Re-evaluate the guaranteed per-port power at hour boundaries.
            # The bound is deliberately conservative: even with every port busy,
            # aggregate draw cannot exceed the node headroom or station contract.
            while remaining > 1e-9:
                if env.now >= horizon_minutes:
                    refused[zone.id] += 1
                    partial_energy[sid] += delivered
                    return
                hour = min(int(env.now // 60), 23)
                headroom = node.headroom_kw[hour] + (node.upgrade_kw if node.id in upgraded_nodes else 0)
                power = min(option.charger_kw, option.connection_kw / option.ports,
                            headroom / max(1, node_ports[node.id]))
                if power <= 0:
                    next_hour = (int(env.now // 60) + 1) * 60
                    if next_hour >= 24 * 60:
                        refused[zone.id] += 1
                        partial_energy[sid] += delivered
                        return
                    yield env.timeout(next_hour - env.now)
                    continue
                minutes_to_boundary = (int(env.now // 60) + 1) * 60 - env.now
                minutes = min(remaining / power * 60, minutes_to_boundary)
                yield env.timeout(minutes)
                portion = power * minutes / 60
                remaining -= portion
                delivered += portion
            served[zone.id] += 1
            energy[sid] += delivered
            last_completion = max(last_completion, env.now)

    for zone in spec.zones:
        for h, hourly_kwh in enumerate(zone.hourly_kwh):
            lam = hourly_kwh * scenario.demand_multiplier[period] / zone.mean_session_kwh
            for _ in range(rng.poisson(lam)):
                arrival = h * 60 + rng.uniform(0, 60)
                requested = max(1, rng.normal(zone.mean_session_kwh, zone.mean_session_kwh * 0.15))
                env.process(vehicle(zone, arrival, requested))
    env.run()
    total_arrivals = sum(arrivals.values())
    return {
        "year": year, "scenario_id": scenario_id, "seed": seed,
        "arrivals": total_arrivals, "served_sessions": sum(served.values()),
        "refused_sessions": sum(refused.values()),
        "mean_wait_minutes": round(mean(waits), 3) if waits else None,
        "p95_wait_minutes": round(float(np.percentile(waits, 95)), 3) if waits else None,
        "energy_kwh": round(sum(energy.values()) + sum(partial_energy.values()), 3),
        "partial_energy_kwh": round(sum(partial_energy.values()), 3),
        "last_completion_minute": round(last_completion, 3) if last_completion else None,
        "served_by_zone": dict(served), "refused_by_zone": dict(refused),
        "energy_by_site_kwh": {k: round(energy[k] + partial_energy[k], 3)
                               for k in sorted(energy.keys() | partial_energy.keys())},
        "assumptions": ["Poisson arrivals", "45-minute patience", "sessions unfinished at the 24-hour horizon are refused", "partial delivered energy is reported", "conservative guaranteed charging power", "grid upgrades included", "storage and solar dispatch are not simulated"],
    }
