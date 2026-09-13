from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.schemas.ingestion import ObservationIn
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import DigitalTwinService
from app.services.ingestion import IngestionService

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


@pytest.fixture
def service() -> IngestionService:
    return IngestionService()


@pytest.fixture
async def sample_campus(db_session: AsyncSession) -> str:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)
    await DigitalTwinService().init_campus(db_session, config.campus_id)
    return config.campus_id


def _parking_observation(**overrides) -> ObservationIn:
    fields = {
        "timestamp": datetime.now(timezone.utc),
        "parking_lot_id": "sample-lot-1",
        "occupied_spaces": 10,
        "source_label": "REAL",
        "collection_method": "manual_count",
    }
    fields.update(overrides)
    return ObservationIn(**fields)


def _gate_observation(**overrides) -> ObservationIn:
    fields = {
        "timestamp": datetime.now(timezone.utc),
        "gate_id": "sample-gate-main",
        "vehicle_count": 5,
        "source_label": "REAL",
        "collection_method": "manual_count",
    }
    fields.update(overrides)
    return ObservationIn(**fields)


async def test_valid_parking_observation_is_accepted(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(db_session, sample_campus, _parking_observation())

    assert rejected is None
    assert accepted is not None
    assert accepted.parking_lot_id == "sample-lot-1"
    assert accepted.occupied_spaces == 10
    assert accepted.source_label == "REAL"


async def test_valid_gate_observation_is_accepted_and_reaches_the_twin(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(db_session, sample_campus, _gate_observation())

    assert rejected is None
    assert accepted is not None

    gate_state = await DigitalTwinService().get_state(db_session, sample_campus)
    gate = next(g for g in gate_state["gates"] if g["gate_id"] == "sample-gate-main")
    assert gate["queue"] == 5
    assert gate["freshness"] == "FRESH"


async def test_unknown_campus_raises(service: IngestionService, db_session: AsyncSession) -> None:
    with pytest.raises(CampusNotFoundError):
        await service.ingest_one(db_session, "does-not-exist", _parking_observation())


async def test_over_capacity_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _parking_observation(occupied_spaces=99999)
    )

    assert accepted is None
    assert rejected is not None
    assert "exceeds" in rejected.reason


async def test_negative_count_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _parking_observation(occupied_spaces=-1)
    )

    assert accepted is None
    assert "must be >= 0" in rejected.reason


async def test_unknown_gate_id_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _gate_observation(gate_id="does-not-exist")
    )

    assert accepted is None
    assert "unknown gate_id" in rejected.reason


async def test_unknown_parking_lot_id_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _parking_observation(parking_lot_id="does-not-exist")
    )

    assert accepted is None
    assert "unknown parking_lot_id" in rejected.reason


async def test_impossible_future_timestamp_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    future = datetime.now(timezone.utc) + timedelta(days=1)
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _parking_observation(timestamp=future)
    )

    assert accepted is None
    assert "in the future" in rejected.reason


async def test_impossibly_old_timestamp_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    ancient = datetime(1999, 1, 1, tzinfo=timezone.utc)
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _parking_observation(timestamp=ancient)
    )

    assert accepted is None
    assert "implausibly old" in rejected.reason


async def test_duplicate_observation_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    observation = _parking_observation()
    accepted_1, rejected_1 = await service.ingest_one(db_session, sample_campus, observation)
    assert rejected_1 is None

    accepted_2, rejected_2 = await service.ingest_one(db_session, sample_campus, observation)

    assert accepted_2 is None
    assert "duplicate" in rejected_2.reason
    assert accepted_1 is not None


async def test_ambiguous_row_with_no_target_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    observation = ObservationIn(
        timestamp=datetime.now(timezone.utc), source_label="REAL", collection_method="manual_count"
    )

    accepted, rejected = await service.ingest_one(db_session, sample_campus, observation)

    assert accepted is None
    assert "exactly one of" in rejected.reason


async def test_ambiguous_row_with_two_targets_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    observation = ObservationIn(
        timestamp=datetime.now(timezone.utc),
        gate_id="sample-gate-main",
        vehicle_count=1,
        parking_lot_id="sample-lot-1",
        occupied_spaces=1,
        source_label="REAL",
        collection_method="manual_count",
    )

    accepted, rejected = await service.ingest_one(db_session, sample_campus, observation)

    assert accepted is None
    assert "exactly one of" in rejected.reason


async def test_invalid_source_label_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _parking_observation(source_label="MADE_UP")
    )

    assert accepted is None
    assert "source_label" in rejected.reason


async def test_invalid_collection_method_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    accepted, rejected = await service.ingest_one(
        db_session, sample_campus, _parking_observation(collection_method="guessed")
    )

    assert accepted is None
    assert "collection_method" in rejected.reason


async def test_event_intensity_out_of_range_is_rejected(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    observation = ObservationIn(
        timestamp=datetime.now(timezone.utc),
        event_type="orientation_day",
        event_intensity=9,
        source_label="REAL",
        collection_method="manual_count",
    )

    accepted, rejected = await service.ingest_one(db_session, sample_campus, observation)

    assert accepted is None
    assert "event_intensity" in rejected.reason


async def test_valid_event_observation_is_accepted(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    observation = ObservationIn(
        timestamp=datetime.now(timezone.utc),
        event_type="orientation_day",
        event_intensity=3,
        source_label="REAL",
        collection_method="manual_count",
    )

    accepted, rejected = await service.ingest_one(db_session, sample_campus, observation)

    assert rejected is None
    assert accepted.event_type == "orientation_day"


async def test_rejected_row_is_still_recorded_in_raw(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    from sqlalchemy import func, select

    from app.models.ingestion import ObservationRaw

    await service.ingest_one(db_session, sample_campus, _parking_observation(occupied_spaces=-5))

    count = (
        await db_session.execute(
            select(func.count()).select_from(ObservationRaw).where(ObservationRaw.campus_id == sample_campus)
        )
    ).scalar_one()
    assert count == 1


async def test_provenance_is_preserved_end_to_end(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    observation = _parking_observation(source_label="SAMPLE", collection_method="simulator")

    accepted, _rejected = await service.ingest_one(db_session, sample_campus, observation)

    assert accepted.source_label == "SAMPLE"
    assert accepted.collection_method == "simulator"

    twin_state = await DigitalTwinService().get_parking_state(db_session, sample_campus, "sample-lot-1")
    assert twin_state["provenance"] == "SAMPLE"
    assert twin_state["source"] == "simulation"


async def test_mixed_validity_unified_csv_batch(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    csv_text = (
        "timestamp,gate_id,vehicle_count,parking_lot_id,occupied_spaces,event_type,event_intensity,"
        "notes,source_label,collection_method\n"
        f"{now},,,sample-lot-1,20,,,,REAL,manual_count\n"
        f"{now},,,sample-lot-1,99999,,,,REAL,manual_count\n"
        f"{now},sample-gate-main,3,,,,,,REAL,manual_count\n"
        f"{now},,,does-not-exist,5,,,,REAL,manual_count\n"
    )

    batch = await service.ingest_bulk_csv(db_session, sample_campus, csv_text, csv_format="unified")

    assert batch.total_rows == 4
    assert batch.accepted_rows == 2
    assert batch.rejected_rows == 2

    rejected = await service.list_rejected(db_session, sample_campus, batch_id=batch.batch_id)
    reasons = {row.reason for row in rejected}
    assert any("exceeds" in reason for reason in reasons)
    assert any("unknown parking_lot_id" in reason for reason in reasons)


async def test_module2_parking_csv_format_is_ingestible(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    csv_text = (
        "collection_session,parking_lot_id,capacity,occupied_spaces,timestamp,"
        "contributing_observers,observation_count,source_label\n"
        f"s1,sample-lot-1,100,42,{now},Alice;Bob,2,REAL\n"
    )

    batch = await service.ingest_bulk_csv(db_session, sample_campus, csv_text, csv_format="module2_parking")

    assert batch.accepted_rows == 1
    accepted = await service.list_observations(db_session, sample_campus, parking_lot_id="sample-lot-1")
    assert accepted[0].occupied_spaces == 42
    assert accepted[0].collection_method == "manual_count"
    assert "Alice" in accepted[0].notes


async def test_cv_batch_ingests_multiple_observations(
    db_session: AsyncSession, service: IngestionService, sample_campus: str
) -> None:
    observations = [
        _parking_observation(occupied_spaces=15, collection_method="cv_auto"),
        _gate_observation(vehicle_count=2, collection_method="cv_auto"),
    ]

    batch = await service.ingest_cv_batch(db_session, sample_campus, observations)

    assert batch.accepted_rows == 2
    assert batch.submitted_via == "cv_batch"
