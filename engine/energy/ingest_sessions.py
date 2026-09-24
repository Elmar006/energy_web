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

import numpy as np

from .contracts import DatasetReference, PlanningInput, Provenance, SessionArrivalProfile

REQUIRED_COLUMNS = {"session_id", "zone_id", "started_at", "ended_at", "energy_kwh"}
TRANSFORM_VERSION = "metered-sessions-v3"


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
    coverage_complete: bool = False,
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
    daily_arrivals: dict[str, dict[date, list[int]]] = {item.id: {} for item in planning_input.zones}
    session_energies: dict[str, list[float]] = {item.id: [] for item in planning_input.zones}
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
        local_start = started_utc.astimezone(zone)
        local_day = daily_arrivals[zone_id].setdefault(local_start.date(), [0] * 24)
        local_day[local_start.hour] += 1
        session_energies[zone_id].append(energy)

    missing = sorted(zone_id for zone_id, count in counts.items() if count == 0)
    if missing:
        raise ValueError("no sessions for zones: " + ", ".join(missing))
    days = (end_date - start_date).days + 1
    gaps = {zone_id: [start_date + timedelta(days=day) for day in range(days)
                      if start_date + timedelta(days=day) not in daily_arrivals[zone_id]]
            for zone_id in sorted(zone_ids)}
    gaps = {zone_id: dates for zone_id, dates in gaps.items() if dates}
    if gaps and not coverage_complete:
        example_zone = next(iter(gaps))
        raise ValueError(f"missing session records for {example_zone} on {gaps[example_zone][0]}; "
                         "set coverage_complete=true only if the export covers every zone and day "
                         "and these are confirmed zero-session days")
    checksum = hashlib.sha256(csv_bytes).hexdigest()
    result = planning_input.model_copy(deep=True)
    for item in result.zones:
        item.hourly_kwh = [value / days for value in totals[item.id]]
        energies = session_energies[item.id]
        item.mean_session_kwh = sum(energies) / len(energies)
        item.provenance = Provenance(
            kind="derived",
            source=f"{source}; CSV SHA-256 {checksum}; {start_date}..{end_date}; "
                   f"{time_zone}; input_kind={kind}; coverage_complete={coverage_complete}; "
                   "session energy apportioned by duration",
        )
        daily = [daily_arrivals[item.id].get(start_date + timedelta(days=day), [0] * 24)
                 for day in range(days)]
        arrivals = [sum(row[hour] for row in daily) / days for hour in range(24)]
        variances = [float(np.var([row[hour] for row in daily], ddof=1)) if days > 1 else 0.0
                     for hour in range(24)]
        item.arrival_profile = SessionArrivalProfile(
            hourly_sessions=arrivals,
            hourly_count_variance=variances,
            energy_quantiles_kwh=[float(value) for value in np.quantile(
                energies, np.linspace(0, 1, 101), method="inverted_cdf")],
            sample_count=len(energies), observation_days=days,
            days_with_sessions=len(daily_arrivals[item.id]), coverage_complete=coverage_complete,
            source_kind=kind,
            hourly_load_method="uniform_session_duration",
            provenance=Provenance(kind="derived",
                                  source=f"{source}; CSV SHA-256 {checksum}; {start_date}..{end_date}; "
                                         f"{time_zone}; input_kind={kind}; coverage_complete={coverage_complete}; "
                                         "starts and delivered session energy"),
        )
    result.datasets.append(DatasetReference(
        name="Зарядные сессии", role="demand_sessions", kind=kind,
        source=source, sha256=checksum, license=license,
        transform_version=TRANSFORM_VERSION,
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
    parser.add_argument("--coverage-complete", action="store_true",
                        help="Assert every zone and day was covered by the export, including zero-session days")
    args = parser.parse_args()
    if args.output.resolve() in {args.scenario.resolve(), args.sessions.resolve()}:
        parser.error("output must differ from input paths")
    try:
        planning_input = PlanningInput.model_validate_json(args.scenario.read_bytes())
        result = derive_demand(planning_input, args.sessions.read_bytes(), source=args.source,
                               license=args.license, kind=args.kind, time_zone=args.time_zone,
                               start_date=args.start_date, end_date=args.end_date,
                               coverage_complete=args.coverage_complete)
        args.output.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
