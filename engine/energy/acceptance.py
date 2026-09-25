"""Operational acceptance of a plan on an explicitly selected simulation sample.

The intervals describe variation between simulated streams. They say nothing
about whether the supplied demand, prices, or grid assumptions are true.
"""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import PlanningInput


class ServiceRequirements(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    schema_version: Literal["service-v1"] = "service-v1"
    min_energy_fraction: float | None = Field(default=None, ge=0, le=1)
    min_session_fraction: float | None = Field(default=None, ge=0, le=1)
    max_refusal_fraction: float | None = Field(default=None, ge=0, le=1)
    max_mean_seed_p95_wait_minutes: float | None = Field(default=None, ge=0)
    min_seeds_per_condition: int = Field(default=30, ge=2, le=100)

    @model_validator(mode="after")
    def require_threshold(self):
        if all(getattr(self, name) is None for name in (
            "min_energy_fraction", "min_session_fraction", "max_refusal_fraction",
            "max_mean_seed_p95_wait_minutes",
        )):
            raise ValueError("at least one service threshold is required")
        return self


def _interval(values: list[float]) -> tuple[float, float, float]:
    """Deterministic percentile bootstrap of the mean of independent seeds."""
    data = np.asarray(values, dtype=float)
    mean = float(np.mean(data))
    rng = np.random.default_rng(871_399)
    indices = rng.integers(0, len(data), size=(2000, len(data)))
    means = np.mean(data[indices], axis=1)
    lower, upper = np.quantile(means, (0.025, 0.975))
    return mean, float(lower), float(upper)


def assess_service(spec: PlanningInput, optimization: dict, simulations: list[dict],
                   requirements: ServiceRequirements | None, *, validation_mode: bool,
                   expected_seeds: list[int]) -> dict:
    """Assess every planning year and external scenario; never infer missing runs.

    The rules use a 95% percentile bootstrap interval of the *mean per seed*.
    A breached upper/lower bound rejects, a bound meeting the target accepts,
    and an interval crossing the target is inconclusive. A complete physical
    audit is a precondition, not a metric that can be traded for service.
    """
    if requirements is None:
        return {"status": "not_evaluated", "reason": "service_requirements_not_configured"}
    base = {"method": "seed_mean_percentile_bootstrap_v1", "confidence_level": 0.95,
            "interval_scope": "simulation_randomness_only",
            "requirements": requirements.model_dump(mode="json"), "conditions": []}
    status = optimization.get("status")
    if status == "infeasible":
        return {**base, "status": "rejected", "reason": "optimization_infeasible"}
    if status not in ("optimal", "feasible"):
        return {**base, "status": "inconclusive", "reason": "optimization_not_solved"}
    if optimization.get("verification", {}).get("passed") is not True:
        return {**base, "status": "rejected", "reason": "physical_verification_failed"}
    if not validation_mode:
        return {**base, "status": "inconclusive", "reason": "validation_mode_required"}
    if (len(expected_seeds) != len(set(expected_seeds)) or
            len(expected_seeds) < requirements.min_seeds_per_condition):
        return {**base, "status": "inconclusive", "reason": "insufficient_declared_seeds"}

    grouped: dict[tuple[str, int], dict[int, dict]] = defaultdict(dict)
    expected_pairs = {(scenario.id, year) for scenario in spec.scenarios
                      for year in spec.parameters.years}
    for run in simulations:
        try:
            key = (run["scenario_id"], run["year"])
            seed = run["seed"]
            if (key not in expected_pairs or seed not in expected_seeds or
                    seed in grouped[key] or
                    run.get("dispatch_verification", {}).get("passed") is not True):
                return {**base, "status": "inconclusive", "reason": "invalid_simulation_coverage"}
            grouped[key][seed] = run
        except (KeyError, TypeError):
            return {**base, "status": "inconclusive", "reason": "invalid_simulation_coverage"}
    if (set(grouped) != expected_pairs or
            any(set(grouped[key]) != set(expected_seeds) for key in expected_pairs)):
        return {**base, "status": "inconclusive", "reason": "incomplete_simulation_coverage"}

    overall = "accepted"
    for scenario_id, year in sorted(expected_pairs):
        runs = [grouped[(scenario_id, year)][seed] for seed in sorted(expected_seeds)]
        metrics: dict[str, dict] = {}
        condition = "accepted"
        for name, threshold, direction in (
            ("energy_fraction", requirements.min_energy_fraction, "min"),
            ("session_fraction", requirements.min_session_fraction, "min"),
            ("refusal_fraction", requirements.max_refusal_fraction, "max"),
            ("mean_seed_p95_wait_minutes", requirements.max_mean_seed_p95_wait_minutes, "max"),
        ):
            if threshold is None:
                continue
            values = []
            for run in runs:
                try:
                    arrivals = run["arrivals"]
                    served = run["served_sessions"]
                    refused = run["refused_sessions"]
                    requested = run["requested_energy_kwh"]
                    delivered = run["energy_kwh"]
                    if (not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                and isfinite(v) and v >= 0 for v in
                                (arrivals, served, refused, requested, delivered)) or
                            served + refused != arrivals or delivered > requested + 0.002):
                        raise ValueError("invalid simulated totals")
                    if name == "energy_fraction":
                        if requested <= 0:
                            raise ValueError("energy denominator missing")
                        value = min(1.0, delivered / requested)
                    elif name == "session_fraction":
                        if arrivals <= 0:
                            raise ValueError("session denominator missing")
                        value = served / arrivals
                    elif name == "refusal_fraction":
                        if arrivals <= 0:
                            raise ValueError("session denominator missing")
                        value = refused / arrivals
                    else:
                        value = run["p95_wait_minutes"]
                        if served <= 0 or value is None or not isfinite(value) or value < 0:
                            raise ValueError("wait percentile unavailable")
                    values.append(float(value))
                except (KeyError, TypeError, ValueError, ZeroDivisionError):
                    values = []
                    break
            if len(values) != len(runs):
                metrics[name] = {"status": "inconclusive", "reason": "metric_unavailable",
                                 "threshold": threshold}
                if condition != "rejected":
                    condition = "inconclusive"
                continue
            mean, lower, upper = _interval(values)
            metric_status = ("accepted" if (lower >= threshold if direction == "min" else upper <= threshold)
                             else "rejected" if (upper < threshold if direction == "min" else lower > threshold)
                             else "inconclusive")
            metrics[name] = {"status": metric_status, "threshold": threshold,
                             "direction": direction, "mean": mean,
                             "lower_95": lower, "upper_95": upper, "seeds": len(values)}
            if metric_status == "rejected":
                condition = "rejected"
            elif metric_status == "inconclusive" and condition == "accepted":
                condition = "inconclusive"
        base["conditions"].append({"scenario_id": scenario_id, "year": year,
                                    "status": condition, "metrics": metrics})
        if condition == "rejected":
            overall = "rejected"
        elif condition == "inconclusive" and overall == "accepted":
            overall = "inconclusive"
    return {**base, "status": overall,
            "reason": {"accepted": "all_conditions_met", "rejected": "service_threshold_failed",
                       "inconclusive": "uncertain_or_missing_metric"}[overall]}
