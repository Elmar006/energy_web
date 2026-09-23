import json
from pathlib import Path


def test_public_openapi_contract_has_resolved_component_references():
    path = Path(__file__).resolve().parents[2] / "openapi.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["openapi"] == "3.1.0"
    assert "/api/v1/scenarios" in document["paths"]
    assert "/api/v1/fleets/schedule" in document["paths"]
    assert "/api/v1/corridors/check" in document["paths"]
    schemas = document["components"]["schemas"]
    assert "expected_cvar" in schemas["Parameters"]["properties"]["risk"]["enum"]
    assert schemas["PlanResult"]["properties"]["optimization"]["$ref"].endswith("/OptimizationResult")
    assert schemas["PlanResult"]["properties"]["simulation"]["items"]["$ref"].endswith("/SimulationResult")
    assert "cvar_loss_rub" in schemas["RiskMetrics"]["properties"]
    assert "partial_energy_kwh" in schemas["SimulationResult"]["properties"]
    assert schemas["OptimizationResult"]["properties"]["energy_audit"]["items"]["$ref"].endswith("/EnergyAudit")
    assert "max_hourly_energy_balance_error_kwh" in schemas["PhysicalVerification"]["properties"]

    def walk(value):
        if isinstance(value, dict):
            if "$ref" in value:
                assert value["$ref"].startswith("#/components/schemas/")
                assert value["$ref"].split("/")[-1] in schemas
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(document)
