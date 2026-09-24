import pytest
from math import inf, nan
from pydantic import ValidationError

from energy.contracts import PlanningInput


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("zones", 0, "hourly_kwh"), [-1] + [0] * 23, "hourly_kwh"),
        (("grid_nodes", 0, "headroom_kw"), [-1] + [0] * 23, "headroom_kw"),
        (("grid_nodes", 0, "upgrade_lead_years"), -1, "upgrade_lead_years"),
        (("scenarios", 0, "demand_multiplier"), [-1], "demand_multiplier"),
        (("parameters", "annual_budgets_rub"), [-1], "annual_budgets_rub"),
        (("parameters", "years"), [2027, 2029], "years"),
    ],
)
def test_rejects_invalid_physical_and_temporal_inputs(small_input, path, value, message):
    raw = small_input.model_dump()
    if path == ("parameters", "years"):
        raw["parameters"]["annual_budgets_rub"] = [2000, 2000]
        raw["scenarios"][0]["demand_multiplier"] = [1, 1]
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError, match=message):
        PlanningInput.model_validate(raw)


def test_rejects_excluding_an_existing_station(small_input):
    raw = small_input.model_dump()
    raw["sites"][0]["existing_option_id"] = "dc"
    raw["excluded_site_ids"] = ["s1"]
    with pytest.raises(ValidationError, match="existing site cannot be excluded"):
        PlanningInput.model_validate(raw)


def test_rejects_duplicate_travel_edges(small_input):
    raw = small_input.model_dump()
    raw["travel_edges"].append(raw["travel_edges"][0])
    with pytest.raises(ValidationError, match="travel edges must be unique"):
        PlanningInput.model_validate(raw)


@pytest.mark.parametrize("mode,limit,reason", [
    ("operator", {}, "max_cvar_loss_rub"),
    ("city", {"max_cvar_loss_rub": 0}, "max_cvar_unmet_kwh"),
])
def test_cvar_requires_probabilities_and_mode_specific_limit(small_input, mode, limit, reason):
    raw = small_input.model_dump()
    raw["parameters"].update({"mode": mode, "risk": "expected_cvar", **limit})
    raw["scenarios"][0]["probability"] = 1
    with pytest.raises(ValidationError, match=reason):
        PlanningInput.model_validate(raw)


def test_cvar_requires_valid_probabilities_and_alpha(small_input):
    raw = small_input.model_dump()
    raw["parameters"].update({"risk": "expected_cvar", "max_cvar_unmet_kwh": 10})
    with pytest.raises(ValidationError, match="probabilities"):
        PlanningInput.model_validate(raw)
    raw["scenarios"][0]["probability"] = 1
    raw["parameters"]["cvar_alpha"] = 1
    with pytest.raises(ValidationError, match="cvar_alpha"):
        PlanningInput.model_validate(raw)


def test_cvar_threshold_cannot_be_silently_ignored(small_input):
    raw = small_input.model_dump()
    raw["parameters"]["max_cvar_unmet_kwh"] = 10
    with pytest.raises(ValidationError, match="expected_cvar"):
        PlanningInput.model_validate(raw)


@pytest.mark.parametrize("path,value", [
    (("zones", 0, "hourly_kwh", 12), nan),
    (("zones", 0, "mean_session_kwh"), inf),
    (("grid_nodes", 0, "headroom_kw", 0), inf),
    (("options", 0, "capex_rub"), inf),
    (("scenarios", 0, "demand_multiplier", 0), nan),
    (("travel_edges", 0, "minutes"), inf),
    (("parameters", "sale_rub_per_kwh"), inf),
])
def test_nonfinite_numbers_never_reach_solver(small_input, path, value):
    raw = small_input.model_dump()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        PlanningInput.model_validate(raw)


@pytest.mark.parametrize("path", [("id",), ("zones", 0, "id"), ("sites", 0, "name"),
                                   ("options", 0, "id")])
def test_empty_identifiers_are_rejected(small_input, path):
    raw = small_input.model_dump()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = ""
    with pytest.raises(ValidationError):
        PlanningInput.model_validate(raw)
