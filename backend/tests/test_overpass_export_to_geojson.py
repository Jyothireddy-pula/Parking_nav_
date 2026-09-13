from scripts.overpass_export_to_geojson import convert

SAMPLE_RAW = {
    "elements": [
        {"type": "node", "id": 1, "lat": 16.5, "lon": 80.5},
        {"type": "node", "id": 2, "lat": 16.51, "lon": 80.5},
        {"type": "node", "id": 3, "lat": 16.51, "lon": 80.51},
        {"type": "node", "id": 4, "lat": 16.5, "lon": 80.51},
        {
            "type": "way",
            "id": 100,
            "nodes": [1, 2, 3, 4, 1],
            "tags": {"building": "yes", "name": "AB-1"},
        },
        {
            "type": "way",
            "id": 101,
            "nodes": [1, 2],
            "tags": {"highway": "footway"},
        },
        {"type": "node", "id": 5, "lat": 16.505, "lon": 80.505, "tags": {"barrier": "gate"}},
        {"type": "node", "id": 6, "lat": 16.506, "lon": 80.506},  # untagged node, skipped
    ]
}


def test_polygon_way_is_converted_correctly() -> None:
    geojson = convert(SAMPLE_RAW)

    building = next(f for f in geojson["features"] if f["properties"].get("osm_id") == 100)
    assert building["geometry"]["type"] == "Polygon"
    assert building["properties"]["name"] == "AB-1"
    assert building["properties"]["provenance"] == "EXTERNAL_MAP_REFERENCE"


def test_open_way_becomes_linestring() -> None:
    geojson = convert(SAMPLE_RAW)

    road = next(f for f in geojson["features"] if f["properties"].get("osm_id") == 101)
    assert road["geometry"]["type"] == "LineString"
    assert len(road["geometry"]["coordinates"]) == 2


def test_tagged_node_becomes_point() -> None:
    geojson = convert(SAMPLE_RAW)

    gate = next(f for f in geojson["features"] if f["properties"].get("osm_id") == 5)
    assert gate["geometry"]["type"] == "Point"
    assert gate["geometry"]["coordinates"] == [80.505, 16.505]


def test_untagged_elements_are_excluded() -> None:
    geojson = convert(SAMPLE_RAW)

    ids = {f["properties"]["osm_id"] for f in geojson["features"]}
    assert 6 not in ids
    assert 1 not in ids  # plain nodes with no tags aren't features on their own


def test_every_feature_is_labeled_external_map_reference() -> None:
    geojson = convert(SAMPLE_RAW)

    assert all(f["properties"]["provenance"] == "EXTERNAL_MAP_REFERENCE" for f in geojson["features"])
