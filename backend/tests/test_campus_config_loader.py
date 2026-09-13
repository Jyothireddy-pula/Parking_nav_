from pathlib import Path

import pytest

from app.config_loader.exceptions import ConfigValidationError
from app.config_loader.loader import load_campus_config_file

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


def test_sample_campus_config_loads_cleanly() -> None:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)

    assert config.campus_id == "sample"
    assert len(config.gates) == 2
    assert len(config.parking_lots) == 1
    assert len(config.destinations) == 2
    assert len(config.roads) == 4


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_campus_config_file(tmp_path / "does-not-exist.yaml")


def test_empty_file_raises_config_validation_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ConfigValidationError):
        load_campus_config_file(path)


def test_invalid_file_reports_cross_entity_errors(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text(
        """
campus_id: broken
name: Broken Campus
timezone: Asia/Kolkata
gates:
  - gate_id: g1
    name: Gate 1
    coordinates: { lat: 12.0, lng: 77.0 }
    capacity: 10
    provenance: SAMPLE
parking_lots: []
destinations: []
roads: []
events: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ConfigValidationError) as exc_info:
        load_campus_config_file(path)

    assert any("orphaned from the routable graph" in error for error in exc_info.value.errors)
