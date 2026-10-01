"""Exercise a named private deployment without exposing credentials/ports.

Explicitly creates a small ASSUMED demand artifact, scenario and queued run.
Does not delete data. Uses the frontend container's environment for credentials.
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
from pathlib import Path

from production_backup import Deployment

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    deployment = Deployment(args.env_file, args.project)
    assumed = {"source": "explicit synthetic deployment verification fixture", "kind": "assumed"}
    document = {"schema_version": "demand-dataset-v1", "service_calendar": {
        "schema_version": "service-calendar-v1", "time_zone": "Europe/Moscow",
        "covered_dates": ["2027-05-03"], "request_zone_ids": ["z1"], "legacy_profile_zone_ids": [],
        "annualization_factor": 365, "annualization_basis": "assumed_repeat"},
        "charging_requests": [{"request_id": "v:1", "vehicle_id": "v", "segment": "private", "zone_id": "z1",
                               "arrival_at": "2027-05-03T12:30:00+03:00", "deadline_at": "2027-05-03T13:30:00+03:00",
                               "energy_from_charger_kwh": 10, "battery_kwh": 40, "soc_before_kwh": 0,
                               "max_vehicle_kw": 20, "charging_efficiency": 1, "population_weight": 1, "provenance": assumed}]}
    hourly = [0] * 24
    hourly[12] = 10
    spec = {"id": "production-synthetic-verification", "time_zone": "Europe/Moscow",
            "zones": [{"id": "z1", "name": "Assumed zone", "latitude": 55, "longitude": 37,
                       "hourly_kwh": hourly, "mean_session_kwh": 10, "max_travel_minutes": 20, "provenance": assumed}],
            "sites": [{"id": "s1", "name": "Assumed station", "latitude": 55, "longitude": 37,
                       "grid_node_id": "g1", "option_ids": ["dc"], "provenance": assumed}],
            "options": [{"id": "dc", "ports": 1, "charger_kw": 10, "connection_kw": 10, "capex_rub": 1000, "annual_fixed_rub": 0}],
            "grid_nodes": [{"id": "g1", "headroom_kw": [10] * 24, "provenance": assumed}],
            "scenarios": [{"id": "base", "demand_multiplier": [1]}],
            "travel_edges": [{"zone_id": "z1", "site_id": "s1", "minutes": 5}],
            "parameters": {"mode": "city", "years": [2027], "annual_budgets_rub": [2000], "total_budget_rub": 2000,
                           "sale_rub_per_kwh": 20, "purchase_rub_per_kwh": 5, "discount_rate": 0.1,
                           "pv_hourly_factor": [0] * 24, "solver_seconds": 15}}
    sys.path.insert(0, str(ROOT / "engine"))
    from energy.run_spec import engine_source_manifest
    script = "const fixture=" + json.dumps({"spec": spec, "document": document, "source_hash": engine_source_manifest()[0]}) + ";\n" + r'''
import assert from 'node:assert/strict';
import {createHash, randomUUID} from 'node:crypto';
const api=process.env.ENERGY_API_URL, origin=process.env.APP_PUBLIC_ORIGIN;
async function backend(path, body, key) {
  const response=await fetch(api+path,{method:body===undefined?'GET':'POST',
    headers:{Authorization:'Bearer '+process.env.API_TOKEN,'Content-Type':'application/json',...(key?{'Idempotency-Key':key}:{})},
    ...(body===undefined?{}:{body:typeof body==='string'?body:JSON.stringify(body)}),signal:AbortSignal.timeout(30000)});
  assert.ok(response.ok, `backend ${path}: ${response.status}`);
  return response.json();
}
for(const authorization of ['',process.env.API_TOKEN,'Basic '+process.env.API_TOKEN]) {
  const r=await fetch(api+'/api/v1/scenarios',{headers:{Authorization:authorization}});
  assert.equal(r.status,401);
}
assert.equal((await fetch('http://localhost:3000/api/session',{method:'POST',headers:{Origin:'https://untrusted.test'},body:'{}'})).status,403);
const login=await fetch('http://localhost:3000/api/session',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json'},body:JSON.stringify({password:process.env.APP_ACCESS_PASSWORD})});
assert.equal(login.status,200);
const cookie=login.headers.get('set-cookie');
for(const flag of ['HttpOnly','Secure','SameSite=strict']) assert.ok(cookie.includes(flag));
const sessionCookie=cookie.split(';')[0];
const self=await fetch('http://localhost:3000/api/session',{headers:{Cookie:sessionCookie}});
assert.equal((await self.json()).signed_in,true);
const raw=JSON.stringify(fixture.document);
const manifest=await backend('/api/v1/artifacts/demand',raw);
assert.equal(manifest.sha256,createHash('sha256').update(raw).digest('hex'));
const scenario=await backend('/api/v1/scenarios',{name:'ASSUMED production verification',spec:{...fixture.spec,demand_dataset:manifest}});
const key=randomUUID();
const body={run_spec:{simulation_seeds:[42],simulation_days:1,solver_seconds:15,explain_top_n:0,alternative_service_fractions:[]}};
const run=await backend('/api/v1/scenarios/'+scenario.id+'/runs',body,key);
assert.equal((await backend('/api/v1/scenarios/'+scenario.id+'/runs',body,key)).id,run.id);
let state;
const deadline=Date.now()+180000;
while(Date.now()<deadline) {
  state=await backend('/api/v1/runs/'+run.id);
  if(['succeeded','failed','cancelled'].includes(state.state)) break;
  await new Promise(resolve=>setTimeout(resolve,1000));
}
assert.equal(state.state,'succeeded','queued production run must succeed');
const result=await backend('/api/v1/runs/'+run.id+'/results');
assert.equal(result.optimization.verification.passed,true);
assert.equal(result.metadata.engine_source_sha256,fixture.source_hash);
assert.equal(result.metadata.scenario_snapshot_sha256,scenario.sha256);
assert.equal(result.metadata.execution_sha256,run.execution_sha256);
assert.ok(result.simulation.length>0);
const relay=await fetch('http://localhost:3000/api/runs/'+run.id,{headers:{Cookie:sessionCookie}});
assert.equal(relay.status,200);
assert.equal((await relay.json()).run.id,run.id);
console.log(JSON.stringify({status:state.state,run_id:run.id,scenario_id:scenario.id,
  artifact_sha256:manifest.sha256,engine_source_sha256:result.metadata.engine_source_sha256,
  physical_verification_passed:true,secure_cookie_verified:true,label:'assumed deployment fixture'}));
'''
    result = deployment.run("exec", "-T", "frontend", "node", "--input-type=module", input=script.encode(), stdout=subprocess.PIPE)
    evidence = json.loads(result.stdout)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence))


if __name__ == "__main__":
    main()
