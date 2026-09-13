from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.db import get_db
from app.main import app
from app.schemas.ingestion import ObservationIn
from app.services.ingestion import IngestionService

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)

    ingestion = IngestionService()
    ts = datetime(2026, 1, 12, 9, 0, tzinfo=timezone.utc)
    await ingestion.ingest_one(
        db_session,
        "sample",
        ObservationIn(
            timestamp=ts,
            parking_lot_id="sample-lot-1",
            occupied_spaces=40,
            source_label="REAL",
            collection_method="manual_count",
        ),
    )
    await ingestion.ingest_cv_batch(
        db_session,
        "sample",
        [
            ObservationIn(
                timestamp=ts,
                parking_lot_id="sample-lot-1",
                occupied_spaces=42,
                source_label="REAL",
                collection_method="cv_auto",
            )
        ],
    )

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_db, None)


async def test_create_and_list_calibration_report(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/v1/campuses/sample/parking-lots/sample-lot-1/cv-calibration-reports"
    )

    assert create_response.status_code == 201
    body = create_response.json()
    assert body["sample_size"] == 1
    assert body["mae"] == 2.0
    assert body["recommended_collection_method"] == "cv_auto"

    list_response = await client.get("/api/v1/campuses/sample/cv-calibration-reports")
    assert list_response.status_code == 200
    assert len(list_response.json()) == 1


@pytest_asyncio.fixture
async def bare_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_db, None)


async def test_calibration_report_no_paired_data_returns_422(bare_client: AsyncClient) -> None:
    response = await bare_client.post(
        "/api/v1/campuses/sample/parking-lots/sample-lot-1/cv-calibration-reports"
    )

    assert response.status_code == 422


async def test_calibration_report_unknown_lot_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/campuses/sample/parking-lots/does-not-exist/cv-calibration-reports"
    )

    assert response.status_code == 404
