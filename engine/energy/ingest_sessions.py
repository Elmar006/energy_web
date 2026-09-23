"""Derive hourly energy demand from metered charging sessions.

This adapter reports observed delivered energy, not latent unmet demand. A missing
zone is rejected rather than interpreted as zero demand.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo
from zoneinfo import ZoneInfoNotFoundError

from .contracts import DatasetReference, PlanningInput, Provenance

REQUIRED_COLUMNS = {"session_id", "zone_id", "started_at", "ended_at", "energy_kwh"}


def derive_demand(
    planning_input: PlanningInput,
    csv_bytes: bytes,
    *,
    source: str,
    time_zone: str,
    start_date: date,
    end_date: date,
    license: str | None = None,
    kind: Literal["observed", "assumed"] = "assumed",
) -> PlanningInput:
    if not source.strip():
        raise ValueError("source description is required")
    if end_date < start_date or (end_date - start_date).days > 366:
        raise ValueError("observation window must be 1 to 367 calendar days")
    if len(csv_bytes) > 50 * 1024 * 1024:
        raise ValueError("sessions CSV exceeds 50 MiB")
    try:
        zone = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown IANA time zone: {time_zone}") from error
    try:
        content = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("sessions CSV must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(content, newline=""))
    if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
        raise ValueError("sessions CSV requires session_id,zone_id,started_at,ended_at,energy_kwh")

    zone_ids = {item.id for item in planning_input.zones}
    totals = {item.id: [0.0] * 24 for item in planning_input.zones}
    counts = {item.id: 0 for item in planning_input.zones}
    seen: set[str] = set()
    window_start = datetime.combine(start_date, datetime.min.time(), zone)
    window_end = datetime.combine(end_date + timedelta(days=1), datetime.min.time(), zone)

    for row_number, row in enumerate(reader, start=2):
        session_id = (row.get("session_id") or "").strip()
        zone_id = (row.get("zone_id") or "").strip()
        if not session_id or session_id in seen:
            raise ValueError(f"row {row_number}: missing or duplicate session_id")
        seen.add(session_id)
        if zone_id not in zone_ids:
            raise ValueError(f"row {row_number}: unknown zone_id {zone_id!r}")
        try:
            started = datetime.fromisoformat(row["started_at"])
            ended = datetime.fromisoformat(row["ended_at"])
            energy = float(row["energy_kwh"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"row {row_number}: invalid timestamp or energy_kwh") from error
        if started.tzinfo is None or ended.tzinfo is None:
            raise ValueError(f"row {row_number}: timestamps must include UTC offset")
        started_utc = started.astimezone(timezone.utc)
        ended_utc = ended.astimezone(timezone.utc)
        duration = (ended_utc - started_utc).total_seconds()
        if duration <= 0 or duration > 72 * 3600 or not math.isfinite(energy) or energy <= 0:
            raise ValueError(f"row {row_number}: duration must be 0..72h and energy_kwh positive")
        if started_utc < window_start.astimezone(timezone.utc) or ended_utc > window_end.astimezone(timezone.utc):
            raise ValueError(f"row {row_number}: session extends outside observation window")

        cursor = started_utc
        allocated = 0.0
        while cursor < ended_utc:
            local = cursor.astimezone(zone)
            seconds_to_hour = (60 - local.minute) * 60 - local.second - local.microsecond / 1_000_000
            boundary = min(ended_utc, cursor + timedelta(seconds=seconds_to_hour))
            portion = energy * (boundary - cursor).total_seconds() / duration
            totals[zone_id][local.hour] += portion
            allocated += portion
            cursor = boundary
        if not math.isclose(allocated, energy, rel_tol=1e-10, abs_tol=1e-8):
            raise ArithmeticError(f"row {row_number}: energy was not conserved")
        counts[zone_id] += 1

    missing = sorted(zone_id for zone_id, count in counts.items() if count == 0)
    if missing:
        raise ValueError("no sessions for zones: " + ", ".join(missing))
    days = (end_date - start_date).days + 1
    checksum = hashlib.sha256(csv_bytes).hexdigest()
    result = planning_input.model_copy(deep=True)
    for item in result.zones:
        item.hourly_kwh = [value / days for value in totals[item.id]]
        item.provenance = Provenance(
            kind="derived",
            source=f"{source}; CSV SHA-256 {checksum}; {start_date}..{end_date}; "
                   f"{time_zone}; input_kind={kind}; session energy apportioned by duration",
        )
    result.datasets.append(DatasetReference(
        name="Зарядные сессии", role="demand_sessions", kind=kind,
        source=source, sha256=checksum, license=license,
    ))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build 24-hour demand profiles from metered sessions")
    parser.add_argument("--scenario", required=True, type=Path, help="Existing PlanningInput JSON")
    parser.add_argument("--sessions", required=True, type=Path, help="UTF-8 CSV of metered sessions")
    parser.add_argument("--output", required=True, type=Path, help="New PlanningInput JSON")
    parser.add_argument("--source", required=True, help="Origin and owner of the session export")
    parser.add_argument("--license", default=None)
    parser.add_argument("--kind", choices=("observed", "assumed"), default="assumed")
    parser.add_argument("--time-zone", required=True, help="IANA time zone, e.g. Europe/Moscow")
    parser.add_argument("--start-date", required=True, type=date.fromisoformat)
    parser.add_argument("--end-date", required=True, type=date.fromisoformat)
    args = parser.parse_args()
    if args.output.resolve() in {args.scenario.resolve(), args.sessions.resolve()}:
        parser.error("output must differ from input paths")
    try:
        planning_input = PlanningInput.model_validate_json(args.scenario.read_bytes())
        result = derive_demand(planning_input, args.sessions.read_bytes(), source=args.source,
                               license=args.license, kind=args.kind, time_zone=args.time_zone,
                               start_date=args.start_date, end_date=args.end_date)
        args.output.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
