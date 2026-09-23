"""Route reachability with mandatory reserve and station outages.

Positions are distances along an already routed corridor. The input route can
come from OSRM or a verified CSV; this module never assumes Euclidean range.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class CorridorStation(BaseModel):
    id: str = Field(min_length=1)
    km: float = Field(gt=0)
    available: bool = True


class CorridorInput(BaseModel):
    route_km: float = Field(gt=0)
    battery_usable_kwh: float = Field(gt=0)
    initial_soc: float = Field(gt=0, le=1)
    reserve_soc: float = Field(ge=0, lt=1)
    consumption_kwh_per_km: float = Field(gt=0)
    consumption_multiplier: float = Field(default=1, gt=0)
    stations: list[CorridorStation]

    @model_validator(mode="after")
    def check_stations(self):
        if self.initial_soc < self.reserve_soc:
            raise ValueError("initial SoC is below reserve")
        if len({station.id for station in self.stations}) != len(self.stations):
            raise ValueError("station IDs must be unique")
        if any(station.km >= self.route_km for station in self.stations):
            raise ValueError("stations must be inside the route")
        if len({station.km for station in self.stations}) != len(self.stations):
            raise ValueError("station positions must be unique")
        return self


def _find_path(spec: CorridorInput, unavailable: set[str]) -> dict:
    stations = sorted((s for s in spec.stations if s.available and s.id not in unavailable), key=lambda s: s.km)
    points = [("start", 0.0)] + [(s.id, s.km) for s in stations] + [("destination", spec.route_km)]
    rate = spec.consumption_kwh_per_km * spec.consumption_multiplier
    usable_after_start = (spec.initial_soc - spec.reserve_soc) * spec.battery_usable_kwh
    usable_after_charge = (1 - spec.reserve_soc) * spec.battery_usable_kwh
    best: dict[int, list[int]] = {0: [0]}
    for j in range(1, len(points)):
        choices = []
        for i, path in best.items():
            allowed = usable_after_start if i == 0 else usable_after_charge
            needed = (points[j][1] - points[i][1]) * rate
            if needed <= allowed + 1e-9:
                choices.append(path + [j])
        if choices:
            best[j] = min(choices, key=lambda path: (len(path), [points[k][1] for k in path[1:]]))
    end = len(points) - 1
    if end not in best:
        return {"reachable": False, "stops": [], "legs": [],
                "farthest_reachable_km": max(points[i][1] for i in best)}
    path = best[end]
    legs = []
    soc = spec.initial_soc
    for previous, current in zip(path, path[1:]):
        distance = points[current][1] - points[previous][1]
        arrival_soc = soc - distance * rate / spec.battery_usable_kwh
        legs.append({"from": points[previous][0], "to": points[current][0],
                     "distance_km": round(distance, 3), "arrival_soc": round(arrival_soc, 4)})
        soc = 1.0 if current != end else arrival_soc
    return {"reachable": True, "stops": [points[i][0] for i in path[1:-1]],
            "legs": legs, "arrival_soc": round(soc, 4),
            "farthest_reachable_km": spec.route_km}


def check_corridor(spec: CorridorInput) -> dict:
    baseline = _find_path(spec, set())
    failures = {}
    for station in spec.stations:
        if not station.available:
            continue
        alternative = _find_path(spec, {station.id})
        failures[station.id] = {"reachable": alternative["reachable"],
                                "replacement_stops": alternative["stops"]}
    return {**baseline, "station_failure_impacts": failures,
            "assumptions": ["input positions follow a routed corridor", "charging to full at every selected stop",
                            "constant segment consumption", "no station queue or opening hours"]}
