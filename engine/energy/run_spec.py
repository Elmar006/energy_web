"""Versioned execution configuration, separate from physical scenario inputs.

``validation`` requires a larger simulation sample. Optional explicit service
requirements are assessed on that sample, without claiming external validity.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import PlanningInput
from .acceptance import ServiceRequirements

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
    service_requirements: ServiceRequirements | None = None

    @model_validator(mode="after")
    def validate_execution_settings(self):
        if len(set(self.simulation_seeds)) != len(self.simulation_seeds):
            raise ValueError("simulation_seeds must contain unique integers")
        if self.mode == "validation" and len(self.simulation_seeds) < 30:
            raise ValueError("validation mode requires at least 30 simulation_seeds")
        if self.service_requirements is not None and self.mode != "validation":
            raise ValueError("service_requirements require validation mode")
        if (self.service_requirements is not None and
                len(self.simulation_seeds) < self.service_requirements.min_seeds_per_condition):
            raise ValueError("simulation_seeds do not meet min_seeds_per_condition")
        targets = self.alternative_service_fractions
        if targets != sorted(set(targets)):
            raise ValueError("alternative_service_fractions must be unique and sorted")
        return self

    def resolve(self, planning_input: PlanningInput) -> RunSpec:
        """Return a fully explicit specification without modifying either input."""
        settings = self.model_dump(exclude_none=True)
        if self.service_requirements is not None:
            settings["service_requirements"] = self.service_requirements.model_dump(
                exclude_unset=True, exclude_none=True)
        for field in ("solver_seconds", "simulation_days"):
            if field not in self.model_fields_set:
                settings[field] = getattr(planning_input.parameters, field)
        return type(self).model_validate(settings)

    def apply(self, planning_input: PlanningInput) -> PlanningInput:
        """Apply resolved execution overrides to a private scenario copy."""
        resolved = self.resolve(planning_input)
        effective = planning_input.model_copy(deep=True)
        effective.parameters.solver_seconds = resolved.solver_seconds
        effective.parameters.simulation_days = resolved.simulation_days
        return effective


class RunSpecV2(RunSpec):
    """Opt-in development/holdout protocol for bounded plan improvement.

    ``simulation_seeds`` remain the final, untouched validation sample. The
    development sample may select investments, so its statistics must never be
    reported as an independent acceptance result.
    """

    schema_version: Literal["run-spec-v2"]
    development_seeds: list[Seed] = Field(default_factory=list, max_length=30)
    max_improvement_iterations: int = Field(default=0, ge=0, le=3)

    @model_validator(mode="after")
    def validate_improvement(self):
        if len(set(self.development_seeds)) != len(self.development_seeds):
            raise ValueError("development_seeds must be unique")
        if set(self.development_seeds) & set(self.simulation_seeds):
            raise ValueError("development_seeds and simulation_seeds must be disjoint")
        if self.max_improvement_iterations and (
            self.mode != "validation" or self.service_requirements is None
            or len(self.development_seeds) < 2
        ):
            raise ValueError("improvement requires validation, service requirements and two development seeds")
        return self


def input_sha256(planning_input: PlanningInput) -> str:
    snapshot = planning_input.model_dump(mode="json")
    # This optional provenance attribute was added after the locked commission
    # benchmark. Omitted values must not change the canonical hash of old inputs.
    for dataset in snapshot["datasets"]:
        if dataset.get("source_kind") is None:
            dataset.pop("source_kind", None)
    # Additive dated-demand fields must not re-identify historical immutable
    # snapshots that had no such dataset. Retain an explicit empty request list
    # when a calendar is present: zero demand on a covered day is meaningful.
    if snapshot.get("demand_dataset") is None:
        snapshot.pop("demand_dataset", None)
    if snapshot.get("service_calendar") is None:
        snapshot.pop("service_calendar", None)
        if not snapshot.get("charging_requests"):
            snapshot.pop("charging_requests", None)
    # Empty additive operational inputs do not change legacy behaviour. Keep
    # historical identities stable; actual transfer edges/outages remain hashed.
    for key in ("site_travel_edges", "operational_outages"):
        if not snapshot.get(key):
            snapshot.pop(key, None)
    canonical = json.dumps(snapshot, ensure_ascii=False,
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
