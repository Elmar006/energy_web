"""Exercise upload -> exact-version preview -> save -> worker on assumed fixtures."""

from __future__ import annotations

import copy
import json
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from smoke import BASE, TOKEN, call


def upload(role: str, feature: dict, label: str) -> str:
    boundary = "energy-test-" + uuid.uuid4().hex
    payload = json.dumps({"type": "FeatureCollection", "features": [feature]},
                         ensure_ascii=False).encode()
    parts = []
    for name, value in {"name": f"{label}-{role}", "kind": "assumed",
                        "source": "synthetic dataset-builder smoke fixture",
                        "license": "test-only"}.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode())
    parts.extend([
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{role}.geojson\"\r\n"
        "Content-Type: application/geo+json\r\n\r\n".encode(),
        payload,
        f"\r\n--{boundary}--\r\n".encode(),
    ])
    request = Request(BASE + "/api/v1/datasets/import", data=b"".join(parts), method="POST",
                      headers={"Authorization": f"Bearer {TOKEN}",
                               "Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urlopen(request, timeout=30) as response:
        result = json.load(response)
    assert result["features"] == 1
    return result["dataset_id"]


def main() -> None:
    label = "smoke-dataset-" + uuid.uuid4().hex
    time_zone = "Europe/Moscow"

    def point(identifier: str, feature_type: str, properties: dict) -> dict:
        return {"type": "Feature", "id": identifier,
                "geometry": {"type": "Point", "coordinates": [-150, -60]},
                "properties": {"feature_type": feature_type, **properties}}

    ids = {
        "demand_zones": upload("demand_zones", point("z1", "demand_zone", {
            "name": "Synthetic zone", "hourly_kwh": [0] * 12 + [10] + [0] * 11,
            "mean_session_kwh": 10, "max_travel_minutes": 20,
            "time_zone": time_zone}), label),
        "candidate_sites": upload("candidate_sites", point("s1", "candidate_site", {
            "name": "Synthetic site", "grid_node_id": "g1", "option_ids": ["dc"]}), label),
        "grid_nodes": upload("grid_nodes", point("g1", "grid_node", {
            "headroom_kw": [10] * 24, "time_zone": time_zone}), label),
        "travel_edges": upload("travel_edges", {
            "type": "Feature", "geometry": {"type": "LineString", "coordinates": [
                [-150, -60], [-149.9999, -59.9999]]},
            "properties": {"feature_type": "travel_edge", "zone_id": "z1", "site_id": "s1",
                           "minutes": 5}}, label),
    }
    build_request = {
        "name": label, "input_id": label, "time_zone": "Europe/Moscow",
        "dataset_versions": ids,
        "options": [{"id": "dc", "ports": 1, "charger_kw": 10, "connection_kw": 10,
                     "capex_rub": 1000, "annual_fixed_rub": 0}],
        "parameters": {"mode": "city", "years": [2027], "annual_budgets_rub": [1000],
                       "total_budget_rub": 1000, "sale_rub_per_kwh": 20,
                       "purchase_rub_per_kwh": 5, "discount_rate": 0.1,
                       "pv_hourly_factor": [0] * 24, "solver_seconds": 15},
        "scenarios": [{"id": "base", "demand_multiplier": [1]}],
    }
    missing = copy.deepcopy(build_request)
    missing["dataset_versions"]["grid_nodes"] = str(uuid.uuid4())
    try:
        call("POST", "/api/v1/scenarios/from-datasets/preview", missing)
        raise AssertionError("unknown grid version was accepted")
    except HTTPError as error:
        assert error.code == 404, error.read()

    incomplete = copy.deepcopy(build_request)
    del incomplete["options"][0]["charger_kw"]
    try:
        call("POST", "/api/v1/scenarios/from-datasets/preview", incomplete)
        raise AssertionError("missing equipment power was accepted")
    except HTTPError as error:
        assert error.code == 422, error.read()

    try:
        preview = call("POST", "/api/v1/scenarios/from-datasets/preview", build_request)
    except HTTPError as error:
        raise AssertionError(f"dataset preview failed: {error.code} {error.read().decode()}") from error
    assert preview["spec"]["time_zone"] == "Europe/Moscow"
    assert len(preview["data_quality"]["datasets"]) == 4
    assert all(row["kind"] == "assumed" for row in preview["data_quality"]["datasets"])
    assert {row["version_id"] for row in preview["data_quality"]["datasets"]} == set(ids.values())
    created = call("POST", "/api/v1/scenarios/from-datasets", build_request)
    scenario = created["scenario"]
    assert scenario["spec"] == preview["spec"]
    assert call("GET", f"/api/v1/scenarios/{scenario['id']}")["sha256"] == scenario["sha256"]
    run = call("POST", f"/api/v1/scenarios/{scenario['id']}/runs", key=str(uuid.uuid4()))
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = call("GET", f"/api/v1/runs/{run['id']}")
        if state["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(1)
    else:
        raise AssertionError("dataset-backed run did not finish")
    assert state["state"] == "succeeded", state
    result = call("GET", f"/api/v1/runs/{run['id']}/results")
    assert result["optimization"]["status"] == "optimal", result
    assert result["optimization"]["selected"][0]["site_id"] == "s1"
    assert result["optimization"]["served_kwh"]["base"] == 10
    assert result["optimization"]["verification"]["passed"] is True
    print(json.dumps({"scenario_id": scenario["id"], "run_id": run["id"],
                      "dataset_versions": ids}, ensure_ascii=False))


if __name__ == "__main__":
    main()
