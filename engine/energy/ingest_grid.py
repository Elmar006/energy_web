"""Apply an explicitly sourced 24-hour grid headroom export to a scenario."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from datetime import date
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .contracts import DatasetReference, PlanningInput, Provenance


def apply_grid_profile(
    planning_input: PlanningInput,
    csv_bytes: bytes,
    *,
    source: str,
    profile_date: date,
    time_zone: str,
    license: str | None = None,
    kind: Literal["observed", "assumed"] = "assumed",
) -> PlanningInput:
    if not source.strip():
        raise ValueError("source description is required")
    if len(csv_bytes) > 10 * 1024 * 1024:
        raise ValueError("grid CSV exceeds 10 MiB")
    try:
        ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"unknown IANA time zone: {time_zone}") from error
    try:
        content = csv_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("grid CSV must be UTF-8") from error
    reader = csv.DictReader(io.StringIO(content, newline=""))
    if not reader.fieldnames or not {"grid_node_id", "hour", "headroom_kw"}.issubset(reader.fieldnames):
        raise ValueError("grid CSV requires grid_node_id,hour,headroom_kw")

    node_ids = {node.id for node in planning_input.grid_nodes}
    hours: dict[str, dict[int, float]] = {node_id: {} for node_id in node_ids}
    for row_number, row in enumerate(reader, start=2):
        node_id = (row.get("grid_node_id") or "").strip()
        if node_id not in node_ids:
            raise ValueError(f"row {row_number}: unknown grid_node_id {node_id!r}")
        try:
            hour = int(row["hour"])
            value = float(row["headroom_kw"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"row {row_number}: invalid hour or headroom_kw") from error
        if str(hour) != row["hour"].strip() or hour not in range(24):
            raise ValueError(f"row {row_number}: hour must be an integer 0..23")
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"row {row_number}: headroom_kw must be finite and nonnegative")
        if hour in hours[node_id]:
            raise ValueError(f"row {row_number}: duplicate grid_node_id and hour")
        hours[node_id][hour] = value

    missing = [f"{node_id}: {','.join(map(str, sorted(set(range(24)) - set(values))))}"
               for node_id, values in sorted(hours.items()) if len(values) != 24]
    if missing:
        raise ValueError("missing grid hours: " + "; ".join(missing))

    checksum = hashlib.sha256(csv_bytes).hexdigest()
    result = planning_input.model_copy(deep=True)
    for node in result.grid_nodes:
        node.headroom_kw = [hours[node.id][hour] for hour in range(24)]
        node.provenance = Provenance(
            kind=kind,
            source=f"{source}; CSV SHA-256 {checksum}; {profile_date}; {time_zone}; "
                   "user-supplied available headroom profile",
        )
    result.datasets.append(DatasetReference(
        name="Почасовой резерв мощности узлов", role="grid", kind=kind,
        source=f"{source}; {profile_date}; {time_zone}", sha256=checksum,
        license=license,
    ))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Import 24-hour grid headroom profiles from an operator CSV")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--grid", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source", required=True, help="Owner and reference of the grid export")
    parser.add_argument("--profile-date", required=True, type=date.fromisoformat)
    parser.add_argument("--time-zone", required=True)
    parser.add_argument("--license", default=None)
    parser.add_argument("--kind", choices=("observed", "assumed"), default="assumed")
    args = parser.parse_args()
    if args.output.resolve() in {args.scenario.resolve(), args.grid.resolve()}:
        parser.error("output must differ from input paths")
    try:
        planning_input = PlanningInput.model_validate_json(args.scenario.read_bytes())
        result = apply_grid_profile(planning_input, args.grid.read_bytes(), source=args.source,
                                    profile_date=args.profile_date, time_zone=args.time_zone,
                                    license=args.license, kind=args.kind)
        args.output.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
