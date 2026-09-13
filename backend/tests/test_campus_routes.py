from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.db import get_db
from app.main import app

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_db, None)


async def test_list_gates(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/sample/gates")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {gate["gate_id"] for gate in body} == {"sample-gate-main", "sample-gate-north"}


async def test_list_roads(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/sample/roads")

    assert response.status_code == 200
    assert len(response.json()) == 4


async def test_list_parking_lots(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/sample/parking-lots")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["parking_lot_id"] == "sample-lot-1"
    assert body[0]["total_capacity"] == 100


async def test_list_destinations(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/sample/destinations")

    assert response.status_code == 200
    assert len(response.json()) == 2


async def test_list_events(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/sample/events")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["event_id"] == "sample-event-orientation"


async def test_unknown_campus_returns_404_error_contract(client: AsyncClient) -> None:
    response = await client.get("/api/v1/campuses/does-not-exist/gates")

    assert response.status_code == 404
    assert set(response.json()) == {"error", "detail", "status_code"}
