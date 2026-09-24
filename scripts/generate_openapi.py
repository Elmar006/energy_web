"""Generate the public Go API contract from the engine's validated scenario schema."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from energy.contracts import PlanningInput  # noqa: E402
from energy.corridor import CorridorInput  # noqa: E402
from energy.fleet import FleetInput  # noqa: E402


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
schemas = {
    **definitions,
    "ScenarioSpec": planning,
    "CorridorSpec": corridor,
    "FleetSpec": fleet,
    "Error": {"type": "object", "required": ["code", "detail"], "properties": {
        "code": {"type": "string"}, "detail": {"type": "string"}}},
    "SavedScenario": {"type": "object", "required": ["id", "name", "spec"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "name": {"type": "string"},
        "spec": ref("ScenarioSpec"), "sha256": {"type": "string"}}},
    "ScenarioSummary": {"type": "object", "required": ["id", "name", "sha256", "created_at"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "name": {"type": "string"},
        "sha256": {"type": "string"}, "created_at": {"type": "string", "format": "date-time"}}},
    "Run": {"type": "object", "required": ["id", "state"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "scenario_id": {"type": "string", "format": "uuid"},
        "state": {"type": "string", "enum": ["queued", "running", "succeeded", "failed", "cancelled"]},
        "attempts": {"type": "integer"}, "error_code": {"type": ["string", "null"]},
        "error_detail": {"type": ["string", "null"]}}},
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
        "year", "scenario_id", "seed", "arrivals", "served_sessions", "refused_sessions",
        "mean_wait_minutes", "p95_wait_minutes", "energy_kwh", "partial_energy_kwh",
        "last_completion_minute", "served_by_zone", "refused_by_zone", "energy_by_site_kwh", "assumptions"],
        "properties": {
            "year": {"type": "integer"}, "scenario_id": {"type": "string"}, "seed": {"type": "integer"},
            "arrivals": {"type": "integer", "minimum": 0},
            "served_sessions": {"type": "integer", "minimum": 0},
            "refused_sessions": {"type": "integer", "minimum": 0},
            "mean_wait_minutes": {"type": ["number", "null"], "minimum": 0},
            "p95_wait_minutes": {"type": ["number", "null"], "minimum": 0},
            "energy_kwh": {"type": "number", "minimum": 0},
            "partial_energy_kwh": {"type": "number", "minimum": 0},
            "last_completion_minute": {"type": ["number", "null"], "minimum": 0, "maximum": 1440},
            "served_by_zone": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
            "refused_by_zone": {"type": "object", "additionalProperties": {"type": "integer", "minimum": 0}},
            "energy_by_site_kwh": {"type": "object", "additionalProperties": {"type": "number", "minimum": 0}},
            "assumptions": {"type": "array", "items": {"type": "string"}}}},
    "AlternativePlan": {"type": "object", "required": [
        "target_service_fraction", "objective_kind", "achieved_min_service_fraction",
        "same_investment_as_target",
        "optimization", "simulation"],
        "properties": {"target_service_fraction": {"type": "number", "minimum": 0, "maximum": 1},
                       "objective_kind": {"const": "minimum_investment_rub"},
                       "achieved_min_service_fraction": {"type": ["number", "null"],
                                                         "minimum": 0, "maximum": 1},
                       "same_investment_as_target": {"type": ["number", "null"],
                                                     "minimum": 0, "maximum": 1},
                       "optimization": ref("OptimizationResult"),
                       "simulation": {"type": "array", "items": ref("SimulationResult")}}},
    "PlanResult": {"type": "object", "required": ["optimization", "simulation", "explanations", "alternatives", "metadata"],
                   "properties": {"optimization": ref("OptimizationResult"),
                                  "simulation": {"type": "array", "items": ref("SimulationResult")},
                                  "explanations": {"type": "array", "items": {"type": "object"}},
                                  "alternatives": {"type": "array", "items": ref("AlternativePlan")},
                                  "metadata": {"type": "object"}}},
    "DatasetManifest": {"type": "object", "required": ["id", "name", "kind", "source", "checksum", "created_at"],
                        "properties": {"id": {"type": "string", "format": "uuid"},
                                       "name": {"type": "string"}, "kind": {"type": "string", "enum": ["observed", "derived", "assumed"]},
                                       "source": {"type": "string"}, "license": {"type": ["string", "null"]},
                                       "checksum": {"type": "string"},
                                       "captured_at": {"type": ["string", "null"], "format": "date-time"},
                                       "created_at": {"type": "string", "format": "date-time"}}},
}

uuid_param = {"name": "id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}}
error_responses = {"401": response(ref("Error"), "Authentication required"),
                   "422": response(ref("Error"), "Invalid input")}
spec_create = {"type": "object", "required": ["name", "spec"], "properties": {
    "name": {"type": "string", "minLength": 1, "maxLength": 120}, "spec": ref("ScenarioSpec")}}

document = {
    "openapi": "3.1.0",
    "info": {"title": "Вектор — planning API", "version": "1.0.0",
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
        "/api/v1/scenarios/{id}": {"get": {"summary": "Get scenario", "parameters": [uuid_param],
            "responses": {"200": response(ref("SavedScenario")), "404": response(ref("Error")), **error_responses}}},
        "/api/v1/scenarios/{id}/runs": {"post": {"summary": "Queue idempotent calculation",
            "parameters": [uuid_param, {"name": "Idempotency-Key", "in": "header", "required": True,
                                       "schema": {"type": "string", "minLength": 8, "maxLength": 128}}],
            "responses": {"202": response(ref("Run")), "404": response(ref("Error")), **error_responses}}},
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
target.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(target)
