import copy

import pytest
from pydantic import ValidationError

from app.config_loader.exceptions import ConfigValidationError
from app.config_loader.schema import CampusConfigFile
from app.config_loader.validators import validate_campus_config

BASE_CONFIG: dict = {
    "campus_id": "sample",
    "name": "Sample Campus",
    "timezone": "Asia/Kolkata",
    "gates": [
        {
            "gate_id": "g1",
            "name": "Gate 1",
            "coordinates": {"lat": 12.0, "lng": 77.0},
            "capacity": 10,
            "status": "open",
        },
    ],
    "parking_lots": [
        {
            "parking_lot_id": "p1",
            "name": "Lot 1",
            "status": "open",
            "total_capacity": 100,
            "usable_capacity": 90,
            "reserved_capacity": 5,
            "restricted_capacity": 3,
            "temporarily_unavailable_capacity": 2,
        },
    ],
    "destinations": [
        {
            "destination_id": "d1",
            "name": "Destination 1",
            "category": "academic_block",
            "coordinates": {"lat": 12.001, "lng": 77.001},
            "nearest_gates": ["g1"],
            "nearest_parking_lots": ["p1"],
        },
    ],
    "roads": [
        {
            "road_id": "r1",
            "name": "Road 1",
            "start_node": "g1",
            "end_node": "p1",
            "length": 100.0,
            "expected_travel_time": 60.0,
            "is_walkable": True,
            "is_driveable": True,
            "geometry": [
                {"lat": 12.0, "lng": 77.0},
                {"lat": 12.0005, "lng": 77.0005},
                {"lat": 12.001, "lng": 77.001},
            ],
        },
        {
            "road_id": "r2",
            "name": "Road 2",
            "start_node": "p1",
            "end_node": "d1",
            "length": 50.0,
            "expected_travel_time": 30.0,
            "is_walkable": True,
            "is_driveable": False,
            "geometry": [
                {"lat": 12.001, "lng": 77.001},
                {"lat": 12.0012, "lng": 77.0012},
                {"lat": 12.0015, "lng": 77.0015},
            ],
        },
    ],
    "events": [],
}


def _config(**overrides) -> dict:
    config = copy.deepcopy(BASE_CONFIG)
    config.update(overrides)
    return config


def test_valid_config_parses_and_passes_cross_validation() -> None:
    parsed = CampusConfigFile.model_validate(BASE_CONFIG)
    assert validate_campus_config(parsed) == []


def test_duplicate_gate_id_is_rejected() -> None:
    config = _config(gates=BASE_CONFIG["gates"] + BASE_CONFIG["gates"])
    parsed = CampusConfigFile.model_validate(config)

    errors = validate_campus_config(parsed)

    assert any("duplicate gate_id" in error for error in errors)


def test_negative_capacity_is_rejected_at_schema_level() -> None:
    config = _config(gates=[{**BASE_CONFIG["gates"][0], "capacity": -5}])

    with pytest.raises(ValidationError):
        CampusConfigFile.model_validate(config)


def test_capacity_breakdown_exceeding_total_is_rejected() -> None:
    config = _config(
        parking_lots=[{**BASE_CONFIG["parking_lots"][0], "usable_capacity": 999}],
    )

    with pytest.raises(ValidationError):
        CampusConfigFile.model_validate(config)


def test_malformed_coordinates_are_rejected() -> None:
    config = _config(gates=[{**BASE_CONFIG["gates"][0], "coordinates": {"lat": 999, "lng": 77.0}}])

    with pytest.raises(ValidationError):
        CampusConfigFile.model_validate(config)


def test_road_geometry_with_only_two_endpoints_is_rejected() -> None:
    config = _config(
        roads=[
            {
                **BASE_CONFIG["roads"][0],
                "geometry": [{"lat": 12.0, "lng": 77.0}, {"lat": 12.001, "lng": 77.001}],
            },
            BASE_CONFIG["roads"][1],
        ]
    )

    with pytest.raises(ValidationError):
        CampusConfigFile.model_validate(config)


def test_road_referencing_nonexistent_node_is_rejected() -> None:
    config = _config(
        roads=[
            {**BASE_CONFIG["roads"][0], "start_node": "does-not-exist"},
            BASE_CONFIG["roads"][1],
        ]
    )
    parsed = CampusConfigFile.model_validate(config)

    errors = validate_campus_config(parsed)

    assert any("does not reference an existing" in error for error in errors)


def test_orphan_node_is_rejected() -> None:
    # d1 is defined but no road connects to it, since we drop road r2.
    config = _config(roads=[BASE_CONFIG["roads"][0]])
    parsed = CampusConfigFile.model_validate(config)

    errors = validate_campus_config(parsed)

    assert any("orphaned from the routable graph" in error for error in errors)


def test_destination_referencing_unknown_gate_is_rejected() -> None:
    config = _config(
        destinations=[{**BASE_CONFIG["destinations"][0], "nearest_gates": ["no-such-gate"]}],
    )
    parsed = CampusConfigFile.model_validate(config)

    errors = validate_campus_config(parsed)

    assert any("unknown gate" in error for error in errors)


def test_reused_node_id_across_entity_types_is_rejected() -> None:
    config = _config(
        parking_lots=[{**BASE_CONFIG["parking_lots"][0], "parking_lot_id": "g1"}],
    )
    parsed = CampusConfigFile.model_validate(config)

    errors = validate_campus_config(parsed)

    assert any("reused across gates/parking_lots/destinations" in error for error in errors)


def test_config_validation_error_carries_every_error() -> None:
    config = _config(gates=BASE_CONFIG["gates"] + BASE_CONFIG["gates"])
    parsed = CampusConfigFile.model_validate(config)
    errors = validate_campus_config(parsed)

    exc = ConfigValidationError(errors)

    assert exc.errors == errors
