"""Exact time-indexed charger scheduling for an assigned vehicle fleet."""

from __future__ import annotations

from collections import defaultdict

import pyomo.environ as pyo
from pydantic import BaseModel, Field, model_validator


class FleetBus(BaseModel):
    id: str = Field(min_length=1)
    battery_kwh: float = Field(gt=0)
    initial_kwh: float = Field(ge=0)
    minimum_kwh: float = Field(ge=0)
    end_target_kwh: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def check_energy(self):
        if self.initial_kwh > self.battery_kwh or self.minimum_kwh > self.battery_kwh:
            raise ValueError("bus energy exceeds battery capacity")
        if self.end_target_kwh is not None and self.end_target_kwh > self.battery_kwh:
            raise ValueError("end target exceeds battery capacity")
        return self


class FleetSite(BaseModel):
    id: str = Field(min_length=1)
    ports: int = Field(gt=0)
    charger_kw: float = Field(gt=0)
    grid_kw: float = Field(gt=0)


class FleetTrip(BaseModel):
    id: str = Field(min_length=1)
    bus_id: str
    start_slot: int = Field(ge=0)
    end_slot: int = Field(gt=0)
    energy_kwh: float = Field(gt=0)


class ChargeWindow(BaseModel):
    bus_id: str
    site_id: str
    start_slot: int = Field(ge=0)
    end_slot: int = Field(gt=0)


class FleetInput(BaseModel):
    slot_minutes: int = Field(default=15, gt=0, le=60)
    horizon_slots: int = Field(gt=0, le=192)
    efficiency: float = Field(default=0.95, gt=0, le=1)
    buses: list[FleetBus] = Field(min_length=1)
    sites: list[FleetSite] = Field(min_length=1)
    trips: list[FleetTrip]
    windows: list[ChargeWindow]
    solver_seconds: int = Field(default=30, ge=1, le=3600)

    @model_validator(mode="after")
    def check_schedule(self):
        buses = {bus.id for bus in self.buses}
        sites = {site.id for site in self.sites}
        if len(buses) != len(self.buses) or len(sites) != len(self.sites):
            raise ValueError("bus and site IDs must be unique")
        if len({trip.id for trip in self.trips}) != len(self.trips):
            raise ValueError("trip IDs must be unique")
        busy = set()
        for trip in self.trips:
            if trip.bus_id not in buses or trip.end_slot > self.horizon_slots or trip.start_slot >= trip.end_slot:
                raise ValueError("trip references unknown bus or invalid time")
            for slot in range(trip.start_slot, trip.end_slot):
                pair = (trip.bus_id, slot)
                if pair in busy:
                    raise ValueError("overlapping trips for a bus")
                busy.add(pair)
        access = set()
        for window in self.windows:
            if window.bus_id not in buses or window.site_id not in sites or window.end_slot > self.horizon_slots or window.start_slot >= window.end_slot:
                raise ValueError("window references unknown bus/site or invalid time")
            for slot in range(window.start_slot, window.end_slot):
                pair = (window.bus_id, slot)
                if pair in busy:
                    raise ValueError("charging window overlaps a trip")
                if pair in access:
                    raise ValueError("multiple charging sites for one bus and slot")
                access.add(pair)
        return self


def schedule_fleet(spec: FleetInput) -> dict:
    buses = {bus.id: bus for bus in spec.buses}
    sites = {site.id: site for site in spec.sites}
    horizon = range(spec.horizon_slots)
    available = {(window.bus_id, window.site_id, slot)
                 for window in spec.windows for slot in range(window.start_slot, window.end_slot)}
    by_site_slot = defaultdict(list)
    by_bus_slot = defaultdict(list)
    for bus_id, site_id, slot in available:
        by_site_slot[site_id, slot].append((bus_id, site_id, slot))
        by_bus_slot[bus_id, slot].append((bus_id, site_id, slot))
    trip_start = defaultdict(float)
    for trip in spec.trips:
        trip_start[trip.bus_id, trip.start_slot] += trip.energy_kwh

    m = pyo.ConcreteModel()
    m.Power = pyo.Var(available, within=pyo.NonNegativeReals)
    m.UsesPort = pyo.Var(available, within=pyo.Binary)
    m.Energy = pyo.Var(buses, range(spec.horizon_slots + 1), within=pyo.NonNegativeReals)
    m.Peak = pyo.Var(within=pyo.NonNegativeReals)
    m.C = pyo.ConstraintList()
    slot_hours = spec.slot_minutes / 60

    for bus in spec.buses:
        m.Energy[bus.id, 0].fix(bus.initial_kwh)
        for slot in horizon:
            charge = sum(m.Power[key] for key in by_bus_slot[bus.id, slot])
            m.C.add(m.Energy[bus.id, slot + 1] == m.Energy[bus.id, slot]
                    + spec.efficiency * charge * slot_hours - trip_start[bus.id, slot])
            m.C.add(m.Energy[bus.id, slot + 1] >= bus.minimum_kwh)
            m.C.add(m.Energy[bus.id, slot + 1] <= bus.battery_kwh)
        m.C.add(m.Energy[bus.id, spec.horizon_slots] >= (bus.end_target_kwh if bus.end_target_kwh is not None else bus.minimum_kwh))
    for key in available:
        _, site_id, _ = key
        m.C.add(m.Power[key] <= sites[site_id].charger_kw * m.UsesPort[key])
    for site in spec.sites:
        for slot in horizon:
            keys = by_site_slot[site.id, slot]
            if not keys:
                continue
            m.C.add(sum(m.UsesPort[key] for key in keys) <= site.ports)
            m.C.add(sum(m.Power[key] for key in keys) <= site.grid_kw)
    for slot in horizon:
        m.C.add(sum(m.Power[key] for key in available if key[2] == slot) <= m.Peak)
    m.Objective = pyo.Objective(expr=m.Peak + 1e-5 * sum(m.Power[key] for key in available), sense=pyo.minimize)

    solver = pyo.SolverFactory("appsi_highs")
    try:
        outcome = solver.solve(m, timelimit=spec.solver_seconds, load_solutions=False)
    except Exception as exc:
        return {"status": "error", "diagnostic": str(exc), "schedule": []}
    term = str(outcome.solver.termination_condition)
    if term != "optimal":
        return {"status": "infeasible" if "infeasible" in term.lower() else "error",
                "diagnostic": term, "schedule": []}
    m.solutions.load_from(outcome)
    schedule = [{"bus_id": bus, "site_id": site, "slot": slot, "kw": round(pyo.value(m.Power[bus, site, slot]), 4)}
                for bus, site, slot in sorted(available)
                if pyo.value(m.Power[bus, site, slot]) > 1e-6]
    return {"status": "optimal", "peak_kw": round(pyo.value(m.Peak), 4), "schedule": schedule,
            "trip_ids_served": [trip.id for trip in spec.trips],
            "end_energy_kwh": {bus: round(pyo.value(m.Energy[bus, spec.horizon_slots]), 4) for bus in buses},
            "assumptions": ["fixed trip-to-bus assignment", "constant charging power within each slot",
                            "trip energy deducted at departure", "no piecewise charging curve"]}
