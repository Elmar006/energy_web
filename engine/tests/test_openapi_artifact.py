import json
from pathlib import Path


def test_public_openapi_contract_has_resolved_component_references():
    path = Path(__file__).resolve().parents[2] / "openapi.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["openapi"] == "3.1.0"
    assert "/api/v1/scenarios" in document["paths"]
    assert "/api/v1/scenarios/from-datasets/preview" in document["paths"]
    assert "/api/v1/scenarios/from-datasets" in document["paths"]
    assert "/api/v1/datasets/import" in document["paths"]
    assert "/api/v1/fleets/schedule" in document["paths"]
    assert "/api/v1/corridors/check" in document["paths"]
    schemas = document["components"]["schemas"]
    assert "expected_cvar" in schemas["Parameters"]["properties"]["risk"]["enum"]
    assert schemas["PlanResult"]["properties"]["optimization"]["$ref"].endswith("/OptimizationResult")
    assert schemas["PlanResult"]["properties"]["simulation"]["items"]["$ref"].endswith("/SimulationResult")
    assert "cvar_loss_rub" in schemas["RiskMetrics"]["properties"]
    assert "partial_energy_kwh" in schemas["SimulationResult"]["properties"]
    assert "arrival_profile" in schemas["Zone"]["properties"]
    assert "hourly_load_method" in schemas["SessionArrivalProfile"]["required"]
    assert "requested_energy_kwh" in schemas["SimulationResult"]["required"]
    assert schemas["PlanResult"]["properties"]["operational_validation"]["items"]["$ref"].endswith("/OperationalValidation")
    assert schemas["PlanResult"]["properties"]["operational_economics"]["items"]["$ref"].endswith("/OperationalEconomics")
    assert schemas["OptimizationResult"]["properties"]["energy_audit"]["items"]["$ref"].endswith("/EnergyAudit")
    assert "max_hourly_energy_balance_error_kwh" in schemas["PhysicalVerification"]["properties"]
    assert "upgrade_lead_years" in schemas["GridNode"]["properties"]
    assert "commissioned_year" in schemas["OptimizationResult"]["properties"]["grid_upgrades"]["items"]["required"]
    assert schemas["PlanResult"]["properties"]["alternatives"]["items"]["$ref"].endswith("/AlternativePlan")
    assert "max_service_floor_shortfall_kwh" in schemas["PhysicalVerification"]["properties"]
    assert schemas["OptimizationResult"]["properties"]["service_by_year"]["items"]["$ref"].endswith("/ServiceYear")
    assert schemas["PreparedDatasetScenario"]["properties"]["spec"]["$ref"].endswith("/ScenarioSpec")
    assert schemas["DatasetScenarioRequest"]["properties"]["dataset_versions"]["$ref"].endswith("/DatasetSelection")
    assert "version_id" in schemas["DatasetReference"]["properties"]

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
