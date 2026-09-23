import pytest

from energy.contracts import PlanningInput


@pytest.fixture
def small_input():
    assumed = {"source": "test fixture", "kind": "assumed"}
    return PlanningInput.model_validate({
        "id": "small",
        "zones": [{"id": "z1", "name": "Zone", "latitude": 55, "longitude": 37,
                   "hourly_kwh": [0] * 12 + [10] + [0] * 11,
                   "mean_session_kwh": 10, "max_travel_minutes": 20, "provenance": assumed}],
        "sites": [{"id": "s1", "name": "Station", "latitude": 55, "longitude": 37,
                   "grid_node_id": "g1", "option_ids": ["dc"], "provenance": assumed}],
        "options": [{"id": "dc", "ports": 1, "charger_kw": 10, "connection_kw": 10,
                     "capex_rub": 1000, "annual_fixed_rub": 0}],
        "grid_nodes": [{"id": "g1", "headroom_kw": [10] * 24, "provenance": assumed}],
        "scenarios": [{"id": "base", "demand_multiplier": [1]}],
        "travel_edges": [{"zone_id": "z1", "site_id": "s1", "minutes": 5}],
        "parameters": {"mode": "city", "years": [2027], "annual_budgets_rub": [2000],
                       "total_budget_rub": 2000, "sale_rub_per_kwh": 20,
                       "purchase_rub_per_kwh": 5, "discount_rate": 0.1,
                       "pv_hourly_factor": [0] * 24, "solver_seconds": 15}
    })
