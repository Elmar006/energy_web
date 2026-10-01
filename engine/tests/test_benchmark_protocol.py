import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from energy.benchmark import benchmark
from energy.benchmark_protocol import (BenchmarkProtocol, input_sha256,
                                       load_locked_protocol)
from energy.contracts import PlanningInput
from energy.run_spec import engine_source_manifest


def protocol_for(spec):
    return BenchmarkProtocol.model_validate({
        "protocol_version": "commission-benchmark-v1",
        "case_id": spec.id,
        "input_sha256": input_sha256(spec),
        "engine_source_sha256": engine_source_manifest()[0],
        "planning_scenario_ids": [row.id for row in spec.scenarios],
        "evaluation_scenario_id": spec.scenarios[0].id,
        "evaluation_year": spec.parameters.years[-1],
        "simulation_days": spec.parameters.simulation_days,
        "budget": {
            "years": spec.parameters.years,
            "annual_budgets_rub": spec.parameters.annual_budgets_rub,
            "total_budget_rub": spec.parameters.total_budget_rub,
        },
        "split": {"kind": "simulation_seed_holdout",
                  "development_seeds": list(range(1, 31)),
                  "evaluation_seeds": list(range(1001, 1031))},
        "baselines": ["existing", "density", "optimized"],
        "stress_cases": ["outage", "demand_x0_75", "demand_x1_25",
                         "grid_x0_75", "grid_x1_25"],
        "primary_comparison": "optimized_minus_density",
        "primary_metric": "service_fraction",
    })


def test_protocol_hash_is_canonical_and_lock_rejects_drift(tmp_path, small_input):
    protocol = protocol_for(small_input)
    protocol_path = tmp_path / "protocol.json"
    lock_path = tmp_path / "protocol.lock.json"
    protocol_path.write_text(json.dumps(protocol.model_dump(mode="json"), indent=2), encoding="utf-8")
    lock_path.write_text(json.dumps({"protocol_sha256": protocol.sha256}), encoding="utf-8")
    assert load_locked_protocol(protocol_path, lock_path).sha256 == protocol.sha256
    protocol_path.write_text(json.dumps(protocol.model_dump(mode="json"),
                                        ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    assert load_locked_protocol(protocol_path, lock_path).sha256 == protocol.sha256
    changed = protocol.model_dump(mode="json")
    changed["split"]["evaluation_seeds"][-1] += 1
    protocol_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="lock SHA-256 mismatch"):
        load_locked_protocol(protocol_path, lock_path)
    lock_path.write_text(json.dumps({"protocol_sha256": protocol.sha256, "ignored": True}), encoding="utf-8")
    with pytest.raises(ValueError, match="lock SHA-256 mismatch"):
        load_locked_protocol(protocol_path, lock_path)


@pytest.mark.parametrize("mutation", [
    lambda row: row["split"]["evaluation_seeds"].__setitem__(0, 1),
    lambda row: row["baselines"].remove("density"),
    lambda row: row["stress_cases"].remove("outage"),
    lambda row: row["planning_scenario_ids"].append(row["planning_scenario_ids"][0]),
    lambda row: row["budget"]["annual_budgets_rub"].append(100),
])
def test_protocol_rejects_invalid_design(small_input, mutation):
    data = protocol_for(small_input).model_dump(mode="json")
    mutation(data)
    with pytest.raises(ValidationError):
        BenchmarkProtocol.model_validate(data)


@pytest.mark.parametrize("change, expected", [
    (lambda spec: setattr(spec.parameters, "total_budget_rub", 2500), "input_sha256"),
    (lambda spec: setattr(spec.scenarios[0], "id", "changed"), "input_sha256"),
    (lambda spec: setattr(spec.parameters, "simulation_days", 2), "input_sha256"),
])
def test_protocol_rejects_changed_input_before_solving(small_input, monkeypatch, change, expected):
    protocol = protocol_for(small_input)
    changed = small_input.model_copy(deep=True)
    change(changed)
    monkeypatch.setattr("energy.benchmark.solve", lambda _: pytest.fail("solver must not run"))
    with pytest.raises(ValueError, match=expected):
        benchmark(changed, protocol=protocol)


def test_budget_and_scenarios_are_independently_locked(small_input):
    original = protocol_for(small_input).model_dump(mode="json")
    changed = small_input.model_copy(deep=True)
    changed.parameters.annual_budgets_rub[0] += 1
    original["input_sha256"] = input_sha256(changed)
    with pytest.raises(ValueError, match="budget.annual_budgets_rub"):
        BenchmarkProtocol.model_validate(original).verify_input(changed)
    changed = small_input.model_copy(deep=True)
    changed.scenarios[0].id = "different"
    original = protocol_for(small_input).model_dump(mode="json")
    original["input_sha256"] = input_sha256(changed)
    with pytest.raises(ValueError, match="planning_scenario_ids"):
        BenchmarkProtocol.model_validate(original).verify_input(changed)


def test_protocol_rejects_changed_engine_before_solving(small_input, monkeypatch):
    protocol = protocol_for(small_input)
    monkeypatch.setattr("energy.benchmark_protocol.engine_source_manifest",
                        lambda: ("0" * 64, []))
    monkeypatch.setattr("energy.benchmark.solve", lambda _: pytest.fail("solver must not run"))
    with pytest.raises(ValueError, match="engine_source_sha256"):
        benchmark(small_input, protocol=protocol)


def test_locked_benchmark_uses_only_evaluation_seeds_and_reports_hash(small_input):
    spec = small_input.model_copy(deep=True)
    spec.parameters.simulation_days = 1
    protocol = protocol_for(spec)
    result = benchmark(spec, protocol=protocol)
    assert result["metadata"]["protocol"]["sha256"] == protocol.sha256
    assert result["metadata"]["protocol"]["status"] == "manifest_validated"
    assert result["metadata"]["seeds"] == list(range(1001, 1031))
    assert result["primary_result"]["difference"] == result["paired_differences"]["optimized_minus_density"]["service_fraction"]
    assert {row["seed"] for row in result["seed_rows"]} == set(range(1001, 1031))
    assert result["metadata"]["protocol"]["spec"]["split"]["development_seeds"] == list(range(1, 31))
    with pytest.raises(ValueError, match="overrides are forbidden"):
        benchmark(spec, protocol=protocol, seeds=list(range(30)))


def test_committed_holdout_artifact_matches_its_locked_protocol():
    root = Path(__file__).resolve().parents[2]
    folder = root / "docs" / "evidence" / "benchmarks" / "legacy"
    protocol = load_locked_protocol(folder / "protocol_monaco.json",
                                    folder / "protocol_monaco.lock.json")
    planning_input = PlanningInput.model_validate_json(
        (root / "examples" / "regression" / "monaco" / "commission_monaco.json").read_bytes())
    result = json.loads((folder / "benchmark_monaco_holdout.json").read_text(encoding="utf-8"))
    assert input_sha256(planning_input) == protocol.input_sha256
    assert result["metadata"]["input_sha256"] == protocol.input_sha256
    assert result["metadata"]["engine_source_sha256"] == protocol.engine_source_sha256
    assert result["metadata"]["protocol"]["sha256"] == protocol.sha256
    assert result["metadata"]["protocol"]["spec"] == protocol.model_dump(mode="json")
    assert result["metadata"]["seeds"] == list(protocol.split.evaluation_seeds)
    assert {row["seed"] for row in result["seed_rows"]} == set(protocol.split.evaluation_seeds)
    assert result["primary_result"]["difference"] == (
        result["paired_differences"][protocol.primary_comparison][protocol.primary_metric])
