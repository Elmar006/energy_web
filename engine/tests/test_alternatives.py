from energy import alternatives


def test_identical_investments_reuse_deterministic_simulation(small_input, monkeypatch):
    calls = []

    def simulation_stub(*args, **kwargs):
        calls.append(kwargs)
        return {"seed": kwargs["seed"], "site_ids": [site["site_id"] for site in args[1]]}

    monkeypatch.setattr(alternatives, "simulate", simulation_stub)
    plans = alternatives.calculate_alternatives(small_input, [0, 0.5, 1], [1, 2], 15)

    assert [plan["same_investment_as_target"] for plan in plans] == [None, None, 0.5]
    assert plans[1]["simulation"] == plans[2]["simulation"]
    assert len(calls) == 4  # Two distinct investments, each with two seeds.
