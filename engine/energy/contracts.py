from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class FiniteModel(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


class Provenance(FiniteModel):
    source: str = Field(min_length=1)
    kind: Literal["observed", "derived", "assumed"]
    captured_at: str | None = None


class DatasetReference(FiniteModel):
    name: str = Field(min_length=1)
    role: Literal["demand_sessions", "demand_zones", "candidate_sites", "grid", "tariff", "routing", "planning_assumptions", "other"]
    kind: Literal["observed", "derived", "assumed"]
    # `kind=derived` describes the transformed planning input, while this field
    # preserves whether the source records were observed or scenario assumptions.
    source_kind: Literal["observed", "assumed"] | None = None
    source: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    version_id: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")
    license: str | None = None
    captured_at: str | None = None
    transform_version: str | None = Field(default=None, min_length=1, max_length=80)


class DemandDataset(FiniteModel):
    """Verified content-addressed artifact metadata; the engine never fetches it."""

    schema_version: Literal["demand-dataset-v1"] = "demand-dataset-v1"
    artifact_id: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_size: int = Field(gt=0)

    @model_validator(mode="after")
    def check_identity(self):
        if self.artifact_id != f"sha256:{self.sha256}":
            raise ValueError("demand dataset artifact_id must match sha256")
        return self


class ServiceDay(FiniteModel):
    date: date
    day_type: Literal["weekday", "weekend", "holiday"]
    season: Literal["winter", "spring", "summer", "autumn"]


class ServiceCalendar(FiniteModel):
    """A bounded, consecutive local-date execution horizon, including empty days."""

    schema_version: Literal["service-calendar-v1"] = "service-calendar-v1"
    time_zone: str = Field(min_length=1)
    covered_dates: list[date] = Field(min_length=1, max_length=14)
    request_zone_ids: list[str] = Field(min_length=1)
    legacy_profile_zone_ids: list[str] = Field(default_factory=list)
    annualization_factor: float = Field(gt=0)
    annualization_basis: Literal["assumed_repeat"] = "assumed_repeat"
    days: list[ServiceDay] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_dates(self):
        try:
            ZoneInfo(self.time_zone)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("service_calendar.time_zone must be a valid IANA zone") from error
        if self.covered_dates != sorted(set(self.covered_dates)):
            raise ValueError("service_calendar.covered_dates must be sorted and unique")
        if any(right != left + timedelta(days=1) for left, right in
               zip(self.covered_dates, self.covered_dates[1:])):
            raise ValueError("service_calendar.covered_dates must be consecutive")
        if len(set(self.request_zone_ids)) != len(self.request_zone_ids):
            raise ValueError("service_calendar.request_zone_ids must be unique")
        if len(set(self.legacy_profile_zone_ids)) != len(self.legacy_profile_zone_ids):
            raise ValueError("service_calendar.legacy_profile_zone_ids must be unique")
        if set(self.request_zone_ids) & set(self.legacy_profile_zone_ids):
            raise ValueError("service_calendar zone modes must not overlap")
        if self.annualization_factor * len(self.covered_dates) > 366 + 1e-8:
            raise ValueError("annualization_factor cannot imply more than 366 days per year")
        seasons = {12: "winter", 1: "winter", 2: "winter", 3: "spring",
                   4: "spring", 5: "spring", 6: "summer", 7: "summer",
                   8: "summer", 9: "autumn", 10: "autumn", 11: "autumn"}
        if not self.days:
            self.days = [ServiceDay(date=day,
                                    day_type="weekend" if day.weekday() >= 5 else "weekday",
                                    season=seasons[day.month]) for day in self.covered_dates]
        if [item.date for item in self.days] != self.covered_dates:
            raise ValueError("service_calendar.days must align with covered_dates")
        if any(item.season != seasons[item.date.month] for item in self.days):
            raise ValueError("service_calendar season must match local calendar month")
        return self


class ChargingRequest(FiniteModel):
    """Potential public energy from a supplied itinerary, not a completed session."""

    request_id: str = Field(min_length=1)
    vehicle_id: str = Field(min_length=1)
    segment: Literal["private", "taxi", "fleet", "corridor"]
    zone_id: str = Field(min_length=1)
    arrival_at: datetime
    deadline_at: datetime
    energy_from_charger_kwh: float = Field(gt=0)
    battery_kwh: float = Field(gt=0)
    soc_before_kwh: float = Field(ge=0)
    max_vehicle_kw: float = Field(gt=0)
    charging_efficiency: float = Field(default=0.9, gt=0, le=1)
    population_weight: float = Field(gt=0)
    provenance: Provenance

    @model_validator(mode="after")
    def check_energy_window(self):
        if (self.arrival_at.tzinfo is None or self.arrival_at.utcoffset() is None or
                self.deadline_at.tzinfo is None or self.deadline_at.utcoffset() is None):
            raise ValueError("charging request timestamps must be timezone-aware")
        duration_hours = ((self.deadline_at.astimezone(timezone.utc) -
                           self.arrival_at.astimezone(timezone.utc)).total_seconds() / 3600)
        if duration_hours <= 0:
            raise ValueError("charging request deadline must be after arrival")
        if self.soc_before_kwh > self.battery_kwh + 1e-8:
            raise ValueError("charging request SoC exceeds battery capacity")
        if self.energy_from_charger_kwh * self.charging_efficiency > (
                self.battery_kwh - self.soc_before_kwh) + 1e-7:
            raise ValueError("charging request energy exceeds battery headroom")
        if self.energy_from_charger_kwh > self.max_vehicle_kw * duration_hours + 1e-7:
            raise ValueError("charging request exceeds vehicle power over parking window")
        return self


class SessionArrivalProfile(FiniteModel):
    """Supplied sessions starting in each local hour of a representative day.

    Quantiles are the empirical inverse CDF at probabilities 0, 0.01, ..., 1.
    They describe *delivered* session energy, not unobserved demand.
    """

    hourly_sessions: list[float] = Field(min_length=24, max_length=24)
    hourly_count_variance: list[float] = Field(min_length=24, max_length=24)
    energy_quantiles_kwh: list[float] = Field(min_length=101, max_length=101)
    sample_count: int = Field(gt=0)
    observation_days: int = Field(gt=0)
    days_with_sessions: int | None = Field(default=None, gt=0)
    coverage_complete: bool = False
    source_kind: Literal["observed", "assumed"]
    hourly_load_method: Literal["uniform_session_duration", "measured_interval"]
    provenance: Provenance

    @model_validator(mode="after")
    def check_profile(self):
        if any(value < 0 for value in self.hourly_sessions + self.hourly_count_variance):
            raise ValueError("session arrivals and count variance cannot be negative")
        if any(value <= 0 for value in self.energy_quantiles_kwh):
            raise ValueError("session energy quantiles must be positive")
        if self.energy_quantiles_kwh != sorted(self.energy_quantiles_kwh):
            raise ValueError("session energy quantiles must be nondecreasing")
        if abs(sum(self.hourly_sessions) * self.observation_days - self.sample_count) > 1e-5:
            raise ValueError("session arrivals must conserve the observed session count")
        if self.days_with_sessions is not None:
            if self.days_with_sessions > min(self.observation_days, self.sample_count):
                raise ValueError("days_with_sessions cannot exceed observation_days or sample_count")
            if self.days_with_sessions < self.observation_days and not self.coverage_complete:
                raise ValueError("missing session days require coverage_complete=true")
        return self


class Zone(FiniteModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    group: Literal["private", "taxi", "fleet", "corridor"] = "private"
    hourly_kwh: list[float] = Field(min_length=24, max_length=24)
    mean_session_kwh: float = Field(gt=0)
    arrival_profile: SessionArrivalProfile | None = None
    max_travel_minutes: float = Field(gt=0)
    provenance: Provenance

    @model_validator(mode="after")
    def check_demand(self):
        if any(value < 0 for value in self.hourly_kwh):
            raise ValueError("hourly_kwh cannot be negative")
        if self.arrival_profile is not None:
            profile = self.arrival_profile
            metered_daily = sum(self.hourly_kwh)
            sessions_daily = self.mean_session_kwh * sum(profile.hourly_sessions)
            if abs(metered_daily - sessions_daily) > max(1e-5, 1e-6 * metered_daily):
                raise ValueError("hourly metered energy and arrival profile must conserve session energy")
        return self


class ChargerOption(FiniteModel):
    id: str = Field(min_length=1)
    ports: int = Field(gt=0)
    charger_kw: float = Field(gt=0)
    connection_kw: float = Field(gt=0)
    capex_rub: float = Field(ge=0)
    annual_fixed_rub: float = Field(ge=0)
    allowed_groups: list[Literal["private", "taxi", "fleet", "corridor"]] = Field(default_factory=lambda: ["private", "taxi", "fleet", "corridor"])


class GridNode(FiniteModel):
    id: str = Field(min_length=1)
    headroom_kw: list[float] = Field(min_length=24, max_length=24)
    upgrade_kw: float = Field(default=0, ge=0)
    upgrade_capex_rub: float = Field(default=0, ge=0)
    upgrade_lead_years: int = Field(default=0, ge=0)
    provenance: Provenance

    @model_validator(mode="after")
    def check_headroom(self):
        if any(value < 0 for value in self.headroom_kw):
            raise ValueError("headroom_kw cannot be negative")
        return self


class Site(FiniteModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
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


class Scenario(FiniteModel):
    id: str = Field(min_length=1)
    demand_multiplier: list[float]
    tariff_multiplier: float = Field(default=1, gt=0)
    pv_multiplier: float = Field(default=1, ge=0)
    probability: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def check_multipliers(self):
        if any(value < 0 for value in self.demand_multiplier):
            raise ValueError("demand_multiplier cannot be negative")
        return self


class TravelEdge(FiniteModel):
    zone_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    minutes: float = Field(ge=0)


class SiteTravelEdge(FiniteModel):
    from_site_id: str = Field(min_length=1)
    to_site_id: str = Field(min_length=1)
    minutes: float = Field(gt=0)


class OperationalOutage(FiniteModel):
    """Deterministic station outage followed by repair in elapsed UTC minutes."""

    schema_version: Literal["operational-outage-v1"] = "operational-outage-v1"
    site_id: str = Field(min_length=1)
    start_minute: int = Field(ge=0)
    repair_minute: int = Field(gt=0)
    provenance: Provenance

    @model_validator(mode="after")
    def check_window(self):
        if self.repair_minute <= self.start_minute:
            raise ValueError("outage repair_minute must follow start_minute")
        return self


class Parameters(FiniteModel):
    mode: Literal["operator", "city"]
    risk: Literal["worst_case", "expected", "expected_cvar"] = "worst_case"
    cvar_alpha: float = Field(default=0.9, gt=0, lt=1, allow_inf_nan=False)
    max_cvar_loss_rub: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_cvar_unmet_kwh: float | None = Field(default=None, ge=0, allow_inf_nan=False)
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
    simulation_days: int = Field(default=3, ge=1, le=14)

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


class PlanningInput(FiniteModel):
    id: str = Field(min_length=1)
    time_zone: str | None = None
    zones: list[Zone]
    sites: list[Site]
    options: list[ChargerOption]
    grid_nodes: list[GridNode]
    scenarios: list[Scenario]
    travel_edges: list[TravelEdge]
    site_travel_edges: list[SiteTravelEdge] = Field(default_factory=list)
    operational_outages: list[OperationalOutage] = Field(default_factory=list)
    parameters: Parameters
    datasets: list[DatasetReference] = Field(default_factory=list)
    demand_dataset: DemandDataset | None = None
    service_calendar: ServiceCalendar | None = None
    charging_requests: list[ChargingRequest] = Field(default_factory=list)
    locked_site_ids: list[str] = Field(default_factory=list)
    excluded_site_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def references(self):
        if self.time_zone is not None:
            try:
                ZoneInfo(self.time_zone)
            except (ZoneInfoNotFoundError, ValueError) as error:
                raise ValueError("time_zone must be a valid IANA zone") from error
        zones = {z.id for z in self.zones}
        sites = {s.id for s in self.sites}
        opts = {o.id for o in self.options}
        nodes = {n.id for n in self.grid_nodes}
        if not self.zones or not self.sites or not self.scenarios:
            raise ValueError("zones, sites and scenarios are required")
        if self.service_calendar is None and self.charging_requests:
            raise ValueError("charging_requests require service_calendar")
        if self.service_calendar is not None:
            calendar = self.service_calendar
            if self.time_zone is not None and self.time_zone != calendar.time_zone:
                raise ValueError("service_calendar time_zone differs from planning time_zone")
            if set(calendar.request_zone_ids) | set(calendar.legacy_profile_zone_ids) != zones:
                raise ValueError("service_calendar must explicitly classify every zone")
            request_ids = set()
            request_energy = {zone_id: 0.0 for zone_id in calendar.request_zone_ids}
            local_zone = ZoneInfo(calendar.time_zone)
            first_day, last_day = calendar.covered_dates[0], calendar.covered_dates[-1]
            horizon_start = datetime.combine(first_day, datetime.min.time(), local_zone)
            horizon_end = datetime.combine(last_day + timedelta(days=1),
                                           datetime.min.time(), local_zone)
            for request in self.charging_requests:
                if request.request_id in request_ids:
                    raise ValueError("charging request IDs must be unique")
                request_ids.add(request.request_id)
                if request.zone_id not in request_energy:
                    raise ValueError("charging request zone is not in request_zone_ids")
                target_zone = next(item for item in self.zones if item.id == request.zone_id)
                if request.segment != target_zone.group:
                    raise ValueError("charging request segment differs from zone group")
                if not (horizon_start.astimezone(timezone.utc) <= request.arrival_at.astimezone(timezone.utc)
                        < request.deadline_at.astimezone(timezone.utc)
                        <= horizon_end.astimezone(timezone.utc)):
                    raise ValueError("charging request is outside service_calendar")
                request_energy[request.zone_id] += (request.energy_from_charger_kwh *
                                                    request.population_weight)
            for zone in self.zones:
                if zone.id not in request_energy:
                    continue
                average = request_energy[zone.id] / len(calendar.covered_dates)
                if abs(sum(zone.hourly_kwh) - average) > max(1e-5, 1e-6 * average):
                    raise ValueError("dated requests and representative zone energy disagree")
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
        for e in self.site_travel_edges:
            if e.from_site_id not in sites or e.to_site_id not in sites or e.from_site_id == e.to_site_id:
                raise ValueError("site travel edge references invalid site pair")
        outages_by_site: dict[str, list[OperationalOutage]] = {}
        for outage in self.operational_outages:
            if outage.site_id not in sites:
                raise ValueError("outage references unknown site")
            outages_by_site.setdefault(outage.site_id, []).append(outage)
        for entries in outages_by_site.values():
            ordered = sorted(entries, key=lambda item: item.start_minute)
            if any(later.start_minute < earlier.repair_minute for earlier, later in
                   zip(ordered, ordered[1:])):
                raise ValueError("outage windows overlap at one site")
        if len({s.id for s in self.scenarios}) != len(self.scenarios):
            raise ValueError("scenario ids must be unique")
        if any(len(s.demand_multiplier) != len(self.parameters.years) for s in self.scenarios):
            raise ValueError("scenario demand_multiplier must match years")
        if self.parameters.risk in ("expected", "expected_cvar"):
            probabilities = [s.probability for s in self.scenarios]
            if any(p is None for p in probabilities) or abs(sum(probabilities) - 1) > 1e-8:
                raise ValueError("probabilistic risk mode requires probabilities summing to one")
        operator_cap = self.parameters.max_cvar_loss_rub
        city_cap = self.parameters.max_cvar_unmet_kwh
        if self.parameters.risk == "expected_cvar":
            if self.parameters.mode == "operator" and (operator_cap is None or city_cap is not None):
                raise ValueError("operator CVaR requires only max_cvar_loss_rub")
            if self.parameters.mode == "city" and (city_cap is None or operator_cap is not None):
                raise ValueError("city CVaR requires only max_cvar_unmet_kwh")
        elif operator_cap is not None or city_cap is not None:
            raise ValueError("CVaR threshold requires expected_cvar risk mode")
        if set(self.locked_site_ids) & set(self.excluded_site_ids):
            raise ValueError("site cannot be locked and excluded")
        if (set(self.locked_site_ids) | set(self.excluded_site_ids)) - sites:
            raise ValueError("unknown locked or excluded site")
        if any(s.existing_option_id and s.id in self.excluded_site_ids for s in self.sites):
            raise ValueError("existing site cannot be excluded without a decommissioning model")
        if len({(e.zone_id, e.site_id) for e in self.travel_edges}) != len(self.travel_edges):
            raise ValueError("travel edges must be unique")
        if len({(e.from_site_id, e.to_site_id) for e in self.site_travel_edges}) != len(self.site_travel_edges):
            raise ValueError("site travel edges must be unique")
        return self
