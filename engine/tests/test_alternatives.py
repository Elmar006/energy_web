from energy import alternatives
import pytest


def test_identical_investments_reuse_deterministic_simulation(small_input, monkeypatch):
    calls = []

    def simulation_stub(*args, **kwargs):
        calls.append(kwargs)
        return {"seed": kwargs["seed"], "site_ids": [site["site_id"] for site in args[1]],
                "scenario_id": kwargs["scenario_id"], "year": kwargs["year"],
                "requested_energy_kwh": 10, "energy_kwh": 5,
                "unserved_energy_kwh": 5, "dispatch_by_site": [],
                "dispatch_verification": {"passed": True}}

    monkeypatch.setattr(alternatives, "simulate", simulation_stub)
    plans = alternatives.calculate_alternatives(small_input, [0, 0.5, 1], [1, 2], 15)

    assert [plan["same_investment_as_target"] for plan in plans] == [None, None, 0.5]
    assert plans[1]["simulation"] == plans[2]["simulation"]
    assert len(calls) == 4  # Two distinct investments, each with two seeds.


def test_alternative_with_failed_dispatch_audit_is_rejected(small_input, monkeypatch):
    monkeypatch.setattr(alternatives, "simulate", lambda *args, **kwargs:
                        {"dispatch_verification": {"passed": False}})
    with pytest.raises(RuntimeError, match="physical verification"):
        alternatives.calculate_alternatives(small_input, [1], [1], 15)
