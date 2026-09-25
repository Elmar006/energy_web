"""The development search must never optimize against its sealed final seeds."""
from fastapi.testclient import TestClient

from energy import api
from energy.acceptance import ServiceRequirements
from energy.improvement import improve_plan
from energy.optimizer import SolveResult


def _with_second_site(spec):
    spec = spec.model_copy(deep=True)
    spec.sites.append(spec.sites[0].model_copy(update={"id": "s2", "name": "Alternative"}))
    spec.travel_edges.append(spec.travel_edges[0].model_copy(update={"site_id": "s2"}))
    return spec


def _solution(extra=False):
    selected = [{"site_id": "s1", "option_id": "dc", "year": 2027}]
    if extra:
        selected.append({"site_id": "s2", "option_id": "dc", "year": 2027})
    return SolveResult(status="optimal", objective=95 if extra else 70, gap=0,
                       selected=selected, grid_upgrades=[], battery=[], solar=[],
                       served_kwh={"base": 95 if extra else 70},
                       unmet_kwh={"base": 5 if extra else 30},
                       cashflow_rub={"base": 0}, verification={"passed": True})


def _simulation(_spec, selected, *, year, scenario_id, seed, **_):
    extra = any(item["site_id"] == "s2" for item in selected)
    delivered = 95 if extra else 70
    return {"scenario_id": scenario_id, "year": year, "seed": seed,
            "arrivals": 100, "served_sessions": delivered,
            "refused_sessions": 100 - delivered,
            "requested_energy_kwh": 100, "energy_kwh": delivered,
            "p95_wait_minutes": 5, "refused_by_zone": {"z1": 100 - delivered},
            "dispatch_verification": {"passed": True}}


def test_bounded_search_selects_verified_extra_site_on_development_only(small_input):
    spec = _with_second_site(small_input)
    used_seeds = []
    solve_calls = []

    def solve(candidate):
        solve_calls.append(list(candidate.locked_site_ids))
        return _solution("s2" in candidate.locked_site_ids)

    def simulate(*args, seed, **kwargs):
        used_seeds.append(seed)
        return _simulation(*args, seed=seed, **kwargs)

    chosen, history = improve_plan(
        spec, _solution(), seeds=[100, 101],
        requirements=ServiceRequirements(min_energy_fraction=0.9),
        max_iterations=3, solve_fn=solve, simulate_fn=simulate)
    assert [item["site_id"] for item in chosen.selected] == ["s1", "s2"]
    assert solve_calls == [["s2"]]
    assert used_seeds == [100, 101, 100, 101]
    assert len(history) == 2
    assert history[0]["selected_for_holdout"] is False
    assert history[1]["selected_for_holdout"] is True
    assert history[1]["development_score"] == 0
    assert history[1]["development"]["not_independent_validation"] is True


def test_run_spec_v2_holds_out_final_sample_until_plan_is_selected(small_input, monkeypatch):
    spec = _with_second_site(small_input)
    used = []

    def solve(candidate):
        return _solution("s2" in candidate.locked_site_ids)

    def simulate(*args, seed, **kwargs):
        used.append(seed)
        return _simulation(*args, seed=seed, **kwargs)

    monkeypatch.setattr(api, "solve", solve)
    monkeypatch.setattr(api, "simulate", simulate)
    monkeypatch.setattr(api, "compare_operations", lambda *_: [])
    monkeypatch.setattr(api, "compare_economics", lambda *_: [])
    holdout = list(range(200, 230))
    response = TestClient(api.app).post("/v1/calculate", json={
        "input": spec.model_dump(mode="json"),
        "run_spec": {"schema_version": "run-spec-v2", "mode": "validation",
                     "development_seeds": [100, 101], "simulation_seeds": holdout,
                     "max_improvement_iterations": 1,
                     "service_requirements": {"min_energy_fraction": 0.9},
                     "explain_top_n": 0, "alternative_service_fractions": []},
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["service_acceptance"]["status"] == "accepted"
    assert result["improvement"]["holdout_seeds_used_for_selection"] is False
    assert result["improvement"]["iterations"][1]["selected_for_holdout"] is True
    assert used == [100, 101, 100, 101, *holdout]
    assert [row["seed"] for row in result["simulation"]] == holdout


def test_failed_candidate_cannot_replace_verified_plan(small_input):
    spec = _with_second_site(small_input)
    invalid = _solution(extra=True)
    invalid.verification = {"passed": False}
    chosen, history = improve_plan(
        spec, _solution(), seeds=[1, 2],
        requirements=ServiceRequirements(min_energy_fraction=0.9),
        max_iterations=1, solve_fn=lambda _: invalid, simulate_fn=_simulation)
    assert chosen.selected == _solution().selected
    assert history[1]["selected_for_holdout"] is False
    assert history[1]["physical_verification_passed"] is False


def test_holdout_failure_is_reported_after_development_success(small_input, monkeypatch):
    spec = _with_second_site(small_input)
    monkeypatch.setattr(api, "solve", lambda candidate:
                        _solution("s2" in candidate.locked_site_ids))

    def sim(*args, seed, **kwargs):
        row = _simulation(*args, seed=seed, **kwargs)
        if seed >= 200:
            row["served_sessions"] = 70
            row["refused_sessions"] = 30
            row["energy_kwh"] = 70
        return row

    monkeypatch.setattr(api, "simulate", sim)
    monkeypatch.setattr(api, "compare_operations", lambda *_: [])
    monkeypatch.setattr(api, "compare_economics", lambda *_: [])
    response = TestClient(api.app).post("/v1/calculate", json={
        "input": spec.model_dump(mode="json"),
        "run_spec": {"schema_version": "run-spec-v2", "mode": "validation",
                     "development_seeds": [100, 101],
                     "simulation_seeds": list(range(200, 230)),
                     "max_improvement_iterations": 1,
                     "service_requirements": {"min_energy_fraction": 0.9},
                     "explain_top_n": 0, "alternative_service_fractions": []},
    })
    assert response.status_code == 200, response.text
    output = response.json()
    assert output["improvement"]["iterations"][-1]["development_score"] == 0
    assert output["service_acceptance"]["status"] == "rejected"
    assert output["service_acceptance"]["reason"] == "service_threshold_failed"
