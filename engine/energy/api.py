from __future__ import annotations

import hashlib
import sys
import base64
import binascii
from datetime import date
from importlib.metadata import version
from typing import Literal
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import PlanningInput
from .ingest_grid import TRANSFORM_VERSION as GRID_TRANSFORM_VERSION, apply_grid_profile
from .ingest_sessions import TRANSFORM_VERSION as SESSION_TRANSFORM_VERSION, derive_demand
from .analysis import explain_selected_sites
from .acceptance import assess_service
from .improvement import improve_plan
from .alternatives import calculate_alternatives
from .corridor import CorridorInput, check_corridor
from .fleet import FleetInput, schedule_fleet
from .mobility import MobilityInput, compile_mobility
from .optimizer import solve
from .run_spec import RunSpec, RunSpecV2, engine_source_manifest, input_sha256
from .simulation import simulate
from .validation import compare_economics, compare_operations, describe_input_quality

app = FastAPI(title="Energy planning engine", version="1.0.0", docs_url=None, redoc_url=None)


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: PlanningInput
    run_spec: RunSpec | RunSpecV2 | None = None
    simulation_seeds: list[int] = Field(default_factory=lambda: [1, 2, 3], max_length=30)
    explain_top_n: int = Field(default=0, ge=0, le=10)
    alternative_service_fractions: list[float] = Field(default_factory=lambda: [0.0, 0.5, 1.0], max_length=5)
    alternative_solver_seconds: int = Field(default=20, ge=1, le=60)

    @model_validator(mode="before")
    @classmethod
    def reject_ambiguous_configuration(cls, value):
        if isinstance(value, dict) and "run_spec" in value:
            if value["run_spec"] is None:
                raise ValueError("run_spec must be an object when supplied")
            legacy_fields = {"simulation_seeds", "explain_top_n", "alternative_service_fractions",
                             "alternative_solver_seconds"}
            if legacy_fields.intersection(value):
                raise ValueError("run_spec cannot be combined with legacy execution fields")
        return value

    @model_validator(mode="after")
    def validate_alternative_targets(self):
        targets = self.alternative_service_fractions
        if any(not 0 <= value <= 1 for value in targets) or targets != sorted(set(targets)):
            raise ValueError("alternative_service_fractions must be unique, sorted values in [0,1]")
        if any(seed < 0 for seed in self.simulation_seeds) or len(set(self.simulation_seeds)) != len(self.simulation_seeds):
            raise ValueError("simulation_seeds must be unique nonnegative integers")
        if self.run_spec is not None:
            self.run_spec = self.run_spec.resolve(self.input)
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
    coverage_complete: bool = False


class MobilityCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input: PlanningInput
    mobility: MobilityInput


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
                                   end_date=request.end_date, license=request.license, kind=request.kind,
                                   coverage_complete=request.coverage_complete)
        else:
            if request.coverage_complete:
                raise ValueError("coverage_complete applies only to demand_sessions")
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


@app.post("/v1/mobility/compile")
def mobility_compile(request: MobilityCompileRequest):
    try:
        return compile_mobility(request.input, request.mobility)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


async def _calculation_request_sha256(request: Request) -> str:
    # Bind the computed result to the exact HTTP payload received by FastAPI,
    # before Pydantic normalizes defaults, floating-point values or key order.
    return hashlib.sha256(await request.body()).hexdigest()


@app.post("/v1/calculate")
def calculate(request: CalculationRequest, request_sha256: str = Depends(_calculation_request_sha256)):
    settings = request.run_spec if request.run_spec is not None else request
    spec = request.run_spec.apply(request.input) if request.run_spec is not None else request.input
    result = solve(spec)
    improvement_history = None
    if isinstance(request.run_spec, RunSpecV2):
        improvement_history = []
        if request.run_spec.max_improvement_iterations:
            try:
                result, improvement_history = improve_plan(
                    spec, result, seeds=request.run_spec.development_seeds,
                    requirements=request.run_spec.service_requirements,
                    max_iterations=request.run_spec.max_improvement_iterations,
                    solve_fn=solve, simulate_fn=simulate)
            except ValueError as error:
                raise HTTPException(status_code=500, detail=str(error)) from error
    source_digest, source_files = engine_source_manifest()
    output = {"optimization": result.as_dict(), "simulation": [], "operational_validation": [],
              "operational_economics": [],
              "explanations": [], "alternatives": [],
              "service_acceptance": {"status": "not_evaluated",
                                     "reason": "service_requirements_not_configured"},
              "metadata": {"model_version": "planner-mip-v3", "simulation_version": "simpy-multiday-v1",
                           "run_spec": _run_spec_metadata(request.run_spec),
                           "configuration_source": "run_spec" if request.run_spec is not None else "legacy_fields",
                           "engine_request_sha256": request_sha256,
                           "source_input_sha256": input_sha256(request.input),
                           "input_sha256": input_sha256(spec),
                           "engine_source_sha256": source_digest,
                           "engine_source_files": source_files,
                           "python_version": sys.version.split()[0], "pyomo_version": version("pyomo"),
                           "highspy_version": version("highspy"), "simpy_version": version("simpy"),
                           "numpy_version": version("numpy"), "simulation_seeds": settings.simulation_seeds,
                           "simulation_days": spec.parameters.simulation_days,
                           "solver_seconds": spec.parameters.solver_seconds,
                           "explain_top_n": settings.explain_top_n,
                           "input_quality": describe_input_quality(spec),
                           "alternative_service_fractions": settings.alternative_service_fractions,
                           "alternative_solver_seconds": settings.alternative_solver_seconds}}
    if improvement_history is not None:
        output["improvement"] = {
            "method": "bounded_extra_site_development_search_v1",
            "development_seeds": request.run_spec.development_seeds,
            "holdout_seeds_used_for_selection": False,
            "iterations": improvement_history,
        }
    if result.status not in ("optimal", "feasible"):
        output["service_acceptance"] = assess_service(
            spec, result.as_dict(), [],
            request.run_spec.service_requirements if request.run_spec is not None else None,
            validation_mode=request.run_spec is not None and request.run_spec.mode == "validation",
            expected_seeds=settings.simulation_seeds)
        return output
    for scenario in spec.scenarios:
        for year in spec.parameters.years:
            for seed in settings.simulation_seeds:
                run = simulate(spec, result.selected, year=year,
                               scenario_id=scenario.id, seed=seed,
                               grid_upgrades=result.grid_upgrades,
                               battery=result.battery, solar=result.solar)
                if not run["dispatch_verification"]["passed"]:
                    raise HTTPException(status_code=500, detail="operational dispatch failed physical verification")
                output["simulation"].append(run)
    output["operational_validation"] = compare_operations(result, output["simulation"])
    output["service_acceptance"] = assess_service(
        spec, result.as_dict(), output["simulation"],
        request.run_spec.service_requirements if request.run_spec is not None else None,
        validation_mode=request.run_spec is not None and request.run_spec.mode == "validation",
        expected_seeds=settings.simulation_seeds)
    output["operational_economics"] = compare_economics(spec, result, output["simulation"])
    if settings.explain_top_n:
        output["explanations"] = explain_selected_sites(spec, result, settings.explain_top_n)
    if settings.alternative_service_fractions:
        output["alternatives"] = calculate_alternatives(spec, settings.alternative_service_fractions,
                                                       settings.simulation_seeds, settings.alternative_solver_seconds)
        for alternative in output["alternatives"]:
            alternative["service_acceptance"] = assess_service(
                spec, alternative["optimization"], alternative["simulation"],
                request.run_spec.service_requirements if request.run_spec is not None else None,
                validation_mode=request.run_spec is not None and request.run_spec.mode == "validation",
                expected_seeds=settings.simulation_seeds)
    return output


def _run_spec_metadata(spec: RunSpec | RunSpecV2 | None) -> dict | None:
    if spec is None:
        return None
    data = spec.model_dump(mode="json", exclude_none=True)
    if isinstance(spec, RunSpecV2):
        # Go uses omitempty for these additive fields; the engine must echo
        # the exact immutable execution snapshot for worker fencing.
        if not spec.development_seeds:
            data.pop("development_seeds", None)
        if not spec.max_improvement_iterations:
            data.pop("max_improvement_iterations", None)
    if spec.service_requirements is not None:
        # Preserve the exact optional object accepted by the Go RunSpec so the
        # worker can compare the persisted execution snapshot to this echo.
        data["service_requirements"] = spec.service_requirements.model_dump(
            mode="json", exclude_unset=True, exclude_none=True)
    return data
