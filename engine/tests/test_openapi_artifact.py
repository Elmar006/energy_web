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
