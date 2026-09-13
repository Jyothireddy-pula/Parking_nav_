from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.models.campus import Campus
from app.models.destination import Destination
from app.models.gate import Gate
from app.models.parking_lot import ParkingLot
from app.models.road import Road
from app.models.route_edge import RouteEdge

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


async def _count(session: AsyncSession, model) -> int:
    result = await session.execute(select(func.count()).select_from(model))
    return result.scalar_one()


async def test_upsert_creates_campus_and_bumps_version(db_session: AsyncSession) -> None:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)

    version = await upsert_campus_config(db_session, config)

    assert version == 1
    campus = await db_session.get(Campus, "sample")
    assert campus is not None
    assert campus.active_configuration_version == 1
    assert await _count(db_session, Gate) == 2
    assert await _count(db_session, ParkingLot) == 1
    assert await _count(db_session, Destination) == 2
    assert await _count(db_session, Road) == 4
    # 4 roads, 3 of which are walkable+driveable (2 edges each) and 1 walkable-only (1 edge),
    # each direction doubled.
    assert await _count(db_session, RouteEdge) > 0


async def test_reload_is_idempotent(db_session: AsyncSession) -> None:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)

    await upsert_campus_config(db_session, config)
    gate_count_after_first_load = await _count(db_session, Gate)
    edge_count_after_first_load = await _count(db_session, RouteEdge)

    second_version = await upsert_campus_config(db_session, config)

    assert second_version == 2
    assert await _count(db_session, Gate) == gate_count_after_first_load
    assert await _count(db_session, RouteEdge) == edge_count_after_first_load

    campus = await db_session.get(Campus, "sample")
    assert campus.active_configuration_version == 2
    gate = await db_session.get(Gate, "sample-gate-main")
    assert gate.configuration_version == 2


async def test_removing_an_entity_and_reloading_prunes_it(db_session: AsyncSession) -> None:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)

    trimmed = config.model_copy(
        update={
            "destinations": [d for d in config.destinations if d.destination_id != "sample-dest-library"],
            "roads": [r for r in config.roads if r.road_id != "sample-road-4" and r.road_id != "sample-road-3"],
        }
    )

    await upsert_campus_config(db_session, trimmed)

    assert await db_session.get(Destination, "sample-dest-library") is None
    assert await db_session.get(Road, "sample-road-3") is None
    assert await db_session.get(Road, "sample-road-4") is None
