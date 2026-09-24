"""One-minute, causal dispatch of grid, PV and storage for active chargers.

This is an operational policy, independent of the investment MILP. Battery
state only comes from energy charged in earlier minutes; no representative-day
cyclic state is assumed. Power sharing is max-min fair within each grid node.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SiteSupply:
    node_id: str
    ports: int
    charger_kw: float
    connection_kw: float
    battery_kwh: float = 0
    pv_kw: float = 0
    soc_kwh: float = 0


@dataclass(frozen=True)
class SiteDispatch:
    load_kw: float
    grid_kw: float
    pv_kw: float
    pv_curtailed_kw: float
    charge_kw: float
    discharge_kw: float
    soc_kwh: float


def _fair_share(requests: dict[str, float], capacity: float) -> dict[str, float]:
    """Allocate a common limit without depending on insertion order."""
    if not requests:
        return {}
    remaining = max(0.0, capacity)
    level = 0.0
    count = len(requests)
    for request in sorted(requests.values()):
        required = (request - level) * count
        if remaining < required:
            level += remaining / count
            break
        remaining -= required
        level = request
        count -= 1
        if count == 0:
            break
    return {site_id: min(request, level) for site_id, request in requests.items()}


def dispatch_minute(sites: dict[str, SiteSupply], requested_kw: dict[str, float],
                    node_headroom_kw: dict[str, float], *, pv_factor: float,
                    efficiency: float, storage_max_hours: float,
                    grid_charge_allowed: dict[str, bool] | None = None) -> dict[str, SiteDispatch]:
    """Advance exactly one minute and mutate only the batteries' SoC.

    Load uses PV, then the available grid, then previously stored energy.
    Spare PV and subsequently spare grid can charge storage. A battery cannot
    charge and discharge in the same minute. Station connection limits *grid
    draw*; equipment limits energy delivered to vehicles.
    """
    dt = 1 / 60
    ids = sorted(sites)
    demand = {sid: min(max(0.0, requested_kw.get(sid, 0.0)),
                       sites[sid].ports * sites[sid].charger_kw) for sid in ids}
    pv_available = {sid: max(0.0, sites[sid].pv_kw * pv_factor) for sid in ids}
    pv_load = {sid: min(demand[sid], pv_available[sid]) for sid in ids}
    grid_load = {sid: 0.0 for sid in ids}
    by_node: dict[str, list[str]] = {}
    for sid in ids:
        by_node.setdefault(sites[sid].node_id, []).append(sid)
    for node, members in by_node.items():
        requests = {sid: min(sites[sid].connection_kw, demand[sid] - pv_load[sid])
                    for sid in members}
        grid_load.update(_fair_share(requests, node_headroom_kw[node]))

    discharge = {}
    pv_charge = {}
    grid_charge = {sid: 0.0 for sid in ids}
    for sid in ids:
        site = sites[sid]
        deficit = max(0.0, demand[sid] - pv_load[sid] - grid_load[sid])
        discharge[sid] = min(deficit, site.battery_kwh / storage_max_hours,
                             site.soc_kwh * efficiency / dt)
        if discharge[sid] > 1e-12:
            pv_charge[sid] = 0.0
            continue
        charge_limit = min(site.battery_kwh / storage_max_hours,
                           max(0.0, site.battery_kwh - site.soc_kwh) / (efficiency * dt))
        pv_charge[sid] = min(max(0.0, pv_available[sid] - pv_load[sid]), charge_limit)

    for node, members in by_node.items():
        spare = max(0.0, node_headroom_kw[node] - sum(grid_load[sid] for sid in members))
        requests = {}
        for sid in members:
            site = sites[sid]
            if discharge[sid] > 1e-12 or (grid_charge_allowed is not None
                                          and not grid_charge_allowed.get(sid, False)):
                requests[sid] = 0.0
                continue
            charge_limit = min(site.battery_kwh / storage_max_hours,
                               max(0.0, site.battery_kwh - site.soc_kwh) / (efficiency * dt))
            requests[sid] = min(max(0.0, charge_limit - pv_charge[sid]),
                                max(0.0, site.connection_kw - grid_load[sid]))
        grid_charge.update(_fair_share(requests, spare))

    result = {}
    for sid in ids:
        site = sites[sid]
        charge = pv_charge[sid] + grid_charge[sid]
        next_soc = min(site.battery_kwh, max(0.0, site.soc_kwh
                                             + efficiency * charge * dt
                                             - discharge[sid] / efficiency * dt))
        site.soc_kwh = 0.0 if next_soc < 1e-12 else next_soc
        load = pv_load[sid] + grid_load[sid] + discharge[sid]
        pv_used = pv_load[sid] + pv_charge[sid]
        result[sid] = SiteDispatch(load, grid_load[sid] + grid_charge[sid], pv_used,
                                   pv_available[sid] - pv_used, charge, discharge[sid],
                                   site.soc_kwh)
    return result
