"""Proves what's actually true about the real VIT-AP data pulled from
OpenStreetMap (Module 1B, Step 1): the names and coordinates are real,
each entity is individually well-formed, but the campus as a whole is
correctly rejected as incomplete — no gates, parking lots, or roads
exist yet to connect these 11 buildings into a routable graph. This is
Module 1's orphan-node check doing exactly its job: real data isn't the
same as usable data, and the system doesn't pretend otherwise.
"""

from pathlib import Path

import pytest
import yaml

from app.config_loader.exceptions import ConfigValidationError
from app.config_loader.loader import load_campus_config_file
from app.config_loader.schema import CampusConfigFile

REPO_ROOT = Path(__file__).resolve().parents[2]
VITAP_CANDIDATE_PATH = REPO_ROOT / "configs" / "campuses" / "vitap" / "real_survey" / "vitap_candidate.yaml"


def test_vitap_candidate_file_exists() -> None:
    assert VITAP_CANDIDATE_PATH.exists()


def test_every_entity_is_individually_well_formed() -> None:
    # Schema-level parsing succeeds: real names, real coordinates, valid
    # categories, valid provenance labels. It's the cross-entity
    # (connectivity) check that correctly fails — see the test below.
    raw = VITAP_CANDIDATE_PATH.read_text(encoding="utf-8")
    config = CampusConfigFile.model_validate(yaml.safe_load(raw))

    assert config.campus_id == "vitap"
    assert len(config.destinations) == 11
    assert all(d.provenance == "EXTERNAL_MAP_REFERENCE" for d in config.destinations)
    assert {d.name for d in config.destinations} == {
        "AB-1", "AB-2", "CB", "Food Street", "MH-1", "MH-2", "MH-2 Food Store",
        "MH-3", "MH-6", "MH-7", "LH-1",
    }


def test_loading_it_for_real_fails_on_orphan_nodes_not_silently() -> None:
    with pytest.raises(ConfigValidationError) as exc_info:
        load_campus_config_file(VITAP_CANDIDATE_PATH)

    errors = exc_info.value.errors
    orphan_errors = [e for e in errors if "orphaned from the routable graph" in e]
    # Every destination is orphaned: there are no roads/gates/lots yet.
    assert len(orphan_errors) == 11
