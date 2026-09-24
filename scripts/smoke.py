"""Exercise the deployed API, worker, solver, simulation, and explanations."""

from __future__ import annotations

import json
import os
import time
import uuid
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("ENERGY_API_URL", "http://127.0.0.1:58080").rstrip("/")
TOKEN = os.environ.get("API_TOKEN", "local-development-token-change-before-deploy")
FRONTEND = os.environ.get("ENERGY_FRONTEND_URL", "http://127.0.0.1:53001").rstrip("/")


def call(method: str, path: str, body: dict | None = None, *, key: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if key:
        headers["Idempotency-Key"] = key
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    with urlopen(Request(BASE + path, data=payload, headers=headers, method=method), timeout=30) as response:
        return json.load(response)


def main() -> None:
    ready_by = time.monotonic() + 90
    while True:
        try:
            if call("GET", "/readyz")["status"] == "ready":
                break
        except OSError:
            if time.monotonic() >= ready_by:
                raise
            time.sleep(2)
    spec = json.loads((ROOT / "examples" / "demo.json").read_text(encoding="utf-8"))
    scenario = call("POST", "/api/v1/scenarios", {"name": "smoke-test", "spec": spec})
    idempotency_key = str(uuid.uuid4())
    path = f"/api/v1/scenarios/{scenario['id']}/runs"
    run = call("POST", path, key=idempotency_key)
    repeated = call("POST", path, key=idempotency_key)
    assert repeated["id"] == run["id"], "idempotency broken"
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        current = call("GET", f"/api/v1/runs/{run['id']}")
        if current["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(2)
    else:
        raise AssertionError("run did not finish within 180 seconds")
    assert current["state"] == "succeeded", current
    result = call("GET", f"/api/v1/runs/{run['id']}/results")
    assert result["optimization"]["status"] in ("optimal", "feasible"), result
    assert result["optimization"]["verification"]["passed"] is True
    assert result["optimization"]["investment_rub_by_year"]
    assert result["optimization"]["service_by_year"]
    assert result["optimization"]["energy_audit"]
    assert result["optimization"]["selected"], "no sites selected"
    assert result["simulation"], "simulation missing"
    for sample in result["simulation"]:
        assert sample["arrivals"] == sample["served_sessions"] + sample["refused_sessions"]
        assert 0 <= sample["partial_energy_kwh"] <= sample["energy_kwh"]
        assert sample["last_completion_minute"] is None or sample["last_completion_minute"] <= 1440
    assert result["explanations"], "counterfactual explanation missing"
    assert [item["target_service_fraction"] for item in result["alternatives"]] == [0, 0.5, 1]
    for alternative in result["alternatives"]:
        assert "same_investment_as_target" in alternative
        optimization = alternative["optimization"]
        if optimization["status"] in ("optimal", "feasible"):
            assert optimization["verification"]["passed"] is True
            assert alternative["achieved_min_service_fraction"] is not None
            assert alternative["achieved_min_service_fraction"] + 1e-4 >= alternative["target_service_fraction"]
            assert alternative["simulation"]
            for sample in alternative["simulation"]:
                assert sample["seed"] in result["metadata"]["simulation_seeds"]
        else:
            assert alternative["simulation"] == []
    corridor = call("POST", "/api/v1/corridors/check", {
        "route_km": 300, "battery_usable_kwh": 60, "initial_soc": 1,
        "reserve_soc": 0.1, "consumption_kwh_per_km": 0.2,
        "consumption_multiplier": 1.5,
        "stations": [{"id": "a", "km": 100}, {"id": "b", "km": 200}],
    })
    assert corridor["reachable"] and corridor["stops"] == ["a", "b"]
    assert not corridor["station_failure_impacts"]["a"]["reachable"]
    fleet = call("POST", "/api/v1/fleets/schedule", {
        "slot_minutes": 15, "horizon_slots": 4,
        "buses": [{"id": bus, "battery_kwh": 20, "initial_kwh": 4, "minimum_kwh": 2}
                  for bus in ("bus-a", "bus-b")],
        "sites": [{"id": "depot", "ports": 1, "charger_kw": 10, "grid_kw": 10}],
        "trips": [{"id": f"trip-{bus}", "bus_id": f"bus-{bus}", "start_slot": 2,
                   "end_slot": 4, "energy_kwh": 4} for bus in ("a", "b")],
        "windows": [{"bus_id": f"bus-{bus}", "site_id": "depot", "start_slot": 0,
                     "end_slot": 2} for bus in ("a", "b")],
    })
    assert fleet["status"] == "optimal" and fleet["peak_kw"] <= 10, fleet
    browser = build_opener(HTTPCookieProcessor(CookieJar()))

    def frontend_call(method: str, path: str, body: dict | None = None) -> dict:
        payload = json.dumps(body).encode() if body is not None else None
        request = Request(FRONTEND + path, data=payload, method=method,
                          headers={"Content-Type": "application/json"})
        with browser.open(request, timeout=30) as response:
            return json.load(response)

    try:
        frontend_call("POST", "/api/runs", {"mode": "city", "budget": 10_000_000, "demand": 100})
        raise AssertionError("unauthenticated frontend run was accepted")
    except HTTPError as error:
        assert error.code == 401, error
    try:
        frontend_call("GET", "/api/maps/config")
        raise AssertionError("unauthenticated map configuration was exposed")
    except HTTPError as error:
        assert error.code == 401, error
    login = frontend_call("POST", "/api/session", {"password": os.environ.get("APP_DEMO_PASSWORD", "demo-local-password")})
    assert login["signed_in"]
    assert frontend_call("GET", "/api/session")["signed_in"]
    map_config = frontend_call("GET", "/api/maps/config")
    assert isinstance(map_config["configured"], bool)
    assert map_config["configured"] == bool(map_config.get("apiKey"))
    imported_spec = json.loads((ROOT / "examples" / "import_sample.json").read_text(encoding="utf-8"))
    broken_spec = json.loads(json.dumps(imported_spec))
    broken_spec["sites"][0]["grid_node_id"] = "unknown-grid"
    try:
        frontend_call("POST", "/api/scenarios", {"name": "broken", "spec": broken_spec})
        raise AssertionError("invalid planning input was saved")
    except HTTPError as error:
        assert error.code == 422, error
    imported = frontend_call("POST", "/api/scenarios", {"name": "Сценарий из файла · синтетический тест", "spec": imported_spec})
    assert imported["spec"]["id"] == imported_spec["id"]
    assert any(item["id"] == imported["id"] for item in frontend_call("GET", "/api/scenarios"))
    assert frontend_call("GET", f"/api/scenarios/{imported['id']}")["sha256"] == imported["sha256"]
    imported_run = frontend_call("POST", "/api/runs", {"scenario_id": imported["id"]})
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        imported_state = frontend_call("GET", f"/api/runs/{imported_run['run_id']}")
        if imported_state["run"]["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(2)
    else:
        raise AssertionError("imported scenario did not finish within 180 seconds")
    assert imported_state["run"]["state"] == "succeeded", imported_state
    assert imported_state["result"]["optimization"]["selected"][0]["site_id"] == "site-kazan-example"
    cvar_spec = json.loads(json.dumps(imported_spec))
    cvar_spec["id"] = "smoke-cvar-city"
    cvar_spec["scenarios"] = [
        {"id": "base", "demand_multiplier": [1], "probability": 0.9},
        {"id": "growth", "demand_multiplier": [2], "probability": 0.1},
    ]
    cvar_spec["parameters"].update({"risk": "expected_cvar", "cvar_alpha": 0.9,
                                    "max_cvar_unmet_kwh": 0})
    cvar_saved = call("POST", "/api/v1/scenarios", {"name": "smoke-cvar-city", "spec": cvar_spec})
    cvar_run = call("POST", f"/api/v1/scenarios/{cvar_saved['id']}/runs", key=str(uuid.uuid4()))
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        cvar_state = call("GET", f"/api/v1/runs/{cvar_run['id']}")
        if cvar_state["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(2)
    else:
        raise AssertionError("CVaR scenario did not finish")
    assert cvar_state["state"] == "succeeded", cvar_state
    cvar_result = call("GET", f"/api/v1/runs/{cvar_run['id']}/results")
    assert cvar_result["optimization"]["status"] == "optimal", cvar_result
    assert cvar_result["optimization"]["risk_metrics"]["cvar_unmet_kwh"] == 0
    assert cvar_result["alternatives"][2]["optimization"]["status"] in ("optimal", "feasible")
    extra_path = os.environ.get("ENERGY_EXTRA_SCENARIO")
    if extra_path:
        extra_spec = json.loads(Path(extra_path).read_text(encoding="utf-8"))
        assert any(dataset["role"] == "routing" and dataset["kind"] == "derived"
                   for dataset in extra_spec.get("datasets", [])), "extra scenario lacks routed dataset provenance"
        extra = call("POST", "/api/v1/scenarios", {"name": "smoke-road-network", "spec": extra_spec})
        stored = call("GET", f"/api/v1/scenarios/{extra['id']}")
        assert stored["spec"]["travel_edges"] == extra_spec["travel_edges"]
        extra_run = call("POST", f"/api/v1/scenarios/{extra['id']}/runs", key=str(uuid.uuid4()))
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            extra_state = call("GET", f"/api/v1/runs/{extra_run['id']}")
            if extra_state["state"] in ("succeeded", "failed", "cancelled"):
                break
            time.sleep(2)
        else:
            raise AssertionError("road-network scenario did not finish")
        assert extra_state["state"] == "succeeded", extra_state
        extra_result = call("GET", f"/api/v1/runs/{extra_run['id']}/results")
        assert extra_result["optimization"]["selected"], extra_result
    frontend_run = frontend_call("POST", "/api/runs", {"mode": "city", "budget": 10_000_000, "demand": 100})
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        frontend_state = frontend_call("GET", f"/api/runs/{frontend_run['run_id']}")
        if frontend_state["run"]["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(2)
    else:
        raise AssertionError("frontend run did not finish within 180 seconds")
    assert frontend_state["run"]["state"] == "succeeded", frontend_state
    assert frontend_state["result"]["optimization"]["selected"]
    assert frontend_call("DELETE", "/api/session")["signed_in"] is False
    assert frontend_call("GET", "/api/session")["signed_in"] is False
    try:
        frontend_call("GET", "/api/maps/config")
        raise AssertionError("map configuration remained accessible after logout")
    except HTTPError as error:
        assert error.code == 401, error
    print(json.dumps({"run_id": run["id"], "state": current["state"],
                      "sites": len(result["optimization"]["selected"]),
                      "simulations": len(result["simulation"]),
                      "explanations": len(result["explanations"]),
                      "corridor_stops": corridor["stops"],
                      "fleet_peak_kw": fleet["peak_kw"],
                      "frontend_run": frontend_run["run_id"],
                      "imported_run": imported_run["run_id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
