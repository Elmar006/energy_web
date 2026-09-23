"""Replace user-supplied travel times with measured OSRM road-network durations."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .contracts import DatasetReference, PlanningInput, TravelEdge


def _fetch(url: str) -> bytes:
    request = Request(url, headers={"User-Agent": "VektorPlanning/0.1 (routing matrix import)"})
    with urlopen(request, timeout=60) as response:
        raw = response.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise ValueError("OSRM response exceeds 10 MiB")
    return raw


def derive_road_edges(
    planning_input: PlanningInput,
    *,
    osrm_url: str,
    routing_dataset: str,
    routing_license: str | None = None,
    profile: str = "driving",
    max_points: int = 80,
    max_snap_meters: float = 500,
    fetch: Callable[[str], bytes] = _fetch,
) -> PlanningInput:
    parsed = urlsplit(osrm_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("OSRM URL must be an HTTP(S) service URL without credentials or query")
    if not routing_dataset.strip():
        raise ValueError("routing dataset identifier is required")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", profile):
        raise ValueError("invalid OSRM profile")
    if max_points < 2 or max_points > 100:
        raise ValueError("max_points must be 2..100")
    if not math.isfinite(max_snap_meters) or max_snap_meters <= 0:
        raise ValueError("max_snap_meters must be positive")

    group_size = max(1, max_points // 2)
    edges: list[TravelEdge] = []
    digest = hashlib.sha256()
    base = osrm_url.rstrip("/")
    for zone_start in range(0, len(planning_input.zones), group_size):
        zones = planning_input.zones[zone_start:zone_start + group_size]
        for site_start in range(0, len(planning_input.sites), group_size):
            sites = planning_input.sites[site_start:site_start + group_size]
            points = [*zones, *sites]
            coordinates = ";".join(f"{point.longitude:.7f},{point.latitude:.7f}" for point in points)
            sources = ";".join(str(index) for index in range(len(zones)))
            destinations = ";".join(str(index) for index in range(len(zones), len(points)))
            url = (f"{base}/table/v1/{profile}/{coordinates}?sources={sources}"
                   f"&destinations={destinations}&annotations=duration")
            raw = fetch(url)
            digest.update(len(raw).to_bytes(8, "big"))
            digest.update(raw)
            try:
                table = json.loads(raw)
            except json.JSONDecodeError as error:
                raise ValueError("OSRM returned invalid JSON") from error
            if not isinstance(table, dict):
                raise ValueError("OSRM returned a malformed duration matrix")
            durations = table.get("durations")
            if table.get("code") != "Ok" or not isinstance(durations, list) or len(durations) != len(zones):
                raise ValueError("OSRM returned a malformed duration matrix")
            for label, waypoints, count in (("source", table.get("sources"), len(zones)),
                                             ("destination", table.get("destinations"), len(sites))):
                if not isinstance(waypoints, list) or len(waypoints) != count:
                    raise ValueError(f"OSRM returned malformed {label} waypoints")
                for waypoint in waypoints:
                    distance = waypoint.get("distance") if isinstance(waypoint, dict) else None
                    if (isinstance(distance, bool) or not isinstance(distance, (int, float))
                            or not math.isfinite(distance) or distance < 0 or distance > max_snap_meters):
                        raise ValueError(f"OSRM {label} is too far from the road graph or malformed")
            for row_index, zone in enumerate(zones):
                row = durations[row_index]
                if not isinstance(row, list) or len(row) != len(sites):
                    raise ValueError("OSRM returned a malformed duration row")
                for column_index, site in enumerate(sites):
                    seconds = row[column_index]
                    if seconds is None:
                        continue  # No road route: never replace with a straight-line estimate.
                    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or seconds < 0:
                        raise ValueError("OSRM returned an invalid travel duration")
                    minutes = seconds / 60
                    if minutes <= zone.max_travel_minutes:
                        edges.append(TravelEdge(zone_id=zone.id, site_id=site.id, minutes=minutes))

    result = planning_input.model_copy(deep=True)
    result.travel_edges = edges
    result.datasets.append(DatasetReference(
        name="Дорожная матрица OSRM", role="routing", kind="derived",
        source=f"{base}; profile={profile}; routing_dataset={routing_dataset}",
        sha256=digest.hexdigest(),
        license=routing_license,
    ))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Build reachable zone-to-site edges using OSRM Table API")
    parser.add_argument("--scenario", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--osrm-url", default=os.environ.get("OSRM_URL"), required=not bool(os.environ.get("OSRM_URL")))
    parser.add_argument("--routing-dataset", required=True, help="Version or SHA-256 of the OSRM road graph")
    parser.add_argument("--routing-license", default=None, help="License and attribution of the road graph")
    parser.add_argument("--profile", default="driving")
    parser.add_argument("--max-points", type=int, default=80)
    parser.add_argument("--max-snap-meters", type=float, default=500)
    args = parser.parse_args()
    if args.output.resolve() == args.scenario.resolve():
        parser.error("output must differ from the input path")
    try:
        planning_input = PlanningInput.model_validate_json(args.scenario.read_bytes())
        result = derive_road_edges(planning_input, osrm_url=args.osrm_url,
                                   routing_dataset=args.routing_dataset, routing_license=args.routing_license,
                                   profile=args.profile,
                                   max_points=args.max_points, max_snap_meters=args.max_snap_meters)
        args.output.write_text(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
