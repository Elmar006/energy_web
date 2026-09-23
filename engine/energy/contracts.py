from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Provenance(BaseModel):
    source: str = Field(min_length=1)
    kind: Literal["observed", "derived", "assumed"]
    captured_at: str | None = None


class Zone(BaseModel):
    id: str
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    group: Literal["private", "taxi", "fleet", "corridor"] = "private"
    hourly_kwh: list[float] = Field(min_length=24, max_length=24)
    mean_session_kwh: float = Field(gt=0)
    max_travel_minutes: float = Field(gt=0)
    provenance: Provenance

    @model_validator(mode="after")
    def check_demand(self):
        if any(value < 0 for value in self.hourly_kwh):
            raise ValueError("hourly_kwh cannot be negative")
        return self


class ChargerOption(BaseModel):
    id: str
    ports: int = Field(gt=0)
    charger_kw: float = Field(gt=0)
    connection_kw: float = Field(gt=0)
    capex_rub: float = Field(ge=0)
    annual_fixed_rub: float = Field(ge=0)
    allowed_groups: list[Literal["private", "taxi", "fleet", "corridor"]] = Field(default_factory=lambda: ["private", "taxi", "fleet", "corridor"])


class GridNode(BaseModel):
    id: str
    headroom_kw: list[float] = Field(min_length=24, max_length=24)
    upgrade_kw: float = Field(default=0, ge=0)
    upgrade_capex_rub: float = Field(default=0, ge=0)
    provenance: Provenance

    @model_validator(mode="after")
    def check_headroom(self):
        if any(value < 0 for value in self.headroom_kw):
            raise ValueError("headroom_kw cannot be negative")
        return self


class Site(BaseModel):
    id: str
    name: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    grid_node_id: str
    option_ids: list[str] = Field(min_length=1)
    existing_option_id: str | None = None
    earliest_period: int = Field(default=0, ge=0)
    battery_max_kwh: float = Field(default=0, ge=0)
    battery_capex_per_kwh_rub: float = Field(default=0, ge=0)
    pv_max_kw: float = Field(default=0, ge=0)
    pv_capex_per_kw_rub: float = Field(default=0, ge=0)
    provenance: Provenance


class Scenario(BaseModel):
    id: str
    demand_multiplier: list[float]
    tariff_multiplier: float = Field(default=1, gt=0)
    pv_multiplier: float = Field(default=1, ge=0)
    probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def check_multipliers(self):
        if any(value < 0 for value in self.demand_multiplier):
            raise ValueError("demand_multiplier cannot be negative")
        return self


class TravelEdge(BaseModel):
    zone_id: str
    site_id: str
    minutes: float = Field(ge=0)


class Parameters(BaseModel):
    mode: Literal["operator", "city"]
    risk: Literal["worst_case", "expected"] = "worst_case"
    years: list[int] = Field(min_length=1)
    annual_budgets_rub: list[float] = Field(min_length=1)
    total_budget_rub: float = Field(ge=0)
    sale_rub_per_kwh: float = Field(ge=0)
    purchase_rub_per_kwh: float = Field(ge=0)
    discount_rate: float = Field(ge=0, lt=1)
    pv_hourly_factor: list[float] = Field(min_length=24, max_length=24)
    storage_efficiency: float = Field(default=0.9, gt=0, le=1)
    storage_max_hours: float = Field(default=2, gt=0)
    storage_degradation_rub_per_kwh: float = Field(default=0, ge=0)
    minimum_zone_service: float = Field(default=0, ge=0, le=1)
    solver_seconds: int = Field(default=60, ge=1, le=3600)

    @model_validator(mode="after")
    def check_periods(self):
        if len(self.years) != len(self.annual_budgets_rub) or len(set(self.years)) != len(self.years):
            raise ValueError("years and annual_budgets_rub must align and years be unique")
        if self.years != sorted(self.years):
            raise ValueError("years must be sorted")
        if any(later != earlier + 1 for earlier, later in zip(self.years, self.years[1:])):
            raise ValueError("planning years must be consecutive")
        if any(value < 0 for value in self.annual_budgets_rub):
            raise ValueError("annual_budgets_rub cannot be negative")
        if any(value < 0 or value > 1 for value in self.pv_hourly_factor):
            raise ValueError("pv_hourly_factor must be between zero and one")
        return self


class PlanningInput(BaseModel):
    id: str
    zones: list[Zone]
    sites: list[Site]
    options: list[ChargerOption]
    grid_nodes: list[GridNode]
    scenarios: list[Scenario]
    travel_edges: list[TravelEdge]
    parameters: Parameters
    locked_site_ids: list[str] = Field(default_factory=list)
    excluded_site_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        zones = {z.id for z in self.zones}
        sites = {s.id for s in self.sites}
        opts = {o.id for o in self.options}
        nodes = {n.id for n in self.grid_nodes}
        if not self.zones or not self.sites or not self.scenarios:
            raise ValueError("zones, sites and scenarios are required")
        if len(zones) != len(self.zones) or len(sites) != len(self.sites) or len(opts) != len(self.options) or len(nodes) != len(self.grid_nodes):
            raise ValueError("ids must be unique within each collection")
        for s in self.sites:
            if s.grid_node_id not in nodes or any(o not in opts for o in s.option_ids):
                raise ValueError(f"unknown node or option at site {s.id}")
            if s.existing_option_id and s.existing_option_id not in s.option_ids:
                raise ValueError(f"existing option not available at site {s.id}")
        for e in self.travel_edges:
            if e.zone_id not in zones or e.site_id not in sites:
                raise ValueError("travel edge references unknown zone or site")
        if len({s.id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario ids must be unique")
        if any(len(s.demand_multiplier) != len(self.parameters.years) for s in self.scenarios):
            raise ValueError("scenario demand_multiplier must match years")
        if self.parameters.risk == "expected":
            probabilities = [s.probability for s in self.scenarios]
            if any(p is None for p in probabilities) or abs(sum(probabilities) - 1) > 1e-8:
                raise ValueError("expected mode requires probabilities summing to one")
        if set(self.locked_site_ids) & set(self.excluded_site_ids):
            raise ValueError("site cannot be locked and excluded")
        if (set(self.locked_site_ids) | set(self.excluded_site_ids)) - sites:
            raise ValueError("unknown locked or excluded site")
        if any(s.existing_option_id and s.id in self.excluded_site_ids for s in self.sites):
            raise ValueError("existing site cannot be excluded without a decommissioning model")
        if len({(e.zone_id, e.site_id) for e in self.travel_edges}) != len(self.travel_edges):
            raise ValueError("travel edges must be unique")
        return self
