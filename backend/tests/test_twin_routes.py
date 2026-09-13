from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.db import get_db
from app.main import app
from app.services.digital_twin import DigitalTwinService

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)
    await DigitalTwinService().init_campus(db_session, config.campus_id)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_db, None)


async def test_get_state(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/sample/state")

    assert response.status_code == 200
    body = response.json()
    assert body["campus_id"] == "sample"
    assert body["active_scenario"] == "normal"
    assert len(body["parking"]) == 1
    assert body["parking"][0]["freshness"] == "UNKNOWN"


async def test_get_parking_state(client: AsyncClient, db_session: AsyncSession) -> None:
    await DigitalTwinService().update_parking(
        db_session, "sample", "sample-lot-1", occupied=12, source="manual", provenance="REAL"
    )

    response = await client.get("/api/v1/campuses/sample/state/parking/sample-lot-1")

    assert response.status_code == 200
    body = response.json()
    assert body["occupied"] == 12
    assert body["freshness"] == "FRESH"


async def test_get_parking_state_unknown_lot_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/sample/state/parking/does-not-exist")

    assert response.status_code == 404
    assert set(response.json()) == {"error", "detail", "status_code"}


async def test_get_state_unknown_campus_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/does-not-exist/state")

    assert response.status_code == 404


async def test_get_state_history(client: AsyncClient, db_session: AsyncSession) -> None:
    service = DigitalTwinService()
    await service.update_parking(
        db_session, "sample", "sample-lot-1", occupied=3, source="manual", provenance="REAL"
    )
    await service.snapshot(db_session, "sample")

    response = await client.get("/api/v1/campuses/sample/state/history")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["campus_id"] == "sample"
