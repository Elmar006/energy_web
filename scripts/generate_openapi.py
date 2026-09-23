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
    "Run": {"type": "object", "required": ["id", "state"], "properties": {
        "id": {"type": "string", "format": "uuid"}, "scenario_id": {"type": "string", "format": "uuid"},
        "state": {"type": "string", "enum": ["queued", "running", "succeeded", "failed", "cancelled"]},
        "attempts": {"type": "integer"}, "error_code": {"type": ["string", "null"]},
        "error_detail": {"type": ["string", "null"]}}},
    "PlanResult": {"type": "object", "required": ["optimization", "simulation", "explanations", "metadata"],
                   "properties": {"optimization": {"type": "object"},
                                  "simulation": {"type": "array", "items": {"type": "object"}},
                                  "explanations": {"type": "array", "items": {"type": "object"}},
                                  "metadata": {"type": "object"}}},
    "DatasetManifest": {"type": "object", "required": ["id", "name", "kind", "source", "checksum"],
                        "properties": {"id": {"type": "string", "format": "uuid"},
                                       "name": {"type": "string"}, "kind": {"type": "string", "enum": ["observed", "derived", "assumed"]},
                                       "source": {"type": "string"}, "license": {"type": ["string", "null"]},
                                       "checksum": {"type": "string"}}},
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
        "/api/v1/scenarios": {"post": {"summary": "Create immutable scenario", "requestBody": body(spec_create),
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
