"""Predeclared, machine-checkable protocol for a commission benchmark.

The seed split is a split of *simulated randomness*, not a holdout of measured
charging demand. A committed lock file makes changes to the protocol visible;
it is not an external timestamp or a substitute for independent validation.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, model_validator

from .contracts import PlanningInput
from .run_spec import engine_source_manifest


BASELINES = ("existing", "density", "optimized")
STRESS_CASES = ("outage", "demand_x0_75", "demand_x1_25", "grid_x0_75", "grid_x1_25")


def input_sha256(spec: PlanningInput) -> str:
    canonical = json.dumps(spec.model_dump(mode="json"), ensure_ascii=False,
                           sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


class BudgetLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    years: tuple[StrictInt, ...] = Field(min_length=1)
    annual_budgets_rub: tuple[Decimal, ...] = Field(min_length=1)
    total_budget_rub: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def check_budgets(self):
        if len(self.years) != len(self.annual_budgets_rub):
            raise ValueError("budget years and annual limits must align")
        if any(not amount.is_finite() or amount < 0 for amount in self.annual_budgets_rub):
            raise ValueError("annual budgets must be finite and nonnegative")
        if not self.total_budget_rub.is_finite():
            raise ValueError("total budget must be finite")
        return self


class SimulationSeedSplit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["simulation_seed_holdout"]
    development_seeds: tuple[StrictInt, ...] = Field(min_length=1)
    evaluation_seeds: tuple[StrictInt, ...] = Field(min_length=30)

    @model_validator(mode="after")
    def check_disjoint(self):
        development, evaluation = self.development_seeds, self.evaluation_seeds
        if (any(seed < 0 for seed in (*development, *evaluation))
                or len(set(development)) != len(development)
                or len(set(evaluation)) != len(evaluation)
                or set(development) & set(evaluation)):
            raise ValueError("development/evaluation seeds must be unique, nonnegative and disjoint")
        return self


class BenchmarkProtocol(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    protocol_version: Literal["commission-benchmark-v1"]
    case_id: StrictStr = Field(min_length=1)
    input_sha256: StrictStr
    engine_source_sha256: StrictStr
    planning_scenario_ids: tuple[StrictStr, ...] = Field(min_length=1)
    evaluation_scenario_id: StrictStr = Field(min_length=1)
    evaluation_year: StrictInt
    simulation_days: StrictInt = Field(ge=1)
    budget: BudgetLock
    split: SimulationSeedSplit
    baselines: tuple[StrictStr, ...]
    stress_cases: tuple[StrictStr, ...]
    primary_comparison: Literal["optimized_minus_density"]
    primary_metric: Literal["service_fraction"]

    @model_validator(mode="after")
    def check_design(self):
        if not re.fullmatch(r"[0-9a-f]{64}", self.input_sha256):
            raise ValueError("input_sha256 must be a lowercase SHA-256 hex digest")
        if not re.fullmatch(r"[0-9a-f]{64}", self.engine_source_sha256):
            raise ValueError("engine_source_sha256 must be a lowercase SHA-256 hex digest")
        if len(set(self.planning_scenario_ids)) != len(self.planning_scenario_ids):
            raise ValueError("planning scenario ids must be unique")
        if self.evaluation_scenario_id not in self.planning_scenario_ids:
            raise ValueError("evaluation scenario must be one of the planning scenarios")
        if self.evaluation_year not in self.budget.years:
            raise ValueError("evaluation year must be in the budget horizon")
        if self.baselines != BASELINES or self.stress_cases != STRESS_CASES:
            raise ValueError("baseline and stress case lists must match the implemented benchmark")
        return self

    @property
    def sha256(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), ensure_ascii=False,
                               sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(canonical).hexdigest()

    def verify_input(self, spec: PlanningInput) -> None:
        """Fail before optimization if the registered evaluation design drifted."""
        checks = {
            "case_id": (spec.id, self.case_id),
            "input_sha256": (input_sha256(spec), self.input_sha256),
            "engine_source_sha256": (engine_source_manifest()[0], self.engine_source_sha256),
            "planning_scenario_ids": (tuple(s.id for s in spec.scenarios), self.planning_scenario_ids),
            "simulation_days": (spec.parameters.simulation_days, self.simulation_days),
            "budget.years": (tuple(spec.parameters.years), self.budget.years),
            "budget.annual_budgets_rub": (
                tuple(Decimal(str(value)) for value in spec.parameters.annual_budgets_rub),
                self.budget.annual_budgets_rub),
            "budget.total_budget_rub": (
                Decimal(str(spec.parameters.total_budget_rub)), self.budget.total_budget_rub),
        }
        for name, (actual, expected) in checks.items():
            if actual != expected:
                raise ValueError(f"benchmark protocol mismatch: {name}")


def load_locked_protocol(protocol_path: Path, lock_path: Path) -> BenchmarkProtocol:
    """Check the separately committed lock; reject missing or malformed locks."""
    protocol = BenchmarkProtocol.model_validate_json(protocol_path.read_bytes())
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if (not isinstance(lock, dict) or set(lock) != {"protocol_sha256"}
            or not isinstance(lock["protocol_sha256"], str)
            or lock["protocol_sha256"] != protocol.sha256):
        raise ValueError("benchmark protocol lock SHA-256 mismatch")
    return protocol
