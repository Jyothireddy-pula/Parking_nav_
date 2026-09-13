"""Convert a GPS field survey (GPX tracks/waypoints + a waypoint CSV) into a
Module 1 campus configuration YAML file.

This is Module 1B's only piece of application code — everything else in
Module 1B is the physical survey itself (Overpass/OSM lookup, the phone GPS
walk, satellite-view verification). This script does not invent or guess
anything: any CSV row whose GPX reference is missing from the GPX file is
rejected outright, and road/parking-lot geometry is taken directly from the
walked track in recorded order — never reordered, straightened, or
interpolated.

Usage:
    python -m scripts.gps_survey_to_config \\
        --gpx survey.gpx --waypoints waypoints.csv \\
        --campus-id vitap --campus-name "VIT-AP University" \\
        --timezone Asia/Kolkata --output config.yaml
"""

import argparse
import csv
import math
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.config_loader.loader import _format_pydantic_errors
from app.config_loader.schema import CampusConfigFile
from app.config_loader.validators import validate_campus_config

GPX_NAMESPACE = "{http://www.topografix.com/GPX/1/1}"

LIST_COLUMNS = ("department_names", "searchable_aliases", "nearest_gates", "nearest_parking_lots")
BOOL_COLUMNS = ("camera_available", "is_walkable", "is_driveable")
INT_COLUMNS = (
    "capacity",
    "total_capacity",
    "usable_capacity",
    "reserved_capacity",
    "restricted_capacity",
    "temporarily_unavailable_capacity",
)
FLOAT_COLUMNS = ("expected_travel_time",)


class SurveyConversionError(Exception):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ParsedGpx:
    waypoints: dict[str, tuple[float, float]] = field(default_factory=dict)
    tracks: dict[str, list[tuple[float, float]]] = field(default_factory=dict)


def parse_gpx(path: Path) -> ParsedGpx:
    tree = ET.parse(path)
    root = tree.getroot()
    parsed = ParsedGpx()

    for wpt in root.findall(f"{GPX_NAMESPACE}wpt"):
        name_el = wpt.find(f"{GPX_NAMESPACE}name")
        if name_el is None or not name_el.text:
            continue
        parsed.waypoints[name_el.text.strip()] = (float(wpt.attrib["lat"]), float(wpt.attrib["lon"]))

    for trk in root.findall(f"{GPX_NAMESPACE}trk"):
        name_el = trk.find(f"{GPX_NAMESPACE}name")
        if name_el is None or not name_el.text:
            continue
        points: list[tuple[float, float]] = []
        for trkseg in trk.findall(f"{GPX_NAMESPACE}trkseg"):
            for trkpt in trkseg.findall(f"{GPX_NAMESPACE}trkpt"):
                points.append((float(trkpt.attrib["lat"]), float(trkpt.attrib["lon"])))
        parsed.tracks[name_el.text.strip()] = points

    return parsed


def _haversine_meters(a: tuple[float, float], b: tuple[float, float]) -> float:
    earth_radius_m = 6371000.0
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * earth_radius_m * math.asin(math.sqrt(h))


def _track_length_meters(points: list[tuple[float, float]]) -> float:
    return sum(_haversine_meters(points[i], points[i + 1]) for i in range(len(points) - 1))


def _points_to_coords(points: list[tuple[float, float]]) -> list[dict]:
    return [{"lat": lat, "lng": lng} for lat, lng in points]


def _split_list_cell(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(";") if item.strip()]


def _read_rows(csv_path: Path) -> list[dict]:
    with csv_path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def convert(gpx_path: Path, csv_path: Path, campus_id: str, campus_name: str, timezone: str) -> dict:
    gpx = parse_gpx(gpx_path)
    rows = _read_rows(csv_path)

    errors: list[str] = []
    gates: list[dict] = []
    parking_lots: list[dict] = []
    destinations: list[dict] = []
    roads: list[dict] = []

    for row in rows:
        entity_type = (row.get("entity_type") or "").strip()
        entity_id = (row.get("entity_id") or "").strip()
        if not entity_type or not entity_id:
            errors.append(f"row missing entity_type/entity_id: {row!r}")
            continue

        for column in LIST_COLUMNS:
            row[column] = _split_list_cell(row.get(column) or "")
        for column in BOOL_COLUMNS:
            row[column] = (row.get(column) or "").strip().lower() in {"true", "1", "yes"}
        for column in INT_COLUMNS:
            raw = (row.get(column) or "").strip()
            row[column] = int(raw) if raw else 0
        for column in FLOAT_COLUMNS:
            raw = (row.get(column) or "").strip()
            row[column] = float(raw) if raw else None
        row["status"] = (row.get("status") or "open").strip()
        row["camera_notes"] = (row.get("camera_notes") or "").strip() or None
        row["category"] = (row.get("category") or "").strip()

        if entity_type == "gate":
            gpx_ref = (row.get("gpx_ref") or "").strip()
            if gpx_ref not in gpx.waypoints:
                errors.append(f"gate {entity_id!r} references waypoint {gpx_ref!r}, not found in GPX")
                continue
            lat, lng = gpx.waypoints[gpx_ref]
            gates.append(
                {
                    "gate_id": entity_id,
                    "name": row.get("name") or entity_id,
                    "coordinates": {"lat": lat, "lng": lng},
                    "capacity": row["capacity"],
                    "status": row["status"],
                    "provenance": "REAL",
                }
            )

        elif entity_type == "destination":
            gpx_ref = (row.get("gpx_ref") or "").strip()
            if gpx_ref not in gpx.waypoints:
                errors.append(f"destination {entity_id!r} references waypoint {gpx_ref!r}, not found in GPX")
                continue
            lat, lng = gpx.waypoints[gpx_ref]
            destinations.append(
                {
                    "destination_id": entity_id,
                    "name": row.get("name") or entity_id,
                    "category": row["category"],
                    "coordinates": {"lat": lat, "lng": lng},
                    "department_names": row["department_names"],
                    "searchable_aliases": row["searchable_aliases"],
                    "nearest_gates": row["nearest_gates"],
                    "nearest_parking_lots": row["nearest_parking_lots"],
                    "provenance": "REAL",
                }
            )

        elif entity_type == "parking_lot":
            perimeter_ref = (row.get("gpx_ref") or "").strip()
            center_ref = (row.get("center_gpx_ref") or "").strip()
            lot_errors = []
            if perimeter_ref not in gpx.tracks:
                lot_errors.append(
                    f"parking_lot {entity_id!r} references perimeter track {perimeter_ref!r}, not found in GPX"
                )
            if center_ref not in gpx.waypoints:
                lot_errors.append(
                    f"parking_lot {entity_id!r} references center waypoint {center_ref!r}, not found in GPX"
                )
            if lot_errors:
                errors.extend(lot_errors)
                continue
            center_lat, center_lng = gpx.waypoints[center_ref]
            parking_lots.append(
                {
                    "parking_lot_id": entity_id,
                    "name": row.get("name") or entity_id,
                    "status": row["status"],
                    "camera_available": row["camera_available"],
                    "camera_notes": row["camera_notes"],
                    "center": {"lat": center_lat, "lng": center_lng},
                    "geometry": _points_to_coords(gpx.tracks[perimeter_ref]),
                    "total_capacity": row["total_capacity"],
                    "usable_capacity": row["usable_capacity"],
                    "reserved_capacity": row["reserved_capacity"],
                    "restricted_capacity": row["restricted_capacity"],
                    "temporarily_unavailable_capacity": row["temporarily_unavailable_capacity"],
                    "provenance": "REAL",
                }
            )

        elif entity_type == "road":
            gpx_ref = (row.get("gpx_ref") or "").strip()
            start_node = (row.get("start_node") or "").strip()
            end_node = (row.get("end_node") or "").strip()
            road_errors = []
            if gpx_ref not in gpx.tracks:
                road_errors.append(f"road {entity_id!r} references track {gpx_ref!r}, not found in GPX")
            if not start_node:
                road_errors.append(f"road {entity_id!r} is missing start_node")
            if not end_node:
                road_errors.append(f"road {entity_id!r} is missing end_node")
            if row["expected_travel_time"] is None:
                road_errors.append(
                    f"road {entity_id!r} is missing expected_travel_time (must be measured, not guessed)"
                )
            if road_errors:
                errors.extend(road_errors)
                continue
            track_points = gpx.tracks[gpx_ref]
            roads.append(
                {
                    "road_id": entity_id,
                    "name": row.get("name") or entity_id,
                    "start_node": start_node,
                    "end_node": end_node,
                    "length": _track_length_meters(track_points),
                    "expected_travel_time": row["expected_travel_time"],
                    "is_walkable": row["is_walkable"],
                    "is_driveable": row["is_driveable"],
                    "status": row["status"],
                    "geometry": _points_to_coords(track_points),
                    "provenance": "REAL",
                }
            )

        else:
            errors.append(f"row {entity_id!r} has unknown entity_type {entity_type!r}")

    if errors:
        raise SurveyConversionError(errors)

    return {
        "campus_id": campus_id,
        "name": campus_name,
        "timezone": timezone,
        "gates": gates,
        "roads": roads,
        "parking_lots": parking_lots,
        "destinations": destinations,
        "events": [],
    }


def convert_and_validate(
    gpx_path: Path, csv_path: Path, campus_id: str, campus_name: str, timezone: str
) -> CampusConfigFile:
    raw_config = convert(gpx_path, csv_path, campus_id, campus_name, timezone)

    try:
        config = CampusConfigFile.model_validate(raw_config)
    except ValidationError as exc:
        raise SurveyConversionError(_format_pydantic_errors(exc)) from exc

    cross_entity_errors = validate_campus_config(config)
    if cross_entity_errors:
        raise SurveyConversionError(cross_entity_errors)

    return config


def _dump_yaml(config: CampusConfigFile, output_path: Path) -> None:
    output_path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpx", required=True, type=Path)
    parser.add_argument("--waypoints", required=True, type=Path, help="Waypoint/track mapping CSV")
    parser.add_argument("--campus-id", required=True)
    parser.add_argument("--campus-name", required=True)
    parser.add_argument("--timezone", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    try:
        config = convert_and_validate(
            args.gpx, args.waypoints, args.campus_id, args.campus_name, args.timezone
        )
    except SurveyConversionError as exc:
        print(f"[FAIL] {len(exc.errors)} error(s) converting survey data:", file=sys.stderr)
        for error in exc.errors:
            print(f"    - {error}", file=sys.stderr)
        raise SystemExit(1) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    _dump_yaml(config, args.output)
    print(f"[OK] wrote {args.output} (campus {config.campus_id!r})")


if __name__ == "__main__":
    main()
