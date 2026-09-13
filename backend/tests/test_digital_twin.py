from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import (
    CapacityExceededError,
    DigitalTwinService,
    EntityNotFoundError,
    InvalidObservationError,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


@pytest.fixture
def service() -> DigitalTwinService:
    return DigitalTwinService()


@pytest.fixture
async def sample_campus(db_session: AsyncSession) -> str:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)
    return config.campus_id


async def test_init_seeds_structural_rows_from_config(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    state = await service.get_state(db_session, sample_campus)

    assert state["campus_id"] == sample_campus
    assert state["active_scenario"] == "normal"
    assert len(state["parking"]) == 1
    lot = state["parking"][0]
    assert lot["parking_lot_id"] == "sample-lot-1"
    assert lot["total_capacity"] == 100
    assert lot["occupied"] is None
    assert lot["available"] is None
    assert lot["freshness"] == "UNKNOWN"
    assert len(state["gates"]) == 2


async def test_sequential_updates_are_reflected_correctly(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=10, source="manual", provenance="REAL"
    )
    state = await service.get_parking_state(db_session, sample_campus, "sample-lot-1")
    assert state["occupied"] == 10
    assert state["available"] == state["usable_capacity"] - 10

    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=25, source="cv_auto", provenance="REAL"
    )
    state = await service.get_parking_state(db_session, sample_campus, "sample-lot-1")
    assert state["occupied"] == 25
    assert state["source"] == "cv_auto"
    assert state["occupancy_pct"] == pytest.approx(100 * 25 / state["usable_capacity"], abs=0.1)


async def test_over_capacity_update_is_rejected_and_state_unchanged(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)
    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=10, source="manual", provenance="REAL"
    )

    with pytest.raises(CapacityExceededError):
        await service.update_parking(
            db_session, sample_campus, "sample-lot-1", occupied=999, source="manual", provenance="REAL"
        )

    state = await service.get_parking_state(db_session, sample_campus, "sample-lot-1")
    assert state["occupied"] == 10  # unchanged, not clamped


async def test_negative_occupied_is_rejected(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    with pytest.raises(InvalidObservationError):
        await service.update_parking(
            db_session, sample_campus, "sample-lot-1", occupied=-1, source="manual", provenance="REAL"
        )


async def test_unknown_source_is_rejected(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    with pytest.raises(InvalidObservationError):
        await service.update_parking(
            db_session, sample_campus, "sample-lot-1", occupied=1, source="guessed", provenance="REAL"
        )


async def test_update_unknown_lot_raises_entity_not_found(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    with pytest.raises(EntityNotFoundError):
        await service.update_parking(
            db_session, sample_campus, "does-not-exist", occupied=1, source="manual", provenance="REAL"
        )


async def test_unknown_campus_raises_campus_not_found(db_session: AsyncSession, service: DigitalTwinService) -> None:
    with pytest.raises(CampusNotFoundError):
        await service.init_campus(db_session, "does-not-exist")


async def test_stale_observation_is_flagged_not_shown_as_current(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    old_timestamp = datetime.now(timezone.utc) - timedelta(hours=2)
    await service.update_parking(
        db_session,
        sample_campus,
        "sample-lot-1",
        occupied=5,
        source="manual",
        provenance="REAL",
        observation_timestamp=old_timestamp,
    )

    state = await service.get_parking_state(db_session, sample_campus, "sample-lot-1")

    assert state["freshness"] == "STALE"
    assert state["occupied"] == 5  # the value is still returned, just not labeled current


async def test_fresh_observation_is_flagged_fresh(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=5, source="manual", provenance="REAL"
    )

    state = await service.get_parking_state(db_session, sample_campus, "sample-lot-1")
    assert state["freshness"] == "FRESH"


async def test_reset_clears_observations_but_keeps_structure(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)
    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=5, source="manual", provenance="REAL"
    )
    await service.update_vehicle(
        db_session, sample_campus, "vehicle-1", state="searching", source="manual", provenance="REAL"
    )

    await service.reset(db_session, sample_campus)

    state = await service.get_state(db_session, sample_campus)
    lot = next(p for p in state["parking"] if p["parking_lot_id"] == "sample-lot-1")
    assert lot["occupied"] is None
    assert lot["freshness"] == "UNKNOWN"
    assert state["vehicles"] == []


async def test_snapshot_captures_current_state(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)
    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=8, source="manual", provenance="REAL"
    )

    snapshot = await service.snapshot(db_session, sample_campus)

    assert snapshot.campus_id == sample_campus
    lot_payload = next(p for p in snapshot.payload["parking"] if p["parking_lot_id"] == "sample-lot-1")
    assert lot_payload["occupied"] == 8

    history = await service.get_history(db_session, sample_campus)
    assert len(history) == 1
    assert history[0].snapshot_id == snapshot.snapshot_id


async def test_multiple_snapshots_are_kept_in_history_order(
    db_session: AsyncSession, service: DigitalTwinService, sample_campus: str
) -> None:
    await service.init_campus(db_session, sample_campus)

    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=1, source="manual", provenance="REAL"
    )
    first = await service.snapshot(db_session, sample_campus)

    await service.update_parking(
        db_session, sample_campus, "sample-lot-1", occupied=2, source="manual", provenance="REAL"
    )
    second = await service.snapshot(db_session, sample_campus)

    history = await service.get_history(db_session, sample_campus)
    assert len(history) == 2
    assert history[0].snapshot_id == second.snapshot_id  # newest first
    assert history[1].snapshot_id == first.snapshot_id
