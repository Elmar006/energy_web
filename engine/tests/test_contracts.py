import pytest
from pydantic import ValidationError

from energy.contracts import PlanningInput


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("zones", 0, "hourly_kwh"), [-1] + [0] * 23, "hourly_kwh"),
        (("grid_nodes", 0, "headroom_kw"), [-1] + [0] * 23, "headroom_kw"),
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
