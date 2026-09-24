"""Full-stack check: upload source CSV -> immutable scenario -> worker calculation.

Fixtures in examples/ are deliberately synthetic and must remain marked assumed.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BASE = os.environ.get("ENERGY_API_URL", "http://127.0.0.1:58080").rstrip("/")
TOKEN = os.environ.get("API_TOKEN", "local-development-token-change-before-deploy")


def call(method: str, path: str, payload: bytes | None = None, *, content_type: str | None = None,
         key: str | None = None) -> bytes:
    headers = {"Authorization": f"Bearer {TOKEN}"}
    if content_type:
        headers["Content-Type"] = content_type
    if key:
        headers["Idempotency-Key"] = key
    with urlopen(Request(BASE + path, data=payload, headers=headers, method=method), timeout=90) as response:
        return response.read()


def json_call(method: str, path: str, payload: dict | None = None, *, key: str | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
    return json.loads(call(method, path, body, content_type="application/json" if body else None, key=key))


def upload(parent: str, role: str, fields: dict[str, str], file_bytes: bytes) -> dict:
    boundary = "energy-" + uuid.uuid4().hex
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n".encode()
                      + value.encode() + b"\r\n")
    chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                  "filename=\"source.csv\"\r\nContent-Type: text/csv\r\n\r\n".encode() + file_bytes + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    path = f"/api/v1/scenarios/{parent}/imports/{role}"
    return json.loads(call("POST", path, b"".join(chunks), content_type=f"multipart/form-data; boundary={boundary}"))


def main() -> None:
    base = json.loads((ROOT / "examples" / "import_sample.json").read_text(encoding="utf-8"))
    parent = json_call("POST", "/api/v1/scenarios", {"name": "synthetic upload smoke", "spec": base})
    sessions = (ROOT / "examples" / "sessions_sample.csv").read_bytes()
    common = {"scenario_name": "synthetic metered demand", "dataset_name": "synthetic sessions",
              "source": "repository synthetic smoke fixture", "kind": "assumed",
              "time_zone": "Europe/Moscow", "start_date": "2027-04-01", "end_date": "2027-04-01"}
    derived = upload(parent["id"], "sessions", common, sessions)
    assert not derived["reused"]
    assert derived["sha256"] == hashlib.sha256(sessions).hexdigest()
    assert call("GET", f"/api/v1/datasets/{derived['dataset_id']}/file") == sessions
    assert json_call("GET", f"/api/v1/scenarios/{parent['id']}")["spec"] == base
    assert sum(derived["scenario"]["spec"]["zones"][0]["hourly_kwh"]) == 20
    assert derived["scenario"]["spec"]["datasets"][-1]["transform_version"] == "metered-sessions-v3"
    repeat = upload(parent["id"], "sessions", common, sessions)
    assert repeat["reused"] and repeat["scenario"]["id"] == derived["scenario"]["id"]
    assert repeat["dataset_id"] == derived["dataset_id"]

    incomplete = {**common, "end_date": "2027-04-02"}
    try:
        upload(parent["id"], "sessions", incomplete, sessions)
    except HTTPError as error:
        assert error.code == 422, error
    else:
        raise AssertionError("missing day was silently counted as zero sessions")
    confirmed = upload(parent["id"], "sessions",
                       {**incomplete, "coverage_complete": "true"}, sessions)
    assert confirmed["scenario"]["spec"]["zones"][0]["arrival_profile"]["coverage_complete"] is True
    assert sum(confirmed["scenario"]["spec"]["zones"][0]["hourly_kwh"]) == 10

    grid = (ROOT / "examples" / "grid_profile_sample.csv").read_bytes()
    grid_fields = {"scenario_name": "synthetic demand and grid", "dataset_name": "synthetic grid reserve",
                   "source": "repository synthetic smoke fixture", "kind": "assumed",
                   "time_zone": "Europe/Moscow", "profile_date": "2026-09-01"}
    combined = upload(derived["scenario"]["id"], "grid-headroom", grid_fields, grid)
    assert len(combined["scenario"]["spec"]["datasets"]) == len(base.get("datasets", [])) + 2
    assert combined["scenario"]["spec"]["datasets"][-1]["version_id"] == combined["dataset_id"]
    assert combined["scenario"]["spec"]["datasets"][-1]["transform_version"] == "grid-headroom-v1"
    assert call("GET", f"/api/v1/datasets/{combined['dataset_id']}/file") == grid
    try:
        upload(derived["scenario"]["id"], "grid-headroom", grid_fields,
               grid.replace(b"grid-kazan-example", b"unknown-node"))
    except HTTPError as error:
        assert error.code == 422, error
    else:
        raise AssertionError("invalid grid node was accepted")

    run = json_call("POST", f"/api/v1/scenarios/{combined['scenario']['id']}/runs", key=str(uuid.uuid4()))
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = json_call("GET", f"/api/v1/runs/{run['id']}")
        if state["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(2)
    else:
        raise AssertionError("uploaded-data calculation did not finish")
    assert state["state"] == "succeeded", state
    result = json_call("GET", f"/api/v1/runs/{run['id']}/results")
    assert result["optimization"]["status"] in ("optimal", "feasible"), result
    assert result["optimization"]["verification"]["passed"] is True
    assert result["optimization"]["service_by_year"][0]["demand_kwh"] == 20
    assert result["simulation"] and result["simulation"][0]["dispatch_verification"]["passed"] is True
    assert result["simulation"][0]["simulation_days"] == 3
    assert len(result["simulation"][0]["day_dispatch"]) == 3
    assert result["simulation"][0]["dispatch_verification"]["storage_energy_balance_error_kwh"] <= 1e-6
    print("uploaded CSV -> versioned scenario -> worker -> verified calculation: OK")


if __name__ == "__main__":
    main()
