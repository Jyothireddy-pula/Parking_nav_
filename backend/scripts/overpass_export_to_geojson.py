"""Converts a raw Overpass API JSON response into a GeoJSON FeatureCollection
labeled EXTERNAL_MAP_REFERENCE (Module 1B, Step 1).

This is a starting skeleton only. Nothing this script produces may be
copied into a Module 1 campus config as-is: every point/shape still needs
physical GPS-walk verification and satellite-view correction (Module 1B,
Steps 2-3) before it can be labeled REAL. Capacity numbers are never
derivable from this data at all (rule: capacity must come from a
physical count) and this script does not attempt to produce any.

Usage:
    python -m scripts.overpass_export_to_geojson \\
        --input raw_overpass_response.json --output skeleton.geojson
"""

import argparse
import json
from pathlib import Path


def _node_lookup(elements: list[dict]) -> dict[int, tuple[float, float]]:
    return {e["id"]: (e["lon"], e["lat"]) for e in elements if e["type"] == "node" and "lat" in e}


def convert(raw: dict) -> dict:
    elements = raw["elements"]
    nodes = _node_lookup(elements)

    features = []
    for element in elements:
        tags = element.get("tags")
        if not tags:
            continue

        if element["type"] == "node":
            geometry = {"type": "Point", "coordinates": list(nodes[element["id"]])}
        elif element["type"] == "way":
            node_ids = element.get("nodes", [])
            coordinates = [list(nodes[n]) for n in node_ids if n in nodes]
            if len(coordinates) < 2:
                continue
            is_closed = len(coordinates) >= 4 and coordinates[0] == coordinates[-1]
            geometry = (
                {"type": "Polygon", "coordinates": [coordinates]}
                if is_closed
                else {"type": "LineString", "coordinates": coordinates}
            )
        else:
            continue

        features.append(
            {
                "type": "Feature",
                "properties": {
                    "osm_type": element["type"],
                    "osm_id": element["id"],
                    "provenance": "EXTERNAL_MAP_REFERENCE",
                    **tags,
                },
                "geometry": geometry,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    geojson = convert(raw)
    args.output.write_text(json.dumps(geojson, indent=2), encoding="utf-8")
    print(f"[OK] wrote {len(geojson['features'])} feature(s) to {args.output}")


if __name__ == "__main__":
    main()
