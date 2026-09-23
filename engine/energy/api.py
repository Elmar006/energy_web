from __future__ import annotations

import hashlib
import json
import sys
from importlib.metadata import version

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .contracts import PlanningInput
from .analysis import explain_selected_sites
from .corridor import CorridorInput, check_corridor
from .fleet import FleetInput, schedule_fleet
from .optimizer import solve
from .simulation import simulate

app = FastAPI(title="Energy planning engine", version="1.0.0", docs_url=None, redoc_url=None)


class CalculationRequest(BaseModel):
    input: PlanningInput
    simulation_seeds: list[int] = Field(default_factory=lambda: [1, 2, 3], max_length=30)
    explain_top_n: int = Field(default=0, ge=0, le=10)


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/v1/validate")
def validate_input(planning_input: PlanningInput):
    return {"valid": True, "id": planning_input.id,
            "zones": len(planning_input.zones), "sites": len(planning_input.sites),
            "grid_nodes": len(planning_input.grid_nodes)}


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
    output = {"optimization": result.as_dict(), "simulation": [], "explanations": [],
              "metadata": {"model_version": "planner-mip-v1", "input_sha256": hashlib.sha256(canonical).hexdigest(),
                           "python_version": sys.version.split()[0], "pyomo_version": version("pyomo"),
                           "highspy_version": version("highspy"), "simulation_seeds": request.simulation_seeds}}
    if result.status not in ("optimal", "feasible"):
        return output
    for scenario in request.input.scenarios:
        for year in request.input.parameters.years:
            for seed in request.simulation_seeds:
                output["simulation"].append(simulate(request.input, result.selected, year=year,
                                                     scenario_id=scenario.id, seed=seed,
                                                     grid_upgrades=result.grid_upgrades))
    if request.explain_top_n:
        output["explanations"] = explain_selected_sites(request.input, result, request.explain_top_n)
    return output
