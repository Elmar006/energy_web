import io
import json
import sys
from datetime import date
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from energy.fleet import schedule_fleet
from energy.ingest_gtfs import FleetOperations, import_gtfs, main


def archive(*, calendar=True, exception="", trip_times=("08:00:01", "09:00:01"), frequency=False):
    files = {
        "trips.txt": "route_id,service_id,trip_id\nr,s,trip-1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          f"trip-1,{trip_times[0]},{trip_times[0]},a,1\n"
                          f"trip-1,{trip_times[1]},{trip_times[1]},b,2\n",
    }
    if calendar:
        files["calendar.txt"] = ("service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                                 "s,1,1,1,1,1,0,0,20270901,20270930\n")
    if exception:
        files["calendar_dates.txt"] = "service_id,date,exception_type\n" + exception
    if frequency:
        files["frequencies.txt"] = "trip_id,start_time,end_time,headway_secs\ntrip-1,08:00:00,09:00:00,600\n"
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as output:
        for name, content in files.items():
            output.writestr(name, content)
    return buffer.getvalue()


def operations(*, windows=None):
    return FleetOperations.model_validate({
        "source": "dispatch test data", "kind": "assumed", "time_zone": "Europe/Moscow",
        "slot_minutes": 15,
        "buses": [{"id": "bus-1", "battery_kwh": 30, "initial_kwh": 15, "minimum_kwh": 2}],
        "sites": [{"id": "depot", "ports": 1, "charger_kw": 20, "grid_kw": 20}],
        "assignments": [{"trip_id": "trip-1", "bus_id": "bus-1", "energy_kwh": 8}],
        "windows": windows if windows is not None else [
            {"bus_id": "bus-1", "site_id": "depot", "start_time": "09:15:00", "end_time": "10:00:00"}],
    })


def test_gtfs_import_preserves_service_time_energy_and_provenance():
    fleet, manifest = import_gtfs(archive(), operations(), service_date=date(2027, 9, 6), source="city export")
    assert fleet.trips[0].start_slot == 32
    assert fleet.trips[0].end_slot == 37  # 09:00:01 rounds up conservatively
    assert fleet.trips[0].energy_kwh == 8
    assert fleet.windows[0].start_slot == 37
    assert manifest["source"] == "city export"
    assert manifest["operations_source"] == "dispatch test data"
    assert manifest["operations_kind"] == "assumed"
    assert manifest["time_zone"] == "Europe/Moscow"
    assert len(manifest["gtfs_sha256"]) == len(manifest["operations_sha256"]) == 64
    assert schedule_fleet(fleet)["status"] == "optimal"


def test_calendar_exception_removes_trip_and_can_add_service_without_calendar():
    removed = archive(exception="s,20270906,2\n")
    with pytest.raises(ValueError, match="inactive"):
        import_gtfs(removed, operations(), service_date=date(2027, 9, 6), source="feed")
    added = archive(calendar=False, exception="s,20270906,1\n")
    fleet, _ = import_gtfs(added, operations(), service_date=date(2027, 9, 6), source="feed")
    assert len(fleet.trips) == 1


def test_extended_gtfs_hours_are_kept_within_service_day_horizon():
    fleet, _ = import_gtfs(archive(trip_times=("24:01:00", "25:00:00")),
                           operations(windows=[]), service_date=date(2027, 9, 6), source="feed")
    assert (fleet.trips[0].start_slot, fleet.trips[0].end_slot, fleet.horizon_slots) == (96, 100, 100)


def test_charging_window_is_rounded_inward_and_overlap_is_rejected():
    windows = [{"bus_id": "bus-1", "site_id": "depot", "start_time": "07:00:01", "end_time": "08:14:59"}]
    fleet, _ = import_gtfs(archive(), operations(windows=windows),
                           service_date=date(2027, 9, 6), source="feed")
    assert (fleet.windows[0].start_slot, fleet.windows[0].end_slot) == (29, 32)
    windows[0]["end_time"] = "08:30:00"
    with pytest.raises(ValueError, match="overlaps a trip"):
        import_gtfs(archive(), operations(windows=windows), service_date=date(2027, 9, 6), source="feed")


def test_missing_energy_assignment_or_timing_is_not_synthesized():
    bad = operations().model_copy(deep=True)
    bad.assignments[0].trip_id = "unknown"
    with pytest.raises(ValueError, match="absent or inactive"):
        import_gtfs(archive(), bad, service_date=date(2027, 9, 6), source="feed")
    with pytest.raises(ValueError, match="invalid GTFS time"):
        import_gtfs(archive(trip_times=("n/a", "09:00:00")), operations(),
                    service_date=date(2027, 9, 6), source="feed")


def test_invalid_archive_and_empty_source_rejected():
    with pytest.raises(ValueError, match="ZIP archive"):
        import_gtfs(b"not zip", operations(), service_date=date(2027, 9, 6), source="feed")
    with pytest.raises(ValueError, match="source is required"):
        import_gtfs(archive(), operations(), service_date=date(2027, 9, 6), source=" ")


def test_nonchronological_stops_and_invalid_calendar_are_rejected():
    with pytest.raises(ValueError, match="not chronological"):
        import_gtfs(archive(trip_times=("09:00:00", "08:00:00")), operations(),
                    service_date=date(2027, 9, 6), source="feed")
    with pytest.raises(ValueError, match="calendar date"):
        import_gtfs(archive(calendar=False, exception="s,20271306,1\n"), operations(),
                    service_date=date(2027, 9, 6), source="feed")


def test_frequency_templates_are_not_misread_as_one_operated_trip():
    with pytest.raises(ValueError, match="explicit instance expansion"):
        import_gtfs(archive(frequency=True), operations(), service_date=date(2027, 9, 6), source="feed")


def test_cli_writes_reproducible_fleet_and_manifest(tmp_path, monkeypatch):
    feed = tmp_path / "gtfs.zip"
    ops = tmp_path / "operations.json"
    output = tmp_path / "fleet.json"
    manifest = tmp_path / "manifest.json"
    feed.write_bytes(archive())
    ops.write_text(operations().model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["ingest_gtfs", "--gtfs", str(feed), "--operations", str(ops),
                                  "--service-date", "2027-09-06", "--source", "city export",
                                  "--output", str(output), "--manifest", str(manifest)])
    main()
    assert json.loads(output.read_text(encoding="utf-8"))["trips"][0]["id"] == "trip-1"
    assert json.loads(manifest.read_text(encoding="utf-8"))["gtfs_sha256"]
