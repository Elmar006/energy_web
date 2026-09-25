"""Versioned execution configuration, separate from physical scenario inputs.

``validation`` requires a larger simulation sample; it does not certify service
quality. Service acceptance needs explicit requirements and an independent
acceptance procedure, neither of which is configured by this version.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import PlanningInput

Seed = Annotated[int, Field(strict=True, ge=0, le=2_147_483_647)]
ServiceFraction = Annotated[float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)]


class RunSpec(BaseModel):
    """Reproducible execution settings, not proof of operational acceptance.

    Missing solver_seconds and simulation_days inherit the scenario's values
    through ``resolve``. All other defaults are independent of the scenario.
    Only the installed model/simulation versions can be requested.
    """

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    schema_version: Literal["run-spec-v1"] = "run-spec-v1"
    model_version: Literal["planner-mip-v3"] = "planner-mip-v3"
    simulation_version: Literal["simpy-multiday-v1"] = "simpy-multiday-v1"
    mode: Literal["exploratory", "validation"] = "exploratory"
    simulation_seeds: list[Seed] = Field(default_factory=lambda: [1, 2, 3], min_length=1, max_length=100)
    explain_top_n: int = Field(default=3, ge=0, le=10)
    alternative_service_fractions: list[ServiceFraction] = Field(
        default_factory=lambda: [0.0, 0.5, 1.0], max_length=5)
    alternative_solver_seconds: int = Field(default=20, ge=1, le=60)
    solver_seconds: int = Field(default=60, ge=1, le=3600,
                               description="When omitted, inherits input.parameters.solver_seconds.")
    simulation_days: int = Field(default=3, ge=1, le=14,
                                description="When omitted, inherits input.parameters.simulation_days.")

    @model_validator(mode="after")
    def validate_execution_settings(self):
        if len(set(self.simulation_seeds)) != len(self.simulation_seeds):
            raise ValueError("simulation_seeds must contain unique integers")
        if self.mode == "validation" and len(self.simulation_seeds) < 30:
            raise ValueError("validation mode requires at least 30 simulation_seeds")
        targets = self.alternative_service_fractions
        if targets != sorted(set(targets)):
            raise ValueError("alternative_service_fractions must be unique and sorted")
        return self

    def resolve(self, planning_input: PlanningInput) -> RunSpec:
        """Return a fully explicit specification without modifying either input."""
        settings = self.model_dump()
        for field in ("solver_seconds", "simulation_days"):
            if field not in self.model_fields_set:
                settings[field] = getattr(planning_input.parameters, field)
        return RunSpec.model_validate(settings)

    def apply(self, planning_input: PlanningInput) -> PlanningInput:
        """Apply resolved execution overrides to a private scenario copy."""
        resolved = self.resolve(planning_input)
        effective = planning_input.model_copy(deep=True)
        effective.parameters.solver_seconds = resolved.solver_seconds
        effective.parameters.simulation_days = resolved.simulation_days
        return effective


def input_sha256(planning_input: PlanningInput) -> str:
    canonical = json.dumps(planning_input.model_dump(mode="json"), ensure_ascii=False,
                           sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def engine_source_manifest() -> tuple[str, list[str]]:
    """Hash all engine Python sources with the existing benchmark manifest format."""
    source_root = Path(__file__).parent
    source_files = sorted(source_root.rglob("*.py"))
    digest = hashlib.sha256()
    names = []
    for source_file in source_files:
        name = source_file.relative_to(source_root).as_posix()
        content = source_file.read_bytes()
        digest.update(name.encode("utf-8"))
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        names.append(name)
    return digest.hexdigest(), names
