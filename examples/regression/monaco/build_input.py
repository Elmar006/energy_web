"""Build a mixed-source Monaco planning input from a pinned OSM extract.

Only the POI coordinates and station/parking tags come from OSM. Demand,
equipment, prices and grid limits are copied from the explicitly synthetic
demo and are marked as assumptions. Road times are added in a separate OSRM
step so the exact response digest is retained by the routing adapter.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

try:
    import osmium
except ImportError as error:
    raise SystemExit("Install the optional case-builder dependency: pip install osmium==4.3.1") from error


PBF_SHA256 = "5104a7858b75c9a1dad86b690fe9a58f1284cd59819e76034882f5b5cbeceac7"
PBF_SOURCE = "https://download.geofabrik.de/europe/monaco-260922.osm.pbf"
OSM_LICENSE = "ODbL 1.0; © OpenStreetMap contributors"
# These IDs are data selectors, not invented coordinates or verified build permits.
ZONE_NODES = {"homes": 25239191, "taxi": 267898764, "fleet": 1880130278}
SITE_NODES = {"west": 1875160729, "centre": 13302048342,
              "east": 1079750865, "south": 25191432}


class SelectedNodes(osmium.SimpleHandler):
    def __init__(self, ids: set[int]):
        super().__init__()
        self.ids = ids
        self.found: dict[int, dict] = {}

    def node(self, node):
        if node.id in self.ids:
            self.found[node.id] = {
                "latitude": node.location.lat, "longitude": node.location.lon,
                "tags": dict(node.tags),
            }


def build_case(demo: dict, pbf: Path) -> dict:
    digest = hashlib.sha256(pbf.read_bytes()).hexdigest()
    if digest != PBF_SHA256:
        raise ValueError(f"OSM extract SHA-256 mismatch: {digest}; use {PBF_SOURCE}")
    selector = SelectedNodes(set(ZONE_NODES.values()) | set(SITE_NODES.values()))
    selector.apply_file(str(pbf))
    missing = selector.ids - selector.found.keys()
    if missing:
        raise ValueError(f"OSM nodes absent from pinned extract: {sorted(missing)}")
    output = json.loads(json.dumps(demo))
    output["id"] = "commission-monaco-mixed-2026-09-22"
    output["time_zone"] = "Europe/Monaco"
    for zone in output["zones"]:
        node_id = ZONE_NODES[zone["id"]]
        poi = selector.found[node_id]
        if poi["tags"].get("amenity") != "parking":
            raise ValueError(f"zone anchor {node_id} is no longer an OSM parking POI")
        zone.update(latitude=poi["latitude"], longitude=poi["longitude"])
        zone["name"] = f"Сценарный спрос у {poi['tags'].get('name', 'парковки')}"
        zone["provenance"] = {
            "kind": "assumed",
            "source": f"Спрос и профиль синтетические (examples/demo.json); только географический якорь OSM node/{node_id} из {PBF_SOURCE}",
        }
    for site in output["sites"]:
        node_id = SITE_NODES[site["id"]]
        poi = selector.found[node_id]
        expected = "charging_station" if site["id"] == "centre" else "parking"
        if poi["tags"].get("amenity") != expected:
            raise ValueError(f"site {node_id} does not have expected OSM tag {expected}")
        if poi["tags"].get("access") == "private":
            raise ValueError(f"site {node_id} is tagged private")
        site.update(latitude=poi["latitude"], longitude=poi["longitude"])
        site["name"] = poi["tags"].get("name", "Зарядная станция OSM" if site["id"] == "centre" else "Парковка OSM")
        site["provenance"] = {
            "kind": "assumed",
            "source": f"OSM node/{node_id} фиксирует только геопозицию и POI; оборудование, право строительства и подключение не подтверждены. {PBF_SOURCE}",
        }
        if site["id"] == "centre":
            # OSM capacity=2 does not establish charger power or connection.
            if poi["tags"].get("capacity") != "2":
                raise ValueError("existing POI capacity tag changed")
            site["existing_option_id"] = "ac"
            site["option_ids"] = ["ac"]
        else:
            site["existing_option_id"] = None
    for node in output["grid_nodes"]:
        node["provenance"] = {
            "kind": "assumed",
            "source": "Сценарные лимиты из examples/demo.json; сетевой организацией не подтверждены",
        }
    output["travel_edges"] = []  # generated from the pinned road graph by energy.routing
    output["datasets"] = [
        {"name": "Monaco OSM POIs and roads 2026-09-22", "role": "other",
         "kind": "observed", "source": PBF_SOURCE, "sha256": digest,
         "license": OSM_LICENSE, "transform_version": "commission-poi-v1"},
        {"name": "Scenario assumptions from demo", "role": "planning_assumptions",
         "kind": "assumed", "source": "examples/demo.json; not Monaco measurements",
         "sha256": hashlib.sha256(json.dumps(demo, ensure_ascii=False, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest(),
         "transform_version": "commission-poi-v1"},
    ]
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pbf", type=Path, required=True)
    parser.add_argument("--demo", type=Path, default=Path("examples/demo.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = build_case(json.loads(args.demo.read_text(encoding="utf-8")), args.pbf)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
