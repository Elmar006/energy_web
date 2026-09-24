from datetime import date

import pytest

from energy.ingest_sessions import derive_demand


def test_metered_energy_is_conserved_across_local_hours(small_input):
    sessions = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
                "one,z1,2027-04-01T12:30:00+00:00,2027-04-01T13:30:00+00:00,10\n").encode()
    result = derive_demand(small_input, sessions, source="operator export", time_zone="Europe/Moscow",
                           start_date=date(2027, 4, 1), end_date=date(2027, 4, 1))
    assert result.zones[0].hourly_kwh[15] == pytest.approx(5)
    assert result.zones[0].hourly_kwh[16] == pytest.approx(5)
    assert sum(result.zones[0].hourly_kwh) == pytest.approx(10)
    assert result.zones[0].mean_session_kwh == pytest.approx(10)
    assert result.zones[0].arrival_profile.hourly_sessions[15] == pytest.approx(1)
    assert result.zones[0].arrival_profile.hourly_sessions[16] == 0
    assert result.zones[0].arrival_profile.energy_quantiles_kwh == [10] * 101
    assert result.zones[0].arrival_profile.sample_count == 1
    assert result.zones[0].provenance.kind == "derived"
    assert result.datasets[0].sha256
    assert result.datasets[0].kind == "assumed"
    assert small_input.zones[0].hourly_kwh[15] == 0


def test_midnight_session_is_normalized_by_explicit_day_count(small_input):
    sessions = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
                "one,z1,2027-04-01T20:30:00+00:00,2027-04-01T21:30:00+00:00,10\n").encode()
    result = derive_demand(small_input, sessions, source="operator export", time_zone="Europe/Moscow",
                           start_date=date(2027, 4, 1), end_date=date(2027, 4, 2))
    assert result.zones[0].hourly_kwh[23] == pytest.approx(2.5)
    assert result.zones[0].hourly_kwh[0] == pytest.approx(2.5)
    assert sum(result.zones[0].hourly_kwh) == pytest.approx(5)
    assert result.zones[0].arrival_profile.hourly_sessions[23] == pytest.approx(0.5)
    assert result.zones[0].arrival_profile.hourly_sessions[0] == 0


def test_import_replaces_stale_session_size_and_captures_daily_arrival_variance(small_input):
    data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
            "one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,5\n"
            "two,z1,2027-04-01T12:15:00+00:00,2027-04-01T13:15:00+00:00,15\n"
            "three,z1,2027-04-02T12:00:00+00:00,2027-04-02T13:00:00+00:00,25\n").encode()
    result = derive_demand(small_input, data, source="operator export", time_zone="Europe/Moscow",
                           start_date=date(2027, 4, 1), end_date=date(2027, 4, 2))
    profile = result.zones[0].arrival_profile
    assert result.zones[0].mean_session_kwh == pytest.approx(15)
    assert profile.hourly_sessions[15] == pytest.approx(1.5)
    assert profile.hourly_count_variance[15] == pytest.approx(0.5)
    assert profile.energy_quantiles_kwh[0] == 5
    assert profile.energy_quantiles_kwh[50] == 15
    assert profile.energy_quantiles_kwh[-1] == 25
    assert profile.sample_count == 3
    assert profile.observation_days == 2
    assert sum(result.zones[0].hourly_kwh) == pytest.approx(22.5)


@pytest.mark.parametrize("rows,reason", [
    ("", "no sessions"),
    ("one,unknown,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n", "unknown zone_id"),
    ("one,z1,2027-04-01T12:00:00,2027-04-01T13:00:00,10\n", "UTC offset"),
    ("one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,-1\n", "positive"),
])
def test_invalid_or_missing_observations_are_not_silently_zeroed(small_input, rows, reason):
    csv_data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n" + rows).encode()
    with pytest.raises(ValueError, match=reason):
        derive_demand(small_input, csv_data, source="operator export", time_zone="Europe/Moscow",
                      start_date=date(2027, 4, 1), end_date=date(2027, 4, 1))


def test_duplicate_session_ids_are_rejected(small_input):
    row = "one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n"
    csv_data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n" + row + row).encode()
    with pytest.raises(ValueError, match="duplicate"):
        derive_demand(small_input, csv_data, source="operator export", time_zone="Europe/Moscow",
                      start_date=date(2027, 4, 1), end_date=date(2027, 4, 1))


def test_repeated_dst_hour_conserves_energy(small_input):
    csv_data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
                "one,z1,2027-10-31T00:30:00+00:00,2027-10-31T02:30:00+00:00,20\n").encode()
    result = derive_demand(small_input, csv_data, source="operator export", time_zone="Europe/Berlin",
                           start_date=date(2027, 10, 31), end_date=date(2027, 10, 31))
    assert result.zones[0].hourly_kwh[2] == pytest.approx(15)
    assert result.zones[0].hourly_kwh[3] == pytest.approx(5)
    assert sum(result.zones[0].hourly_kwh) == pytest.approx(20)


def test_operator_export_can_be_marked_observed(small_input):
    data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
            "one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n").encode()
    result = derive_demand(small_input, data, source="verified operator export", kind="observed",
                           time_zone="Europe/Moscow", start_date=date(2027, 4, 1), end_date=date(2027, 4, 1))
    assert result.datasets[0].kind == "observed"
    assert result.zones[0].arrival_profile.source_kind == "observed"
    assert "input_kind=observed" in result.zones[0].provenance.source


def test_arrival_profile_cannot_disagree_with_metered_energy(small_input):
    data = ("session_id,zone_id,started_at,ended_at,energy_kwh\n"
            "one,z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,10\n").encode()
    observed = derive_demand(small_input, data, source="operator export", time_zone="Europe/Moscow",
                             start_date=date(2027, 4, 1), end_date=date(2027, 4, 1))
    raw = observed.model_dump()
    raw["zones"][0]["mean_session_kwh"] = 20
    from energy.contracts import PlanningInput
    with pytest.raises(ValueError, match="conserve session energy"):
        PlanningInput.model_validate(raw)


def test_skewed_session_energy_uses_empirical_inverse_cdf_not_smoothed_percentiles(small_input):
    rows = ["session_id,zone_id,started_at,ended_at,energy_kwh"]
    rows.extend(f"{index},z1,2027-04-01T12:00:00+00:00,2027-04-01T13:00:00+00:00,{energy}"
                for index, energy in enumerate((1, 1, 100)))
    result = derive_demand(small_input, ("\n".join(rows) + "\n").encode(),
                           source="test skewed sessions", time_zone="Europe/Moscow",
                           start_date=date(2027, 4, 1), end_date=date(2027, 4, 1))
    profile = result.zones[0].arrival_profile
    assert result.zones[0].mean_session_kwh == 34
    assert profile.energy_quantiles_kwh[66] == 1
    assert profile.energy_quantiles_kwh[67] == 100
