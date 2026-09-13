from pathlib import Path

import pytest
import yaml

from app.config_loader.loader import load_campus_config_file
from scripts.gps_survey_to_config import SurveyConversionError, convert_and_validate

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_GPX = FIXTURES_DIR / "sample_survey.gpx"
SAMPLE_CSV = FIXTURES_DIR / "sample_waypoints.csv"


def test_conversion_produces_a_valid_module_1_config() -> None:
    config = convert_and_validate(SAMPLE_GPX, SAMPLE_CSV, "test-campus", "Test Campus", "Asia/Kolkata")

    assert config.campus_id == "test-campus"
    assert {g.gate_id for g in config.gates} == {"test-gate"}
    assert {d.destination_id for d in config.destinations} == {"test-dest"}
    assert {p.parking_lot_id for p in config.parking_lots} == {"test-lot"}
    assert {r.road_id for r in config.roads} == {"road-1", "road-2"}


def test_road_geometry_preserves_walked_point_order() -> None:
    config = convert_and_validate(SAMPLE_GPX, SAMPLE_CSV, "test-campus", "Test Campus", "Asia/Kolkata")

    road_1 = next(r for r in config.roads if r.road_id == "road-1")
    points = [(p.lat, p.lng) for p in road_1.geometry]

    assert points == [
        (12.00000, 77.00000),
        (12.00050, 77.00050),
        (12.00080, 77.00080),
        (12.00120, 77.00120),
    ]


def test_road_length_is_computed_from_the_walked_track() -> None:
    config = convert_and_validate(SAMPLE_GPX, SAMPLE_CSV, "test-campus", "Test Campus", "Asia/Kolkata")

    road_1 = next(r for r in config.roads if r.road_id == "road-1")

    # ~170m for this track given the coordinate deltas; not a guess, computed
    # via haversine over the recorded points.
    assert 100 < road_1.length < 250


def test_parking_lot_perimeter_and_center_are_captured() -> None:
    config = convert_and_validate(SAMPLE_GPX, SAMPLE_CSV, "test-campus", "Test Campus", "Asia/Kolkata")

    lot = next(p for p in config.parking_lots if p.parking_lot_id == "test-lot")

    assert lot.geometry is not None
    assert len(lot.geometry) == 5
    assert lot.center is not None
    assert lot.center.lat == pytest.approx(12.00120)


def test_missing_gpx_reference_is_rejected_not_guessed(tmp_path: Path) -> None:
    bad_csv = tmp_path / "waypoints.csv"
    bad_csv.write_text(
        SAMPLE_CSV.read_text(encoding="utf-8").replace("wpt_gate", "wpt_gate_does_not_exist"),
        encoding="utf-8",
    )

    with pytest.raises(SurveyConversionError) as exc_info:
        convert_and_validate(SAMPLE_GPX, bad_csv, "test-campus", "Test Campus", "Asia/Kolkata")

    assert any("not found in GPX" in error for error in exc_info.value.errors)


def test_missing_expected_travel_time_is_rejected_not_guessed(tmp_path: Path) -> None:
    bad_csv = tmp_path / "waypoints.csv"
    lines = SAMPLE_CSV.read_text(encoding="utf-8").splitlines()
    lines = [line if not line.startswith("road,road-1,") else line.rsplit(",", 1)[0] + "," for line in lines]
    bad_csv.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SurveyConversionError) as exc_info:
        convert_and_validate(SAMPLE_GPX, bad_csv, "test-campus", "Test Campus", "Asia/Kolkata")

    assert any("expected_travel_time" in error for error in exc_info.value.errors)


def test_end_to_end_written_yaml_loads_through_module_1_loader(tmp_path: Path) -> None:
    config = convert_and_validate(SAMPLE_GPX, SAMPLE_CSV, "test-campus", "Test Campus", "Asia/Kolkata")
    output_path = tmp_path / "test-campus.yaml"
    output_path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    reloaded = load_campus_config_file(output_path)

    assert reloaded.campus_id == "test-campus"
    assert len(reloaded.roads) == 2
