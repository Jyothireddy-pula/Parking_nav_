"""configs/campuses/vitap.yaml mixes real and fabricated data on purpose
(see that file's header): destinations are real (EXTERNAL_MAP_REFERENCE
names/coordinates from OpenStreetMap); the gate, parking lot, and every
road are fabricated SAMPLE placeholders added only so the campus is
loadable and routable before Module 1B's physical GPS walk happens. This
test file proves that mix is exactly what's in the file — nothing real
was quietly relabeled as fake, and nothing fake is mislabeled as real."""

from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.models.destination import Destination
from app.models.gate import Gate
from app.models.parking_lot import ParkingLot
from app.models.road import Road

REPO_ROOT = Path(__file__).resolve().parents[2]
VITAP_CONFIG_PATH = REPO_ROOT / "configs" / "campuses" / "vitap.yaml"

REAL_DESTINATION_NAMES = {
    "AB-1", "AB-2", "CB", "Food Street", "MH-1", "MH-2", "MH-2 Food Store",
    "MH-3", "MH-6", "MH-7", "LH-1",
}


def test_vitap_config_loads_cleanly() -> None:
    config = load_campus_config_file(VITAP_CONFIG_PATH)

    assert config.campus_id == "vitap"
    assert len(config.destinations) == 11
    assert len(config.gates) == 1
    assert len(config.parking_lots) == 1
    assert len(config.roads) == 12  # gate->lot + lot->each of 11 destinations


def test_destinations_are_real_everything_else_is_sample() -> None:
    config = load_campus_config_file(VITAP_CONFIG_PATH)

    assert {d.name for d in config.destinations} == REAL_DESTINATION_NAMES
    assert all(d.provenance == "EXTERNAL_MAP_REFERENCE" for d in config.destinations)
    assert all(g.provenance == "SAMPLE" for g in config.gates)
    assert all(p.provenance == "SAMPLE" for p in config.parking_lots)
    assert all(r.provenance == "SAMPLE" for r in config.roads)


def test_every_destination_connects_to_the_placeholder_lot() -> None:
    config = load_campus_config_file(VITAP_CONFIG_PATH)

    lot_id = config.parking_lots[0].parking_lot_id
    connected_destination_ids = {
        r.end_node for r in config.roads if r.start_node == lot_id
    }
    destination_ids = {d.destination_id for d in config.destinations}
    assert connected_destination_ids == destination_ids


async def test_vitap_config_upserts_and_round_trips_through_the_database(db_session: AsyncSession) -> None:
    config = load_campus_config_file(VITAP_CONFIG_PATH)

    version = await upsert_campus_config(db_session, config)

    assert version == 1
    destination_count = (
        await db_session.execute(select(func.count()).select_from(Destination))
    ).scalar_one()
    gate_count = (await db_session.execute(select(func.count()).select_from(Gate))).scalar_one()
    lot_count = (await db_session.execute(select(func.count()).select_from(ParkingLot))).scalar_one()
    road_count = (await db_session.execute(select(func.count()).select_from(Road))).scalar_one()

    assert destination_count == 11
    assert gate_count == 1
    assert lot_count == 1
    assert road_count == 12

    stored_destinations = (await db_session.execute(select(Destination))).scalars().all()
    assert all(d.provenance == "EXTERNAL_MAP_REFERENCE" for d in stored_destinations)
    stored_roads = (await db_session.execute(select(Road))).scalars().all()
    assert all(r.provenance == "SAMPLE" for r in stored_roads)
    # Every road's geometry is a straight line (3 collinear-ish points, not a
    # walked curve) — a real walked road would have many more points.
    assert all(len(r.geometry) == 3 for r in stored_roads)
