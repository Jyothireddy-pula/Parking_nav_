from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.schema import CampusConfigFile
from app.config_loader.upsert import upsert_campus_config
from app.db import get_db
from app.main import app
from app.services.digital_twin import DigitalTwinService
from tests.test_risk import CAMPUS_ID, LOT_ID, RISK_TEST_CONFIG


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    config = CampusConfigFile.model_validate(RISK_TEST_CONFIG)
    await upsert_campus_config(db_session, config)
    await DigitalTwinService().init_campus(db_session, CAMPUS_ID)
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=50, source="manual", provenance="SYNTHETIC"
    )

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_db, None)


async def test_get_risk_returns_full_numbers_not_just_a_label(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/risk/{LOT_ID}", params={"campus_id": CAMPUS_ID})

    assert response.status_code == 200
    body = response.json()
    assert body["lot_id"] == LOT_ID
    for key in ("overflow_risk", "gate_queue_risk", "road_congestion_risk", "search_risk", "combined_network_risk"):
        component = body[key]
        assert set(component) == {"available", "level", "raw_value", "threshold", "score", "reason"}
    assert "fired" in body["proactive_trigger"]


async def test_get_risk_unknown_lot_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/risk/does-not-exist", params={"campus_id": CAMPUS_ID})
    assert response.status_code == 404


async def test_get_risk_unknown_campus_returns_404(client: AsyncClient) -> None:
    response = await client.get(f"/api/v1/risk/{LOT_ID}", params={"campus_id": "does-not-exist"})
    assert response.status_code == 404
    assert set(response.json()) == {"error", "detail", "status_code"}
