"""Exercise session-derived arrival profiles through Go, worker and Python."""
from __future__ import annotations

import json
import sys
import time
import uuid
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "engine"))

from energy.contracts import PlanningInput  # noqa: E402
from energy.ingest_sessions import derive_demand  # noqa: E402
from smoke import call  # noqa: E402


def main() -> None:
    spec = PlanningInput.model_validate_json((ROOT / "examples" / "import_sample.json").read_bytes())
    derived = derive_demand(spec, (ROOT / "examples" / "sessions_sample.csv").read_bytes(),
                            source="synthetic smoke fixture", kind="assumed",
                            time_zone="Europe/Moscow", start_date=date(2027, 4, 1),
                            end_date=date(2027, 4, 1))
    derived.id = "smoke-session-profile-" + uuid.uuid4().hex
    scenario = call("POST", "/api/v1/scenarios", {
        "name": "smoke-sessions-synthetic", "spec": derived.model_dump(mode="json")})
    saved = call("GET", f"/api/v1/scenarios/{scenario['id']}")
    profile = saved["spec"]["zones"][0]["arrival_profile"]
    assert profile["source_kind"] == "assumed"
    assert profile["sample_count"] == 2
    assert profile["hourly_sessions"][12] == 1
    assert profile["hourly_sessions"][17] == 1
    run = call("POST", f"/api/v1/scenarios/{scenario['id']}/runs", key=str(uuid.uuid4()))
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        state = call("GET", f"/api/v1/runs/{run['id']}")
        if state["state"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(2)
    else:
        raise AssertionError("session-derived run did not finish")
    assert state["state"] == "succeeded", state
    result = call("GET", f"/api/v1/runs/{run['id']}/results")
    assert result["optimization"]["verification"]["passed"]
    assert result["metadata"]["input_quality"]["demand_scope"] == "assumed_session_profiles"
    assert result["operational_validation"]
    assert result["operational_economics"]
    assert result["simulation"]
    for sample in result["simulation"]:
        assert sample["arrivals"] == sum(sample["arrivals_by_hour"])
        assert sum(value for hour, value in enumerate(sample["arrivals_by_hour"])
                   if hour not in (12, 17)) == 0
        assert sample["dispatch_verification"]["passed"]
    print(json.dumps({"scenario_id": scenario["id"], "run_id": run["id"],
                      "state": state["state"], "session_sample_count": profile["sample_count"],
                      "simulations": len(result["simulation"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
