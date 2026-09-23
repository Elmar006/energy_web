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
    assert result["optimization"]["selected"], "no sites selected"
    assert result["simulation"], "simulation missing"
    assert result["explanations"], "counterfactual explanation missing"
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
                      "frontend_run": frontend_run["run_id"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
