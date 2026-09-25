"""Turn an explicit vehicle itinerary into potential public charging demand.

This is a deterministic scenario transformation. A generated public request is
assumed deliverable for *demand projection*; actual station service is decided
later by the optimizer and independent operations model.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from importlib.metadata import version
from math import isclose
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (ChargingRequest, DatasetReference, PlanningInput,
                        Provenance, ServiceCalendar)
from .run_spec import engine_source_manifest


class _FiniteModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Drive(_FiniteModel):
    kind: Literal["drive"]
    start_at: datetime
    end_at: datetime
    destination_zone_id: str = Field(min_length=1)
    distance_km: float = Field(gt=0)
    consumption_multiplier: float = Field(default=1, gt=0)


class Park(_FiniteModel):
    kind: Literal["park"]
    start_at: datetime
    end_at: datetime
    zone_id: str = Field(min_length=1)
    private_charger_kw: float = Field(default=0, ge=0)
    public_allowed: bool = False


Activity = Annotated[Drive | Park, Field(discriminator="kind")]


class MobilityVehicle(_FiniteModel):
    id: str = Field(min_length=1)
    segment: Literal["private", "taxi", "fleet", "corridor"]
    initial_zone_id: str = Field(min_length=1)
    battery_kwh: float = Field(gt=0)
    initial_kwh: float = Field(ge=0)
    reserve_kwh: float = Field(ge=0)
    consumption_kwh_per_km: float = Field(gt=0)
    max_charge_kw: float = Field(gt=0)
    charging_efficiency: float = Field(default=0.9, gt=0, le=1)
    population_weight: float = Field(default=1, gt=0, le=10000)
    population_weight_basis: str | None = Field(default=None, min_length=1, max_length=2048)
    activities: list[Activity] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def check_battery(self):
        if self.initial_kwh > self.battery_kwh or self.reserve_kwh > self.battery_kwh:
            raise ValueError("initial energy and reserve cannot exceed battery")
        if self.population_weight != 1 and not self.population_weight_basis:
            raise ValueError("population_weight_basis is required when population_weight differs from one")
        return self


class MobilityInput(_FiniteModel):
    schema_version: Literal["mobility-v1"] = "mobility-v1"
    time_zone: str = Field(min_length=1)
    covered_dates: list[date] = Field(min_length=1, max_length=366)
    replace_zone_ids: list[str] = Field(min_length=1, max_length=10000)
    source: str = Field(min_length=1, max_length=2048)
    source_kind: Literal["observed", "assumed"]
    license: str | None = Field(default=None, max_length=2048)
    max_average_speed_kmh: float = Field(default=250, gt=0, le=300)
    vehicles: list[MobilityVehicle] = Field(min_length=1, max_length=10000)

    @model_validator(mode="after")
    def check_coverage(self):
        try:
            ZoneInfo(self.time_zone)
        except (KeyError, ValueError) as error:
            raise ValueError("time_zone must be a valid IANA zone") from error
        if self.covered_dates != sorted(set(self.covered_dates)):
            raise ValueError("covered_dates must be sorted and unique")
        if len(set(self.replace_zone_ids)) != len(self.replace_zone_ids):
            raise ValueError("replace_zone_ids must be unique")
        if len({vehicle.id for vehicle in self.vehicles}) != len(self.vehicles):
            raise ValueError("vehicle ids must be unique")
        if sum(len(vehicle.activities) for vehicle in self.vehicles) > 100000:
            raise ValueError("mobility input exceeds 100000 activities")
        return self


def _valid_local_instant(value: datetime, zone: ZoneInfo) -> bool:
    if value.tzinfo is None or value.utcoffset() is None:
        return False
    local = value.astimezone(zone)
    return (local.replace(tzinfo=None) == value.replace(tzinfo=None)
            and local.utcoffset() == value.utcoffset())


def _season(day: date) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring",
            5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "autumn",
            10: "autumn", 11: "autumn"}[day.month]


def compile_mobility(spec: PlanningInput, mobility: MobilityInput) -> dict:
    """Return a new PlanningInput, explicit requests, calendar and energy audit.

    Every date in covered_dates is asserted to be represented, including days
    with zero requests. The 24-hour projection is a mean per covered local day,
    not an independently validated year-long forecast.
    """
    zone = ZoneInfo(mobility.time_zone)
    if len(mobility.covered_dates) > 14:
        raise ValueError("dated service_calendar supports at most 14 consecutive days")
    source_bytes = json.dumps(mobility.model_dump(mode="json"), ensure_ascii=False,
                              sort_keys=True, separators=(",", ":")).encode("utf-8")
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if spec.time_zone is not None and spec.time_zone != mobility.time_zone:
        raise ValueError("mobility time_zone differs from scenario time_zone")
    zones = {item.id: item for item in spec.zones}
    replaced = set(mobility.replace_zone_ids)
    if replaced - zones.keys():
        raise ValueError("replace_zone_ids contain unknown planning zones")
    covered = set(mobility.covered_dates)
    requests: list[ChargingRequest] = []
    audits = []
    for vehicle in mobility.vehicles:
        if vehicle.initial_zone_id not in zones:
            raise ValueError(f"unknown initial zone for vehicle {vehicle.id}")
        soc = vehicle.initial_kwh
        initial = soc
        current_zone = vehicle.initial_zone_id
        driven_kwh = private_metered_kwh = public_metered_kwh = 0.0
        previous_end: datetime | None = None
        drive_kwh: dict[int, float] = {}
        parking_hours: dict[int, float] = {}
        # Validate the complete itinerary before projecting any charging. A
        # drive can require energy from an earlier parking, even if the park
        # immediately before that drive has no charger.
        for index, activity in enumerate(vehicle.activities):
            if index and type(activity) is type(vehicle.activities[index - 1]):
                raise ValueError(f"drives and parkings must alternate: {vehicle.id}")
            if not _valid_local_instant(activity.start_at, zone) or not _valid_local_instant(activity.end_at, zone):
                raise ValueError(f"activity timestamp must be local with the correct UTC offset: {vehicle.id}")
            start_utc = activity.start_at.astimezone(timezone.utc)
            end_utc = activity.end_at.astimezone(timezone.utc)
            if (start_utc >= end_utc or (previous_end is not None and start_utc < previous_end)
                    or activity.start_at.date() not in covered
                    or activity.end_at.date() not in covered):
                raise ValueError(f"activity time or date coverage is invalid: {vehicle.id}")
            previous_end = end_utc
            if isinstance(activity, Drive):
                if activity.destination_zone_id not in zones:
                    raise ValueError(f"unknown destination zone: {vehicle.id}")
                elapsed_hours = (end_utc - start_utc).total_seconds() / 3600
                if activity.distance_km > mobility.max_average_speed_kmh * elapsed_hours + 1e-9:
                    raise ValueError(f"drive exceeds max_average_speed_kmh: {vehicle.id}")
                need = (activity.distance_km * vehicle.consumption_kwh_per_km
                        * activity.consumption_multiplier)
                if need + vehicle.reserve_kwh > vehicle.battery_kwh + 1e-9:
                    raise ValueError(f"drive exceeds battery capacity: {vehicle.id}")
                drive_kwh[index] = need
                current_zone = activity.destination_zone_id
                continue
            if activity.zone_id != current_zone or activity.zone_id not in replaced:
                raise ValueError(f"parking zone does not match itinerary and covered zones: {vehicle.id}")
            if zones[activity.zone_id].group != vehicle.segment:
                raise ValueError(f"parking zone segment does not match vehicle segment: {vehicle.id}")
            parking_hours[index] = (end_utc - start_utc).total_seconds() / 3600

        # Backward minimum SoC uses *all* future charging windows. It imposes
        # the reserve after every drive, rather than merely at journey end.
        required_soc = vehicle.reserve_kwh
        required_after_park: dict[int, float] = {}
        future_drive_kwh: dict[int, float] = {}
        remaining_drive_kwh = 0.0
        for index in range(len(vehicle.activities) - 1, -1, -1):
            activity = vehicle.activities[index]
            if isinstance(activity, Drive):
                need = drive_kwh[index]
                remaining_drive_kwh += need
                required_soc = need + max(vehicle.reserve_kwh, required_soc)
                if required_soc > vehicle.battery_kwh + 1e-9:
                    raise ValueError(f"itinerary exceeds battery capacity before drive: {vehicle.id}")
            else:
                required_after_park[index] = required_soc
                future_drive_kwh[index] = remaining_drive_kwh
                charge_kw = (vehicle.max_charge_kw if activity.public_allowed else
                             min(activity.private_charger_kw, vehicle.max_charge_kw))
                required_soc = max(0.0, required_soc - charge_kw * parking_hours[index]
                                   * vehicle.charging_efficiency)

        current_zone = vehicle.initial_zone_id
        for index, activity in enumerate(vehicle.activities):
            if isinstance(activity, Drive):
                need = drive_kwh[index]
                if soc + 1e-9 < need + vehicle.reserve_kwh:
                    raise ValueError(f"vehicle {vehicle.id} cannot complete its drive with reserve")
                soc -= need
                driven_kwh += need
                current_zone = activity.destination_zone_id
                continue

            required = required_after_park[index]
            duration_hours = parking_hours[index]
            private_kw = min(activity.private_charger_kw, vehicle.max_charge_kw)
            private_capacity = private_kw * duration_hours
            # Use available private energy for future driving, not just the
            # immediately next drive. Never fill beyond total remaining need.
            private_target = min(vehicle.battery_kwh,
                                 vehicle.reserve_kwh + future_drive_kwh[index])
            private_metered = min(private_capacity,
                                  max(0.0, private_target - soc) / vehicle.charging_efficiency)
            if soc + private_metered * vehicle.charging_efficiency + 1e-9 >= required:
                soc += private_metered * vehicle.charging_efficiency
                private_metered_kwh += private_metered
                continue

            if not activity.public_allowed:
                raise ValueError(f"no feasible charging access before next drive: {vehicle.id}")
            deficit_metered = max(0.0, required - soc) / vehicle.charging_efficiency
            public_kw = vehicle.max_charge_kw
            if deficit_metered > public_kw * duration_hours + 1e-9:
                raise ValueError(f"public charge cannot fit the parking window: {vehicle.id}")
            # The vehicle cannot charge privately and publicly at the same
            # time. Maximize private energy within the shared parking window.
            if private_kw > 0 and private_kw < public_kw:
                private_metered = max(0.0, min(
                    deficit_metered, private_capacity,
                    (duration_hours - deficit_metered / public_kw)
                    / (1 / private_kw - 1 / public_kw)))
            else:
                private_metered = 0.0
            public_metered = deficit_metered - private_metered
            private_hours = private_metered / private_kw if private_kw else 0.0
            public_arrival = (activity.start_at.astimezone(timezone.utc)
                              + timedelta(hours=private_hours)).astimezone(zone)
            private_metered_kwh += private_metered
            soc += private_metered * vehicle.charging_efficiency
            requests.append(ChargingRequest(
                request_id=f"{vehicle.id}:{index}",
                vehicle_id=vehicle.id, segment=vehicle.segment, zone_id=activity.zone_id,
                arrival_at=public_arrival, deadline_at=activity.end_at,
                energy_from_charger_kwh=public_metered, battery_kwh=vehicle.battery_kwh,
                soc_before_kwh=soc, max_vehicle_kw=vehicle.max_charge_kw,
                charging_efficiency=vehicle.charging_efficiency,
                population_weight=vehicle.population_weight,
                provenance=Provenance(source=f"mobility-v1:{source_hash}:{mobility.source}",
                                      kind="derived")))
            public_metered_kwh += public_metered
            soc += public_metered * vehicle.charging_efficiency  # virtual projection only
        residual = initial + (private_metered_kwh + public_metered_kwh) * vehicle.charging_efficiency - driven_kwh - soc
        if not isclose(residual, 0, abs_tol=1e-7) or soc < -1e-8 or soc > vehicle.battery_kwh + 1e-8:
            raise ValueError(f"vehicle energy balance failed: {vehicle.id}")
        audits.append({"vehicle_id": vehicle.id, "population_weight": vehicle.population_weight,
                       "population_weight_basis": vehicle.population_weight_basis,
                       "weighted_public_requested_kwh": public_metered_kwh * vehicle.population_weight,
                       "initial_kwh": initial,
                       "driving_kwh": driven_kwh,
                       "private_metered_kwh": private_metered_kwh,
                       "public_requested_metered_kwh": public_metered_kwh,
                       "projected_final_kwh": soc, "balance_error_kwh": residual})

    compiler_source_hash, _ = engine_source_manifest()
    by_zone_hour: dict[str, list[float]] = {id_: [0.0] * 24 for id_ in replaced}
    by_zone_weight: dict[str, float] = defaultdict(float)
    # Sparse daily slices avoid O(days * zones * 24) memory for large territories.
    by_date: dict[date, dict[str, list[float]]] = {
        day: {} for day in mobility.covered_dates}
    for request in requests:
        local = request.arrival_at.astimezone(zone)
        weighted = request.energy_from_charger_kwh * request.population_weight
        by_zone_hour[request.zone_id][local.hour] += weighted
        by_zone_weight[request.zone_id] += request.population_weight
        by_date[local.date()].setdefault(request.zone_id, [0.0] * 24)[local.hour] += weighted
    output = spec.model_copy(deep=True)
    output.time_zone = mobility.time_zone
    output.service_calendar = ServiceCalendar(
        time_zone=mobility.time_zone, covered_dates=mobility.covered_dates,
        request_zone_ids=mobility.replace_zone_ids,
        legacy_profile_zone_ids=sorted(set(zones) - replaced),
        annualization_factor=365 / len(covered))
    output.charging_requests = requests
    for item in output.zones:
        if item.id not in replaced:
            continue
        item.hourly_kwh = [value / len(covered) for value in by_zone_hour[item.id]]
        if by_zone_weight[item.id]:
            item.mean_session_kwh = sum(by_zone_hour[item.id]) / by_zone_weight[item.id]
        item.arrival_profile = None  # observed completed sessions are a different quantity
        item.provenance = Provenance(source=f"mobility-v1:{source_hash}:{mobility.source}", kind="derived")
    output.datasets.append(DatasetReference(
        name="mobility-v1 potential public requests", role="planning_assumptions",
        kind="derived", source_kind=mobility.source_kind, source=mobility.source, sha256=source_hash,
        license=mobility.license, transform_version="mobility-v1"))
    # model_copy and assignment bypass Pydantic's model-level reference checks.
    output = PlanningInput.model_validate(output.model_dump(mode="json"))
    daily = []
    for day in mobility.covered_dates:
        start = datetime.combine(day, time.min, zone).astimezone(timezone.utc)
        finish = datetime.combine(day + timedelta(days=1), time.min, zone).astimezone(timezone.utc)
        daily.append({"date": day.isoformat(), "day_type": "weekend" if day.weekday() >= 5 else "weekday",
                      "season": _season(day), "physical_hours": (finish - start).total_seconds() / 3600,
                      "zone_hourly_kwh": by_date[day]})
    return {"spec": output.model_dump(mode="json"),
            "requests": [request.model_dump(mode="json") for request in requests],
            "calendar_profiles": daily,
            "audit": {"vehicles": audits, "request_count": len(requests),
                      "population_weighted_public_kwh": sum(sum(v) for v in by_zone_hour.values()),
                      "covered_dates": len(covered), "source_kind": mobility.source_kind,
                      "projection": "mean_per_covered_local_day; virtual_public_fulfillment"},
            "source_sha256": source_hash,
            "source_canonical_json": source_bytes.decode("utf-8"),
            "compiler_source_sha256": compiler_source_hash,
            "compiler_pydantic_version": version("pydantic")}
