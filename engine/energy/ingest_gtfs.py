"""Convert a GTFS service day and explicit fleet operations into FleetInput.

GTFS describes public service, not vehicle energy or charger access. Those
facts must be supplied separately; this adapter never estimates them.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Literal
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator

from .fleet import ChargeWindow, FleetBus, FleetInput, FleetSite, FleetTrip

MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 20 * 1024 * 1024
MAX_ROWS = 500_000


class TripAssignment(BaseModel):
    trip_id: str = Field(min_length=1)
    bus_id: str = Field(min_length=1)
    energy_kwh: float = Field(gt=0, allow_inf_nan=False)


class TimedChargeWindow(BaseModel):
    bus_id: str = Field(min_length=1)
    site_id: str = Field(min_length=1)
    start_time: str
    end_time: str


class FleetOperations(BaseModel):
    source: str = Field(min_length=1)
    kind: Literal["observed", "assumed"] = "assumed"
    time_zone: str = Field(min_length=1)
    slot_minutes: int = Field(default=15, gt=0, le=60)
    efficiency: float = Field(default=0.95, gt=0, le=1)
    buses: list[FleetBus] = Field(min_length=1)
    sites: list[FleetSite] = Field(min_length=1)
    assignments: list[TripAssignment] = Field(min_length=1)
    windows: list[TimedChargeWindow] = Field(default_factory=list)
    solver_seconds: int = Field(default=30, ge=1, le=3600)

    @model_validator(mode="after")
    def check_assignments(self):
        if len({a.trip_id for a in self.assignments}) != len(self.assignments):
            raise ValueError("trip assignments must be unique")
        if not self.source.strip():
            raise ValueError("operations source is required")
        try:
            ZoneInfo(self.time_zone)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"unknown IANA time zone: {self.time_zone}") from error
        return self


def _time_minutes(value: str) -> float:
    pieces = value.split(":")
    if len(pieces) != 3 or len(pieces[0]) < 2 or any(not part.isascii() or not part.isdigit() for part in pieces) or any(len(part) != 2 for part in pieces[1:]):
        raise ValueError(f"invalid GTFS time {value!r}; expected HH:MM:SS")
    hours, minutes, seconds = map(int, pieces)
    if minutes > 59 or seconds > 59:
        raise ValueError(f"invalid GTFS time {value!r}")
    return hours * 60 + minutes + seconds / 60


def _service_day(value: str) -> date:
    if len(value) != 8 or not value.isascii() or not value.isdigit():
        raise ValueError(f"invalid GTFS calendar date {value!r}")
    try:
        return date.fromisoformat(f"{value[:4]}-{value[4:6]}-{value[6:]}")
    except ValueError as error:
        raise ValueError(f"invalid GTFS calendar date {value!r}") from error


def _read_table(archive: ZipFile, name: str, required: set[str]) -> list[dict[str, str]]:
    matches = [item for item in archive.infolist() if item.filename == name]
    if len(matches) != 1:
        raise ValueError(f"GTFS requires exactly one {name}")
    info = matches[0]
    if info.file_size > MAX_MEMBER_BYTES:
        raise ValueError(f"GTFS {name} exceeds 20 MiB")
    try:
        with archive.open(info) as file:
            content = file.read(MAX_MEMBER_BYTES + 1)
        if len(content) > MAX_MEMBER_BYTES:
            raise ValueError(f"GTFS {name} exceeds 20 MiB")
        reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig"), newline=""))
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            raise ValueError(f"GTFS {name} missing columns: {', '.join(sorted(required - set(reader.fieldnames or [])))}")
        rows = []
        for number, row in enumerate(reader, start=2):
            if number > MAX_ROWS + 1:
                raise ValueError(f"GTFS {name} exceeds {MAX_ROWS} rows")
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"GTFS {name} row {number} has malformed columns")
            rows.append(row)
        return rows
    except (UnicodeDecodeError, BadZipFile) as error:
        raise ValueError(f"GTFS {name} is not a valid UTF-8 CSV") from error


def _active_services(archive: ZipFile, service_date: date) -> set[str]:
    names = set(archive.namelist())
    if "calendar.txt" not in names and "calendar_dates.txt" not in names:
        raise ValueError("GTFS requires calendar.txt or calendar_dates.txt")
    active: set[str] = set()
    day = service_date.strftime("%Y%m%d")
    if "calendar.txt" in names:
        weekdays = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
        rows = _read_table(archive, "calendar.txt", {"service_id", "start_date", "end_date", *weekdays})
        seen = set()
        for row in rows:
            service = row["service_id"]
            if not service or service in seen:
                raise ValueError("GTFS calendar service_id must be unique and nonempty")
            seen.add(service)
            start, end = _service_day(row["start_date"]), _service_day(row["end_date"])
            if end < start or any(row[weekday] not in ("0", "1") for weekday in weekdays):
                raise ValueError("GTFS calendar has invalid date range or weekday flag")
            if row["start_date"] <= day <= row["end_date"] and row[weekdays[service_date.weekday()]] == "1":
                active.add(service)
    if "calendar_dates.txt" in names:
        rows = _read_table(archive, "calendar_dates.txt", {"service_id", "date", "exception_type"})
        seen = set()
        for row in rows:
            pair = (row["service_id"], row["date"])
            if not pair[0] or pair in seen or row["exception_type"] not in ("1", "2"):
                raise ValueError("GTFS calendar_dates has duplicate or invalid exception")
            seen.add(pair)
            _service_day(row["date"])
            if row["date"] == day:
                if row["exception_type"] == "1":
                    active.add(row["service_id"])
                else:
                    active.discard(row["service_id"])
    return active


def import_gtfs(gtfs_bytes: bytes, operations: FleetOperations, *, service_date: date,
                source: str, license: str | None = None) -> tuple[FleetInput, dict]:
    if not source.strip():
        raise ValueError("GTFS source is required")
    if len(gtfs_bytes) > MAX_ARCHIVE_BYTES:
        raise ValueError("GTFS archive exceeds 50 MiB")
    try:
        archive = ZipFile(io.BytesIO(gtfs_bytes))
    except BadZipFile as error:
        raise ValueError("GTFS input must be a ZIP archive") from error
    with archive:
        active = _active_services(archive, service_date)
        trip_rows = _read_table(archive, "trips.txt", {"trip_id", "service_id"})
        trips: dict[str, str] = {}
        for row in trip_rows:
            trip_id = row["trip_id"]
            if not trip_id or trip_id in trips:
                raise ValueError("GTFS trip_id must be unique and nonempty")
            trips[trip_id] = row["service_id"]
        assigned = {a.trip_id: a for a in operations.assignments}
        inactive = sorted(trip_id for trip_id in assigned if trip_id not in trips or trips[trip_id] not in active)
        if inactive:
            raise ValueError("assigned trips absent or inactive on service date: " + ", ".join(inactive))
        if "frequencies.txt" in archive.namelist():
            frequency_rows = _read_table(archive, "frequencies.txt", {"trip_id", "start_time", "end_time", "headway_secs"})
            frequency_templates = sorted({row["trip_id"] for row in frequency_rows} & assigned.keys())
            if frequency_templates:
                raise ValueError("assigned frequency-based trips require explicit instance expansion: "
                                 + ", ".join(frequency_templates))
        stop_rows = _read_table(archive, "stop_times.txt", {"trip_id", "arrival_time", "departure_time", "stop_sequence"})
        stops = defaultdict(list)
        for row in stop_rows:
            if row["trip_id"] in assigned:
                try:
                    sequence = int(row["stop_sequence"])
                except ValueError as error:
                    raise ValueError(f"trip {row['trip_id']}: invalid stop_sequence") from error
                if sequence < 0:
                    raise ValueError(f"trip {row['trip_id']}: invalid stop_sequence")
                stops[row["trip_id"]].append((sequence, row))

    slot = operations.slot_minutes
    normalized_trips = []
    for trip_id, assignment in assigned.items():
        sequence = sorted(stops[trip_id], key=lambda item: item[0])
        if len(sequence) < 2 or len({item[0] for item in sequence}) != len(sequence):
            raise ValueError(f"trip {trip_id}: at least two unique stop times are required")
        previous_departure = -1.0
        for _, row in sequence:
            arrival_text, departure_text = row["arrival_time"], row["departure_time"]
            if bool(arrival_text) != bool(departure_text):
                raise ValueError(f"trip {trip_id}: arrival/departure must both be present or absent")
            if not arrival_text:
                continue
            arrival, departure = _time_minutes(arrival_text), _time_minutes(departure_text)
            if arrival < previous_departure or departure < arrival:
                raise ValueError(f"trip {trip_id}: stop times are not chronological")
            previous_departure = departure
        start = _time_minutes(sequence[0][1]["departure_time"])
        end = _time_minutes(sequence[-1][1]["arrival_time"])
        if end <= start:
            raise ValueError(f"trip {trip_id}: arrival must be after departure")
        normalized_trips.append(FleetTrip(id=trip_id, bus_id=assignment.bus_id,
                                          start_slot=start // slot, end_slot=math.ceil(end / slot),
                                          energy_kwh=assignment.energy_kwh))

    windows = []
    for item in operations.windows:
        start = _time_minutes(item.start_time)
        end = _time_minutes(item.end_time)
        if end <= start:
            raise ValueError("charging window end must follow start")
        first, last = math.ceil(start / slot), end // slot
        if first >= last:
            raise ValueError("charging window is shorter than a complete slot")
        windows.append(ChargeWindow(bus_id=item.bus_id, site_id=item.site_id,
                                    start_slot=first, end_slot=last))
    horizon = max([trip.end_slot for trip in normalized_trips] + [window.end_slot for window in windows])
    fleet = FleetInput(slot_minutes=slot, horizon_slots=horizon, efficiency=operations.efficiency,
                       buses=operations.buses, sites=operations.sites, trips=normalized_trips,
                       windows=windows, solver_seconds=operations.solver_seconds)
    metadata = {"source": source, "license": license, "service_date": service_date.isoformat(),
                "operations_source": operations.source, "operations_kind": operations.kind,
                "time_zone": operations.time_zone,
                "gtfs_sha256": hashlib.sha256(gtfs_bytes).hexdigest(),
                "operations_sha256": hashlib.sha256(json.dumps(operations.model_dump(mode="json"),
                                                       sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
                "trip_count": len(normalized_trips), "bus_count": len(operations.buses),
                "time_basis": "GTFS local service-day time, including hours after 24:00",
                "rounding": "trips occupy every intersected slot; windows contain only complete slots",
                "energy_source": "explicit trip assignments; no energy inferred from GTFS"}
    return fleet, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Import one GTFS service day into a charging fleet model")
    parser.add_argument("--gtfs", type=Path, required=True)
    parser.add_argument("--operations", type=Path, required=True, help="JSON with buses, sites, assignments and charge windows")
    parser.add_argument("--service-date", type=date.fromisoformat, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--license")
    parser.add_argument("--output", type=Path, required=True, help="FleetInput JSON")
    parser.add_argument("--manifest", type=Path, required=True, help="Provenance JSON")
    args = parser.parse_args()
    if len({path.resolve() for path in (args.gtfs, args.operations, args.output, args.manifest)}) != 4:
        parser.error("input and output paths must all differ")
    try:
        operations = FleetOperations.model_validate_json(args.operations.read_bytes())
        fleet, metadata = import_gtfs(args.gtfs.read_bytes(), operations,
                                      service_date=args.service_date, source=args.source, license=args.license)
        args.output.write_text(json.dumps(fleet.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        args.manifest.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
