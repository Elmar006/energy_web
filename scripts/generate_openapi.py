"""Generate the public Go API contract from the engine's validated scenario schema."""

from __future__ import annotations

import json
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from energy.contracts import PlanningInput  # noqa: E402
from energy.corridor import CorridorInput  # noqa: E402
from energy.fleet import FleetInput  # noqa: E402
from energy.mobility import ChargingRequest, MobilityInput  # noqa: E402
from energy.run_spec import RunSpec, RunSpecV2  # noqa: E402


def ref(name: str) -> dict:
    return {"$ref": f"#/components/schemas/{name}"}


def response(schema: dict, description: str = "Success") -> dict:
    return {"description": description, "content": {"application/json": {"schema": schema}}}


def body(schema: dict) -> dict:
    return {"required": True, "content": {"application/json": {"schema": schema}}}


planning = PlanningInput.model_json_schema(ref_template="#/components/schemas/{model}")
definitions = planning.pop("$defs")
corridor = CorridorInput.model_json_schema(ref_template="#/components/schemas/{model}")
definitions.update(corridor.pop("$defs"))
fleet = FleetInput.model_json_schema(ref_template="#/components/schemas/{model}")
definitions.update(fleet.pop("$defs"))
mobility = MobilityInput.model_json_schema(ref_template="#/components/schemas/{model}")
definitions.update(mobility.pop("$defs", {}))
charging_request = ChargingRequest.model_json_schema(ref_template="#/components/schemas/{model}")
definitions.update(charging_request.pop("$defs", {}))
def run_spec_schemas(model, version: str) -> tuple[dict, dict]:
    overrides = model.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions.update(overrides.pop("$defs", {}))
    overrides["title"] = f"RunSpecOverrides{version}"
    overrides["description"] = ("Optional execution overrides. V2 separates development "
                                "and final holdout seeds; only holdout simulations count toward acceptance.")
    for name in ("solver_seconds", "simulation_days"):
        overrides["properties"][name].pop("default", None)
    overrides["properties"]["simulation_seeds"]["uniqueItems"] = True
    overrides["properties"]["alternative_service_fractions"]["uniqueItems"] = True
    overrides["properties"]["alternative_service_fractions"]["description"] = (
        "Strictly increasing fractions; an empty array disables alternatives.")
    overrides["properties"]["service_requirements"] = ref("ServiceRequirements")
    overrides["allOf"] = [{"if": {"required": ["mode"], "properties": {"mode": {"const": "validation"}}},
                           "then": {"required": ["simulation_seeds"], "properties": {
                               "simulation_seeds": {"minItems": 30}}}}]
    if version == "V2":
        overrides["required"] = ["schema_version"]
        overrides["properties"]["development_seeds"]["uniqueItems"] = True
    resolved = copy.deepcopy(overrides)
    resolved["title"] = f"RunSpec{version}"
    resolved["description"] = "Fully resolved immutable execution controls, persisted when queued."
    resolved["required"] = [name for name in resolved["properties"]
                            if name not in ("service_requirements", "development_seeds",
                                            "max_improvement_iterations")]
    return overrides, resolved


run_overrides_v1, resolved_run_spec_v1 = run_spec_schemas(RunSpec, "V1")
run_overrides_v2, resolved_run_spec_v2 = run_spec_schemas(RunSpecV2, "V2")
schemas = {
    **definitions,
    "ScenarioSpec": planning,
    "CorridorSpec": corridor,
    "FleetSpec": fleet,
    "MobilityInput": mobility,
    "ChargingRequest": charging_request,
    "DemandArtifactDocument": {"type": "object", "additionalProperties": False,
        "required": ["schema_version", "service_calendar", "charging_requests"],
        "properties": {"schema_version": {"const": "demand-dataset-v1", "type": "string"},
                       "service_calendar": ref("ServiceCalendar"),
                       "charging_requests": {"type": "array", "items": ref("ChargingRequest")}}},
    "MobilityCompileRequest": {"type": "object", "additionalProperties": False,
                               "required": ["input", "mobility"],
                               "properties": {"input": ref("ScenarioSpec"), "mobility": ref("MobilityInput")}},
    "MobilityCreateRequest": {"type": "object", "additionalProperties": False,
                              "required": ["name", "input", "mobility"],
                              "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120},
                                             "input": ref("ScenarioSpec"), "mobility": ref("MobilityInput")}},
    "MobilityCalendarProfile": {"type": "object", "additionalProperties": False,
        "required": ["date", "day_type", "season", "physical_hours", "zone_hourly_kwh"],
        "properties": {"date": {"type": "string", "format": "date"},
                       "day_type": {"type": "string", "enum": ["weekday", "weekend"]},
                       "season": {"type": "string", "enum": ["winter", "spring", "summer", "autumn"]},
                       "physical_hours": {"type": "number", "minimum": 0},
                       "zone_hourly_kwh": {"type": "object", "description": "Sparse map; absent zone means zero requests on this covered date.", "additionalProperties": {
                           "type": "array", "minItems": 24, "maxItems": 24,
                           "items": {"type": "number", "minimum": 0}}}}},
    "MobilityVehicleAudit": {"type": "object", "additionalProperties": False,
        "required": ["vehicle_id", "population_weight_basis", "initial_kwh", "driving_kwh", "private_metered_kwh",
                     "public_requested_metered_kwh", "weighted_public_requested_kwh",
                     "population_weight", "projected_final_kwh", "balance_error_kwh"],
        "properties": {"vehicle_id": {"type": "string"},
                       "population_weight_basis": {"type": ["string", "null"]},
                       **{name: {"type": "number"} for name in (
                           "initial_kwh", "driving_kwh", "private_metered_kwh",
                           "public_requested_metered_kwh", "weighted_public_requested_kwh",
                           "population_weight", "projected_final_kwh", "balance_error_kwh")}}},
    "MobilityAudit": {"type": "object", "additionalProperties": False,
        "required": ["vehicles", "request_count", "population_weighted_public_kwh",
                     "covered_dates", "source_kind", "projection"],
        "properties": {"vehicles": {"type": "array", "items": ref("MobilityVehicleAudit")},
                       "request_count": {"type": "integer", "minimum": 0},
                       "population_weighted_public_kwh": {"type": "number", "minimum": 0},
                       "covered_dates": {"type": "integer", "minimum": 1},
                       "source_kind": {"type": "string", "enum": ["observed", "assumed"]},
                       "projection": {"type": "string"}}},
    "PreparedMobilityScenario": {"type": "object", "additionalProperties": False,
        "required": ["spec", "requests", "calendar_profiles", "audit", "source_sha256",
                     "source_canonical_json", "compiler_source_sha256", "compiler_pydantic_version"],
        "properties": {"spec": ref("ScenarioSpec"),
                       "requests": {"type": "array", "items": ref("ChargingRequest")},
                       "calendar_profiles": {"type": "array", "items": ref("MobilityCalendarProfile")},
                       "audit": ref("MobilityAudit"),
                       "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "source_canonical_json": {"type": "string", "description": "Normalized mobility-v1 JSON exactly hashed by source_sha256; archive with the scenario for reproducibility."},
                       "compiler_source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "compiler_pydantic_version": {"type": "string"}}},
    "SavedMobilityScenario": {"type": "object", "additionalProperties": False,
        "required": ["scenario", "dataset_version_id", "source_sha256", "base_sha256", "source_access_token"],
        "properties": {"scenario": ref("SavedScenario"),
                       "dataset_version_id": {"type": "string", "format": "uuid"},
                       "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "base_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "source_access_token": {"type": "string", "pattern": "^[0-9a-f]{64}$",
                                               "description": "Returned once. Retain securely; required with API bearer token to retrieve the original itinerary."}}},
    "MobilityOrigin": {"type": "object", "additionalProperties": False,
        "required": ["scenario_id", "dataset_version_id", "base_input", "base_sha256",
                     "source_canonical_json", "source_sha256", "compiler_version",
                     "compiler_source_sha256", "compiler_pydantic_version"],
        "properties": {"scenario_id": {"type": "string", "format": "uuid"},
                       "dataset_version_id": {"type": "string", "format": "uuid"},
                       "base_input": ref("ScenarioSpec"),
                       "base_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "source_canonical_json": {"type": "string"},
                       "source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "compiler_version": {"type": "string"},
                       "compiler_source_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "compiler_pydantic_version": {"type": "string"}}},
    "RunSpecV1": resolved_run_spec_v1,
    "RunSpecV2": resolved_run_spec_v2,
    "RunSpec": {"oneOf": [ref("RunSpecV1"), ref("RunSpecV2")]},
    "RunSpecOverridesV1": run_overrides_v1,
    "RunSpecOverridesV2": run_overrides_v2,
    "RunSpecOverrides": {"oneOf": [ref("RunSpecOverridesV1"), ref("RunSpecOverridesV2")]},
    "ImprovementIteration": {"type": "object", "required": ["iteration"],
        "properties": {"iteration": {"type": "integer", "minimum": 0, "maximum": 3},
                       "forced_site_id": {"type": ["string", "null"]},
                       "optimization_status": {"type": "string"},
                       "physical_verification_passed": {"type": "boolean"},
                       "development_score": {"type": ["number", "null"]},
                       "development": {"type": "object"},
                       "status": {"type": "string"}, "reason": {"type": "string"},
                       "selected_for_holdout": {"type": "boolean"}}},
    "ImprovementTrace": {"type": "object", "required": ["method", "development_seeds",
        "holdout_seeds_used_for_selection", "iterations"],
        "properties": {"method": {"type": "string"},
                       "development_seeds": {"type": "array", "items": {"type": "integer"}},
                       "holdout_seeds_used_for_selection": {"const": False},
                       "iterations": {"type": "array", "items": ref("ImprovementIteration")}}},
    "RunRequest": {"type": "object", "additionalProperties": False,
                   "properties": {"run_spec": ref("RunSpecOverrides")}},
    "Error": {"type": "object", "required": ["code", "detail"], "properties": {
        "code": {"type": "string"}, "detail": {"type": "string"}}},
    "SavedScenario": {"type": "object", "required": ["id", "name", "spec"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "name": {"type": "string"},
        "spec": ref("ScenarioSpec"), "sha256": {"type": "string"}}},
    "ScenarioSummary": {"type": "object", "required": ["id", "name", "sha256", "created_at"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "name": {"type": "string"},
        "sha256": {"type": "string"}, "created_at": {"type": "string", "format": "date-time"}}},
    "Run": {"type": "object", "required": ["id", "state", "run_spec", "run_spec_sha256", "scenario_sha256", "execution_sha256", "run_spec_origin"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "scenario_id": {"type": "string", "format": "uuid"},
        "state": {"type": "string", "enum": ["queued", "running", "succeeded", "failed", "cancelled"]},
        "attempts": {"type": "integer"}, "error_code": {"type": ["string", "null"]},
        "error_detail": {"type": ["string", "null"]},
        "run_spec": ref("RunSpec"),
        "run_spec_origin": {"type": "string", "enum": ["resolved", "legacy_inferred"]},
        **{name: {"type": "string", "pattern": "^[0-9a-f]{64}$"} for name in
           ("run_spec_sha256", "scenario_sha256", "execution_sha256")},
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"}}},
    "RiskMetrics": {"type": "object", "properties": {
        "cvar_alpha": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "cvar_loss_rub": {"type": "number", "minimum": 0},
        "cvar_unmet_kwh": {"type": "number", "minimum": 0}}},
    "InvestmentYear": {"type": "object", "required": ["year", "rub"], "properties": {
        "year": {"type": "integer"}, "rub": {"type": "number", "minimum": 0}}},
    "ServiceYear": {"type": "object", "required": [
        "scenario_id", "year", "demand_kwh", "served_kwh", "unmet_kwh"],
        "properties": {"scenario_id": {"type": "string"}, "year": {"type": "integer"},
                       "demand_kwh": {"type": "number", "minimum": 0},
                       "served_kwh": {"type": "number", "minimum": 0},
                       "unmet_kwh": {"type": "number", "minimum": 0}}},
    "EnergyAudit": {"type": "object", "required": [
        "scenario_id", "year", "site_id", "served_kwh", "grid_kwh", "pv_used_kwh",
        "pv_available_kwh", "battery_charge_kwh", "battery_discharge_kwh",
        "peak_grid_kw", "peak_station_kw", "battery_soc_start_kwh", "battery_soc_end_kwh"],
        "properties": {**{name: {"type": "number", "minimum": 0} for name in (
            "served_kwh", "grid_kwh", "pv_used_kwh", "pv_available_kwh",
            "battery_charge_kwh", "battery_discharge_kwh", "peak_grid_kw", "peak_station_kw",
            "battery_soc_start_kwh", "battery_soc_end_kwh")},
            "scenario_id": {"type": "string"}, "site_id": {"type": "string"}, "year": {"type": "integer"}}},
    "PhysicalVerification": {"type": "object", "properties": {
        **{name: {"type": "number", "minimum": 0} for name in (
            "max_hourly_energy_balance_error_kwh", "max_relative_energy_balance_error",
            "max_grid_node_overload_kw", "max_station_connection_overload_kw",
            "max_station_equipment_overload_kw", "max_pv_overuse_kw",
            "max_budget_overrun_rub", "max_service_floor_shortfall_kwh")},
        "energy_audit_rows_total": {"type": "integer", "minimum": 0},
        "energy_audit_truncated": {"type": "boolean"}, "passed": {"type": "boolean"}}},
    "DispatchSite": {"type": "object", "required": [
        "site_id", "load_kwh", "grid_kwh", "pv_used_kwh", "pv_curtailed_kwh",
        "battery_charge_kwh", "battery_discharge_kwh", "battery_soc_start_kwh",
        "battery_soc_end_kwh"],
        "properties": {"site_id": {"type": "string"},
            **{name: {"type": "number", "minimum": 0} for name in (
                "load_kwh", "grid_kwh", "pv_used_kwh", "pv_curtailed_kwh",
                "battery_charge_kwh", "battery_discharge_kwh",
                "battery_soc_start_kwh", "battery_soc_end_kwh")}}},
    "DispatchVerification": {"type": "object", "required": [
        "passed", "max_energy_balance_error_kwh_per_minute", "max_grid_node_overload_kw",
        "max_station_connection_overload_kw", "max_equipment_overload_kw",
        "max_storage_soc_violation_kwh", "max_simultaneous_storage_kw",
        "session_dispatch_energy_mismatch_kwh", "storage_energy_balance_error_kwh"],
        "properties": {"passed": {"type": "boolean"},
            **{name: {"type": "number", "minimum": 0} for name in (
                "max_energy_balance_error_kwh_per_minute", "max_grid_node_overload_kw",
                "max_station_connection_overload_kw", "max_equipment_overload_kw",
                "max_storage_soc_violation_kwh", "max_simultaneous_storage_kw",
                "session_dispatch_energy_mismatch_kwh", "storage_energy_balance_error_kwh")}}},
    "DayDispatch": {"type": "object", "required": ["day_index", "arrivals", "dispatch_by_site",
        "charging_sessions_at_boundary", "queued_sessions_at_boundary"], "properties": {
        "day_index": {"type": "integer", "minimum": 0},
        "arrivals": {"type": "integer", "minimum": 0},
        "dispatch_by_site": {"type": "array", "items": ref("DispatchSite")},
        "charging_sessions_at_boundary": {"type": "integer", "minimum": 0},
        "queued_sessions_at_boundary": {"type": "integer", "minimum": 0}}},
    "OptimizationResult": {"type": "object", "required": [
        "status", "objective", "gap", "selected", "grid_upgrades", "battery", "solar",
        "served_kwh", "unmet_kwh", "cashflow_rub", "diagnostic", "risk_metrics",
        "investment_rub_by_year", "service_by_year", "energy_audit", "verification"],
        "properties": {
            "status": {"type": "string", "enum": ["optimal", "feasible", "infeasible", "error"]},
            "objective": {"type": ["number", "null"]}, "gap": {"type": ["number", "null"]},
            "selected": {"type": "array", "items": {"type": "object",
                "required": ["site_id", "option_id", "year"], "properties": {
                    "site_id": {"type": "string"}, "option_id": {"type": "string"}, "year": {"type": "integer"}}}},
            "grid_upgrades": {"type": "array", "items": {"type": "object",
                "required": ["grid_node_id", "year", "commissioned_year"], "properties": {
                    "grid_node_id": {"type": "string"}, "year": {"type": "integer"},
                    "commissioned_year": {"type": "integer"}}}},
            "battery": {"type": "array", "items": {"type": "object",
                "required": ["site_id", "year", "kwh"], "properties": {
                    "site_id": {"type": "string"}, "year": {"type": "integer"}, "kwh": {"type": "number"}}}},
            "solar": {"type": "array", "items": {"type": "object",
                "required": ["site_id", "year", "kw"], "properties": {
                    "site_id": {"type": "string"}, "year": {"type": "integer"}, "kw": {"type": "number"}}}},
            "served_kwh": {"type": "object", "additionalProperties": {"type": "number"}},
            "unmet_kwh": {"type": "object", "additionalProperties": {"type": "number"}},
            "cashflow_rub": {"type": "object", "additionalProperties": {"type": "number"}},
            "diagnostic": {"type": ["string", "null"]}, "risk_metrics": ref("RiskMetrics"),
            "investment_rub_by_year": {"type": "array", "items": ref("InvestmentYear")},
            "service_by_year": {"type": "array", "items": ref("ServiceYear")},
            "energy_audit": {"type": "array", "items": ref("EnergyAudit")},
            "verification": ref("PhysicalVerification")}},
    "SimulationResult": {"type": "object", "required": [
        "year", "scenario_id", "seed", "simulation_days", "arrivals", "served_sessions", "refused_sessions",
        "arrivals_by_hour", "arrivals_by_day_hour", "day_dispatch", "requested_energy_kwh", "unserved_energy_kwh",
        "mean_wait_minutes", "p95_wait_minutes", "energy_kwh", "partial_energy_kwh",
        "last_completion_minute", "served_by_zone", "refused_by_zone", "energy_by_site_kwh",
        "dispatch_by_site", "dispatch_verification", "assumptions"],
        "properties": {
            "year": {"type": "integer"}, "scenario_id": {"type": "string"}, "seed": {"type": "integer"},
            "simulation_days": {"type": "integer", "minimum": 1, "maximum": 14},
            "arrivals": {"type": "integer", "minimum": 0},
            "served_sessions": {"type": "integer", "minimum": 0},
            "refused_sessions": {"type": "integer", "minimum": 0},
            "arrivals_by_hour": {"type": "array", "minItems": 24, "maxItems": 24,
                                 "items": {"type": "integer", "minimum": 0}},
            "arrivals_by_day_hour": {"type": "array", "minItems": 1, "maxItems": 14,
                "items": {"type": "array", "minItems": 24, "maxItems": 24,
                          "items": {"type": "integer", "minimum": 0}}},
            "day_dispatch": {"type": "array", "minItems": 1, "maxItems": 14,
                             "items": ref("DayDispatch")},
            "requested_energy_kwh": {"type": "number", "minimum": 0},
            "unserved_energy_kwh": {"type": "number", "minimum": 0},
            "mean_wait_minutes": {"type": ["number", "null"], "minimum": 0},
            "p95_wait_minutes": {"type": ["number", "null"], "minimum": 0},
            "energy_kwh": {"type": "number", "minimum": 0},
            "partial_energy_kwh": {"type": "number", "minimum": 0},
            "last_completion_minute": {"type": ["number", "null"], "minimum": 0, "maximum": 20160},
            "served_by_zone": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
            "refused_by_zone": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
            "energy_by_site_kwh": {"type": "object", "additionalProperties": {"type": "number", "minimum": 0}},
            "dispatch_by_site": {"type": "array", "items": ref("DispatchSite")},
            "dispatch_verification": ref("DispatchVerification"),
            "assumptions": {"type": "array", "items": {"type": "string"}}}},
    "OperationalValidation": {"type": "object", "required": [
        "scenario_id", "year", "seeds", "optimized_service_fraction",
        "simulated_service_fraction_mean", "simulated_service_fraction_min",
        "simulated_service_fraction_max", "service_gap_percentage_points",
        "simulation_days", "requested_energy_kwh_mean", "delivered_energy_kwh_mean", "unserved_energy_kwh_mean"],
        "properties": {
            "scenario_id": {"type": "string"}, "year": {"type": "integer"},
            "seeds": {"type": "integer", "minimum": 1},
            "simulation_days": {"type": "integer", "minimum": 1, "maximum": 14},
            **{name: {"type": "number", "minimum": 0, "maximum": 1} for name in (
                "optimized_service_fraction", "simulated_service_fraction_mean",
                "simulated_service_fraction_min", "simulated_service_fraction_max")},
            "service_gap_percentage_points": {"type": "number"},
            **{name: {"type": "number", "minimum": 0} for name in (
                "requested_energy_kwh_mean", "delivered_energy_kwh_mean",
                "unserved_energy_kwh_mean")}}},
    "OperationalEconomics": {"type": "object", "required": [
        "scenario_id", "seeds", "optimized_npv_rub", "simulated_npv_rub_mean",
        "simulated_npv_rub_min", "simulated_npv_rub_max", "optimism_gap_rub",
        "profitability_sign_changed"],
        "properties": {"scenario_id": {"type": "string"},
                       "seeds": {"type": "integer", "minimum": 1},
                       **{name: {"type": "number"} for name in (
                           "optimized_npv_rub", "simulated_npv_rub_mean",
                           "simulated_npv_rub_min", "simulated_npv_rub_max", "optimism_gap_rub")},
                       "profitability_sign_changed": {"type": "boolean"}}},
    "AlternativePlan": {"type": "object", "required": [
        "target_service_fraction", "objective_kind", "achieved_min_service_fraction",
        "same_investment_as_target",
        "optimization", "simulation", "operational_validation", "operational_economics"],
        "properties": {"target_service_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                       "objective_kind": {"const": "minimum_investment_rub"},
                       "achieved_min_service_fraction": {"type": ["number", "null"],
                                                         "minimum": 0, "maximum": 1},
                       "same_investment_as_target": {"type": ["number", "null"],
                                                     "minimum": 0, "maximum": 1},
                       "optimization": ref("OptimizationResult"),
                       "simulation": {"type": "array", "items": ref("SimulationResult")},
                       "operational_validation": {"type": "array", "items": ref("OperationalValidation")},
                       "operational_economics": {"type": "array", "items": ref("OperationalEconomics")},
                       "service_acceptance": ref("ServiceAcceptance")}},
    "ServiceAcceptance": {"type": "object", "required": ["status", "reason"],
                          "description": "Assessment of simulated streams, not external validation of assumptions.",
                          "properties": {"status": {"type": "string", "enum": ["accepted", "rejected", "inconclusive", "not_evaluated"]},
                                         "reason": {"type": "string"},
                                         "method": {"type": "string"},
                                         "confidence_level": {"type": "number"},
                                         "interval_scope": {"type": "string"},
                                         "requirements": ref("ServiceRequirements"),
                                         "conditions": {"type": "array", "items": {"type": "object"}}}},
    "RunMetadata": {"type": "object", "description": "Current calculations include these fields; historical results may omit them.",
                    "properties": {
                        "run_spec": {"oneOf": [ref("RunSpec"), {"type": "null"}]},
                        "configuration_source": {"type": "string", "enum": ["run_spec", "legacy_fields"]},
                        **{name: {"type": "string", "pattern": "^[0-9a-f]{64}$"} for name in (
                            "engine_request_sha256", "source_input_sha256", "input_sha256",
                            "scenario_snapshot_sha256", "run_spec_sha256", "execution_sha256",
                            "engine_source_sha256", "demand_dataset_sha256")},
                        "engine_source_files": {"type": "array", "items": {"type": "string"}},
                        "simulation_seeds": {"type": "array", "items": {"type": "integer"}},
                        "simulation_days": {"type": "integer"}, "solver_seconds": {"type": "integer"}}},
    "PlanResult": {"type": "object", "required": ["optimization", "simulation", "operational_validation", "operational_economics", "explanations", "alternatives", "metadata"],
                   "properties": {"optimization": ref("OptimizationResult"),
                                  "service_acceptance": ref("ServiceAcceptance"),
                                  "improvement": ref("ImprovementTrace"),
                                  "simulation": {"type": "array", "items": ref("SimulationResult")},
                                  "operational_validation": {"type": "array", "items": ref("OperationalValidation")},
                                  "operational_economics": {"type": "array", "items": ref("OperationalEconomics")},
                                  "explanations": {"type": "array", "items": {"type": "object"}},
                                  "alternatives": {"type": "array", "items": ref("AlternativePlan")},
                                  "metadata": ref("RunMetadata")}},
    "DatasetManifest": {"type": "object", "required": ["id", "name", "kind", "source", "checksum", "created_at", "format"],
                        "properties": {"id": {"type": "string", "format": "uuid"},
                                       "name": {"type": "string"}, "kind": {"type": "string", "enum": ["observed", "derived", "assumed"]},
                                       "source": {"type": "string"}, "license": {"type": ["string", "null"]},
                                       "checksum": {"type": "string"},
                                       "format": {"type": "string", "enum": ["geojson", "csv", "mobility"]},
                                       "role": {"type": "string", "enum": ["demand_sessions", "grid_headroom", "mobility_source"]},
                                       "captured_at": {"type": ["string", "null"], "format": "date-time"},
                                       "created_at": {"type": "string", "format": "date-time"}}},
    "DatasetImportResult": {"type": "object", "required": ["dataset_id", "features", "sha256"],
        "properties": {"dataset_id": {"type": "string", "format": "uuid"},
                       "features": {"type": "integer", "minimum": 1}, "sha256": {"type": "string"}}},
    "DatasetSelection": {"type": "object", "additionalProperties": False,
        "required": ["demand_zones", "candidate_sites", "grid_nodes", "travel_edges"],
        "properties": {name: {"type": "string", "format": "uuid"} for name in
                       ("demand_zones", "candidate_sites", "grid_nodes", "travel_edges")}},
    "DatasetScenarioRequest": {"type": "object", "additionalProperties": False,
        "required": ["name", "input_id", "time_zone", "dataset_versions", "options", "parameters", "scenarios"],
        "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120},
                       "input_id": {"type": "string", "minLength": 1, "maxLength": 200},
                       "time_zone": {"type": "string", "maxLength": 128,
                                     "description": "IANA zone shared by demand and grid hourly profiles"},
                       "dataset_versions": ref("DatasetSelection"),
                       "options": {"type": "array", "items": ref("ChargerOption")},
                       "parameters": ref("Parameters"),
                       "scenarios": {"type": "array", "items": ref("Scenario")},
                       "locked_site_ids": {"type": "array", "items": {"type": "string"}},
                       "excluded_site_ids": {"type": "array", "items": {"type": "string"}}}},
    "DatasetUse": {"type": "object", "required": [
        "role", "version_id", "name", "kind", "source", "sha256", "feature_count"],
        "properties": {"role": {"type": "string"}, "version_id": {"type": "string", "format": "uuid"},
                       "name": {"type": "string"}, "kind": {"type": "string", "enum": ["observed", "derived", "assumed"]},
                       "source": {"type": "string"}, "sha256": {"type": "string"},
                       "license": {"type": ["string", "null"]},
                       "captured_at": {"type": ["string", "null"], "format": "date-time"},
                       "feature_count": {"type": "integer", "minimum": 1}}},
    "DataQuality": {"type": "object", "required": ["datasets", "warnings"],
        "properties": {"datasets": {"type": "array", "items": ref("DatasetUse")},
                       "warnings": {"type": "array", "items": {"type": "string"}}}},
    "PreparedDatasetScenario": {"type": "object", "required": ["spec", "data_quality"],
        "properties": {"spec": ref("ScenarioSpec"), "data_quality": ref("DataQuality")}},
    "SavedDatasetScenario": {"type": "object", "required": ["scenario", "data_quality"],
        "properties": {"scenario": ref("SavedScenario"), "data_quality": ref("DataQuality")}},
    "PlanningCSVImportResult": {"type": "object", "required": [
        "scenario", "dataset_id", "role", "sha256", "reused"],
        "properties": {"scenario": ref("SavedScenario"),
                       "dataset_id": {"type": "string", "format": "uuid"},
                       "role": {"type": "string", "enum": ["demand_sessions", "grid_headroom"]},
                       "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                       "reused": {"type": "boolean"}}},
}

uuid_param = {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}
error_responses = {"401": response(ref("Error"), "Authentication required"),
                   "422": response(ref("Error"), "Invalid input")}
spec_create = {"type": "object", "required": ["name", "spec"], "properties": {
    "name": {"type": "string", "minLength": 1, "maxLength": 120}, "spec": ref("ScenarioSpec")}}


def planning_csv_import(role: str) -> dict:
    common = {"scenario_name": {"type": "string", "minLength": 1, "maxLength": 120},
              "dataset_name": {"type": "string", "minLength": 1, "maxLength": 120},
              "source": {"type": "string", "minLength": 1, "maxLength": 2048},
              "kind": {"type": "string", "enum": ["observed", "assumed"]},
              "time_zone": {"type": "string", "description": "IANA zone; must match scenario time_zone if set"},
              "license": {"type": "string", "maxLength": 2048},
              "file": {"type": "string", "format": "binary"}}
    if role == "demand_sessions":
        common.update({"start_date": {"type": "string", "format": "date"},
                       "end_date": {"type": "string", "format": "date"},
                       "coverage_complete": {"type": "boolean", "default": False,
                           "description": "Importer asserts every zone and calendar day is covered, including zero-session days. Required to accept days with no records."}})
    else:
        common["profile_date"] = {"type": "string", "format": "date"}
    required = ["scenario_name", "dataset_name", "source", "kind", "time_zone", "file"]
    required += ["start_date", "end_date"] if role == "demand_sessions" else ["profile_date"]
    return {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "additionalProperties": False,
        "required": required, "properties": common}}}}

document = {
    "openapi": "3.1.0",
    "info": {"title": "Энергоконтур API", "version": "1.0.0",
             "description": "Public scenario, run and geography API. Engine coordinates and money are explicit in ScenarioSpec."},
    "servers": [{"url": "http://localhost:58080"}],
    "security": [{"bearerAuth": []}],
    "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer"}}, "schemas": schemas},
    "paths": {
        "/healthz": {"get": {"security": [], "summary": "Process health", "responses": {"200": response({"type": "object"})}}},
        "/readyz": {"get": {"security": [], "summary": "Database readiness", "responses": {"200": response({"type": "object"})}}},
        "/api/v1/scenarios": {
            "get": {"summary": "List saved scenario snapshots", "responses": {
                "200": response({"type": "array", "items": ref("ScenarioSummary")}), **error_responses}},
            "post": {"summary": "Validate and create immutable scenario", "requestBody": body(spec_create),
                "responses": {"201": response(ref("SavedScenario")), **error_responses}}},
        "/api/v1/artifacts/demand": {"post": {
            "summary": "Upload immutable dated charging demand",
            "description": "Stores the exact JSON bytes under their SHA-256 content address. The returned DemandDataset manifest can be placed in ScenarioSpec.demand_dataset without inline service_calendar or charging_requests. Go verifies and hydrates it for validation and again before handing a run to the engine. Requires ARTIFACT_DIR shared by API and worker; no arbitrary URLs are accepted.",
            "requestBody": body(ref("DemandArtifactDocument")),
            "responses": {"201": response(ref("DemandDataset")),
                          "413": response(ref("Error"), "Artifact exceeds 64 MiB"),
                          "422": response(ref("Error"), "Invalid artifact envelope"),
                          "503": response(ref("Error"), "Artifact storage unavailable"),
                          **error_responses}}},
        "/api/v1/scenarios/from-datasets/preview": {"post": {
            "summary": "Validate exact imported versions and preview a planning input without saving",
            "requestBody": body(ref("DatasetScenarioRequest")),
            "responses": {"200": response(ref("PreparedDatasetScenario")),
                          "404": response(ref("Error")), "503": response(ref("Error")), **error_responses}}},
        "/api/v1/scenarios/from-mobility/preview": {"post": {
            "summary": "Derive potential public charging requests from an explicit vehicle itinerary",
            "description": "Returns an unsaved PlanningInput and physical audit. The 24-hour hourly_kwh is the mean over explicitly covered local dates; calendar_profiles are diagnostic and do not yet drive multiday optimization or simulation. Assumed public charging in the projection is not actual service. Persist the returned spec through POST /api/v1/scenarios before running it.",
            "requestBody": body(ref("MobilityCompileRequest")),
            "responses": {"200": response(ref("PreparedMobilityScenario")),
                          "400": response(ref("Error"), "Malformed JSON"),
                          "413": response(ref("Error"), "Request exceeds 4 MiB"),
                          "502": response(ref("Error"), "Invalid engine output"),
                          "503": response(ref("Error"), "Compiler unavailable"),
                          **error_responses}}},
        "/api/v1/scenarios/from-mobility": {"post": {
            "summary": "Compile and atomically save a mobility-derived scenario and its source",
            "description": "Stores the compiled scenario, exact pre-transformation input and canonical itinerary. source_access_token is returned only once; retain it securely to retrieve the sensitive source later. An API bearer token is also required. The endpoint does not start optimization.",
            "requestBody": body(ref("MobilityCreateRequest")),
            "responses": {"201": response(ref("SavedMobilityScenario")),
                          "400": response(ref("Error"), "Malformed JSON"),
                          "413": response(ref("Error"), "Request exceeds 4 MiB"),
                          "502": response(ref("Error"), "Invalid engine output"),
                          "503": response(ref("Error"), "Compiler unavailable"),
                          **error_responses}}},
        "/api/v1/scenarios/from-datasets": {"post": {
            "summary": "Assemble and save an immutable scenario from exact imported versions",
            "requestBody": body(ref("DatasetScenarioRequest")),
            "responses": {"201": response(ref("SavedDatasetScenario")),
                          "404": response(ref("Error")), "503": response(ref("Error")), **error_responses}}},
        "/api/v1/scenarios/{id}": {"get": {"summary": "Get scenario", "parameters": [uuid_param],
            "responses": {"200": response(ref("SavedScenario")), "404": response(ref("Error")), **error_responses}}},
        "/api/v1/scenarios/{id}/mobility-origin": {"get": {
            "summary": "Retrieve the canonical mobility source and pre-transformation scenario",
            "description": "Requires both the API bearer token and the 256-bit source capability returned by POST /from-mobility. A missing or invalid capability returns 404 without revealing whether an origin exists.",
            "parameters": [uuid_param, {"name": "X-Mobility-Source-Token", "in": "header", "required": True,
                                       "schema": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}],
            "responses": {"200": response(ref("MobilityOrigin")), "404": response(ref("Error")),
                          **error_responses}}},
        "/api/v1/scenarios/{id}/imports/sessions": {"post": {
            "summary": "Derive an immutable scenario from uploaded charging sessions CSV",
            "description": "Sessions are completed charging, not latent unmet demand. The original CSV bytes are stored under dataset_id. Upload does not start a calculation; use the new scenario id with /runs.",
            "parameters": [uuid_param], "requestBody": planning_csv_import("demand_sessions"),
            "responses": {"201": response(ref("PlanningCSVImportResult")),
                          "404": response(ref("Error")), "413": response(ref("Error")),
                          "503": response(ref("Error")), **error_responses}}},
        "/api/v1/scenarios/{id}/imports/grid-headroom": {"post": {
            "summary": "Derive an immutable scenario from uploaded hourly grid headroom CSV",
            "description": "Requires all 24 hours for each grid node. headroom_kw is available connection reserve, not background load or AC power-flow verification.",
            "parameters": [uuid_param], "requestBody": planning_csv_import("grid_headroom"),
            "responses": {"201": response(ref("PlanningCSVImportResult")),
                          "404": response(ref("Error")), "413": response(ref("Error")),
                          "503": response(ref("Error")), **error_responses}}},
        "/api/v1/scenarios/{id}/runs": {"post": {"summary": "Queue idempotent calculation",
            "description": "An empty body or {} keeps legacy defaults. The resolved RunSpec is stored with the run. Reusing the key with different resolved parameters returns 409.",
            "requestBody": {"required": False, "content": {"application/json": {"schema": ref("RunRequest")}}},
            "parameters": [uuid_param, {"name": "Idempotency-Key", "in": "header", "required": True,
                                       "schema": {"type": "string", "minLength": 8, "maxLength": 128}}],
            "responses": {"202": response(ref("Run")), "400": response(ref("Error")), "404": response(ref("Error")),
                          "409": response(ref("Error"), "Idempotency key already used with different parameters"),
                          "413": response(ref("Error"), "Request exceeds 16 KiB"), **error_responses}}},
        "/api/v1/runs/{id}": {"get": {"summary": "Get run state", "parameters": [uuid_param],
            "responses": {"200": response(ref("Run")), "404": response(ref("Error")), **error_responses}}},
        "/api/v1/runs/{id}/cancel": {"post": {"summary": "Cancel queued or running run", "parameters": [uuid_param],
            "responses": {"200": response({"type": "object"}), "409": response(ref("Error")), **error_responses}}},
        "/api/v1/runs/{id}/results": {"get": {"summary": "Get completed plan and simulation", "parameters": [uuid_param],
            "responses": {"200": response(ref("PlanResult")), "404": response(ref("Error")), **error_responses}}},
        "/api/v1/runs/{id}/events": {"get": {"summary": "SSE stream with Last-Event-ID replay",
            "parameters": [uuid_param, {"name": "Last-Event-ID", "in": "header", "schema": {"type": "integer"}}],
            "responses": {"200": {"description": "Run events", "content": {"text/event-stream": {"schema": {"type": "string"}}}},
                          "404": response(ref("Error")), **error_responses}}},
        "/api/v1/datasets": {"get": {"summary": "List imported dataset versions",
            "responses": {"200": response({"type": "array", "items": ref("DatasetManifest")}), **error_responses}}},
        "/api/v1/datasets/import": {"post": {
            "summary": "Atomically import a versioned GeoJSON FeatureCollection",
            "requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
                "type": "object", "required": ["name", "kind", "source", "file"],
                "properties": {"name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "kind": {"type": "string", "enum": ["observed", "derived", "assumed"]},
                    "source": {"type": "string", "minLength": 1, "maxLength": 2048},
                    "license": {"type": "string", "maxLength": 2048},
                    "captured_at": {"type": "string", "format": "date-time",
                                    "description": "Required for observed imports"},
                    "file": {"type": "string", "format": "binary"}}}}}},
            "responses": {"201": response(ref("DatasetImportResult")),
                          "413": response(ref("Error")), **error_responses}}},
        "/api/v1/datasets/{id}/file": {"get": {
            "summary": "Download exact original CSV bytes of a planning data upload",
            "parameters": [uuid_param], "responses": {
                "200": {"description": "Uploaded CSV", "content": {"text/csv": {
                    "schema": {"type": "string", "format": "binary"}}}},
                "404": response(ref("Error")), **error_responses}}},
        "/api/v1/map": {"get": {"summary": "GeoJSON in bounding box", "parameters": [
            {"name": "bbox", "in": "query", "required": True, "schema": {"type": "string"},
             "description": "west,south,east,north in WGS84"},
            {"name": "type", "in": "query", "schema": {"type": "string"}}],
            "responses": {"200": {"description": "FeatureCollection", "content": {"application/geo+json": {"schema": {"type": "object"}}}}, **error_responses}}},
        "/api/v1/tiles/{z}/{x}/{y}": {"get": {"summary": "PostGIS vector tile", "parameters": [
            {"name": axis, "in": "path", "required": True, "schema": {"type": "integer"}} for axis in ("z", "x", "y")],
            "responses": {"200": {"description": "Mapbox Vector Tile", "content": {
                "application/vnd.mapbox-vector-tile": {"schema": {"type": "string", "format": "binary"}}}}, **error_responses}}},
        "/api/v1/corridors/check": {"post": {"summary": "Check route reachability and station outages",
            "requestBody": body(ref("CorridorSpec")),
            "responses": {"200": response({"type": "object"}), **error_responses}}},
        "/api/v1/fleets/schedule": {"post": {"summary": "Schedule charging for an assigned vehicle fleet",
            "requestBody": body(ref("FleetSpec")),
            "responses": {"200": response({"type": "object"}), **error_responses}}},
    },
}

target = ROOT / "openapi.json"
target.write_bytes((json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
print(target)
