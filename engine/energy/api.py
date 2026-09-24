from __future__ import annotations

import hashlib
import json
import sys
import base64
import binascii
from datetime import date
from importlib.metadata import version
from typing import Literal
from uuid import UUID

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from .contracts import PlanningInput
from .ingest_grid import TRANSFORM_VERSION as GRID_TRANSFORM_VERSION, apply_grid_profile
from .ingest_sessions import TRANSFORM_VERSION as SESSION_TRANSFORM_VERSION, derive_demand
from .analysis import explain_selected_sites
from .alternatives import calculate_alternatives
from .corridor import CorridorInput, check_corridor
from .fleet import FleetInput, schedule_fleet
from .optimizer import solve
from .simulation import simulate
from .validation import compare_economics, compare_operations, describe_input_quality

app = FastAPI(title="Energy planning engine", version="1.0.0", docs_url=None, redoc_url=None)


class CalculationRequest(BaseModel):
    input: PlanningInput
    simulation_seeds: list[int] = Field(default_factory=lambda: [1, 2, 3], max_length=30)
    explain_top_n: int = Field(default=0, ge=0, le=10)
    alternative_service_fractions: list[float] = Field(default_factory=lambda: [0.0, 0.5, 1.0], max_length=5)
    alternative_solver_seconds: int = Field(default=20, ge=1, le=60)

    @model_validator(mode="after")
    def validate_alternative_targets(self):
        targets = self.alternative_service_fractions
        if any(not 0 <= value <= 1 for value in targets) or targets != sorted(set(targets)):
            raise ValueError("alternative_service_fractions must be unique, sorted values in [0,1]")
        if any(seed < 0 for seed in self.simulation_seeds) or len(set(self.simulation_seeds)) != len(self.simulation_seeds):
            raise ValueError("simulation_seeds must be unique nonnegative integers")
        return self


class DeriveRequest(BaseModel):
    input: PlanningInput
    dataset_version_id: UUID
    dataset_name: str = Field(min_length=1, max_length=120)
    csv_base64: str
    role: Literal["demand_sessions", "grid_headroom"]
    source: str = Field(min_length=1, max_length=2048)
    kind: Literal["observed", "assumed"]
    time_zone: str = Field(min_length=1, max_length=128)
    license: str | None = Field(default=None, max_length=2048)
    start_date: date | None = None
    end_date: date | None = None
    profile_date: date | None = None


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/v1/validate")
def validate_input(planning_input: PlanningInput):
    return {"valid": True, "id": planning_input.id,
            "zones": len(planning_input.zones), "sites": len(planning_input.sites),
            "grid_nodes": len(planning_input.grid_nodes)}


@app.post("/v1/derive")
def derive_uploaded_data(request: DeriveRequest):
    # The public API caps uploads too; keep the internal endpoint bounded when
    # called directly or if a reverse proxy is misconfigured.
    limit = 50 * 1024 * 1024 if request.role == "demand_sessions" else 10 * 1024 * 1024
    if len(request.csv_base64) > 4 * ((limit + 2) // 3):
        raise HTTPException(status_code=413, detail="CSV exceeds role-specific upload limit")
    try:
        csv_bytes = base64.b64decode(request.csv_base64, validate=True)
    except binascii.Error as error:
        raise HTTPException(status_code=422, detail="csv_base64 must be valid base64") from error
    if len(csv_bytes) > limit:
        raise HTTPException(status_code=413, detail="CSV exceeds role-specific upload limit")
    if request.input.time_zone is not None and request.input.time_zone != request.time_zone:
        raise HTTPException(status_code=422, detail="time_zone differs from scenario time_zone")
    try:
        if request.role == "demand_sessions":
            if request.start_date is None or request.end_date is None or request.profile_date is not None:
                raise ValueError("start_date and end_date are required only for demand_sessions")
            result = derive_demand(request.input, csv_bytes, source=request.source,
                                   time_zone=request.time_zone, start_date=request.start_date,
                                   end_date=request.end_date, license=request.license, kind=request.kind)
        else:
            if request.profile_date is None or request.start_date is not None or request.end_date is not None:
                raise ValueError("profile_date is required only for grid_headroom")
            result = apply_grid_profile(request.input, csv_bytes, source=request.source,
                                        profile_date=request.profile_date, time_zone=request.time_zone,
                                        license=request.license, kind=request.kind)
        result.time_zone = request.time_zone
        result.datasets[-1].version_id = str(request.dataset_version_id)
        result.datasets[-1].name = request.dataset_name
        if request.role == "grid_headroom":
            result.datasets[-1].role = "grid"
        transform_version = (SESSION_TRANSFORM_VERSION if request.role == "demand_sessions"
                             else GRID_TRANSFORM_VERSION)
        return {"spec": result.model_dump(mode="json"),
                "sha256": hashlib.sha256(csv_bytes).hexdigest(),
                "transform_version": transform_version}
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.post("/v1/corridor/check")
def corridor_check(request: CorridorInput):
    return check_corridor(request)


@app.post("/v1/fleet/schedule")
def fleet_schedule(request: FleetInput):
    return schedule_fleet(request)


@app.post("/v1/calculate")
def calculate(request: CalculationRequest):
    result = solve(request.input)
    canonical = json.dumps(request.input.model_dump(mode="json"), ensure_ascii=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
    output = {"optimization": result.as_dict(), "simulation": [], "operational_validation": [],
              "operational_economics": [],
              "explanations": [], "alternatives": [],
              "metadata": {"model_version": "planner-mip-v3", "input_sha256": hashlib.sha256(canonical).hexdigest(),
                           "python_version": sys.version.split()[0], "pyomo_version": version("pyomo"),
                           "highspy_version": version("highspy"), "simulation_seeds": request.simulation_seeds,
                           "input_quality": describe_input_quality(request.input),
                           "alternative_service_fractions": request.alternative_service_fractions,
                           "alternative_solver_seconds": request.alternative_solver_seconds}}
    if result.status not in ("optimal", "feasible"):
        return output
    for scenario in request.input.scenarios:
        for year in request.input.parameters.years:
            for seed in request.simulation_seeds:
                run = simulate(request.input, result.selected, year=year,
                               scenario_id=scenario.id, seed=seed,
                               grid_upgrades=result.grid_upgrades,
                               battery=result.battery, solar=result.solar)
                if not run["dispatch_verification"]["passed"]:
                    raise HTTPException(status_code=500, detail="operational dispatch failed physical verification")
                output["simulation"].append(run)
    output["operational_validation"] = compare_operations(result, output["simulation"])
    output["operational_economics"] = compare_economics(request.input, result, output["simulation"])
    if request.explain_top_n:
        output["explanations"] = explain_selected_sites(request.input, result, request.explain_top_n)
    if request.alternative_service_fractions:
        output["alternatives"] = calculate_alternatives(request.input, request.alternative_service_fractions,
                                                         request.simulation_seeds, request.alternative_solver_seconds)
    return output
