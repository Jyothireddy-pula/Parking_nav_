from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.schema import CampusConfigFile
from app.config_loader.upsert import upsert_campus_config
from app.db import get_db
from app.main import app
from tests.test_navigation import NAV_TEST_CONFIG


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    config = CampusConfigFile.model_validate(NAV_TEST_CONFIG)
    await upsert_campus_config(db_session, config)

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.pop(get_db, None)


async def test_get_route(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/campuses/navtest/navigate/route",
        params={"start": "nav-gate", "end": "nav-lot", "mode": "walk"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["distance_m"] == 10.0
    assert len(body["geometry"]) == 3


async def test_get_route_no_feasible_route_returns_409_with_error_contract(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/campuses/navtest/navigate/route",
        params={"start": "nav-lot", "end": "nav-dest-drive-only", "mode": "walk"},
    )

    assert response.status_code == 409
    assert set(response.json()) == {"error", "detail", "status_code"}


async def test_get_route_unknown_node_returns_404(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/campuses/navtest/navigate/route",
        params={"start": "does-not-exist", "end": "nav-lot", "mode": "walk"},
    )

    assert response.status_code == 404


async def test_get_nearest_parking(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/campuses/navtest/navigate/nearest-parking",
        params={"start": "nav-gate", "mode": "drive", "require_available": "false"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target"]["node_id"] == "nav-lot"


async def test_get_nearest_destination(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/campuses/navtest/navigate/nearest-destination",
        params={"start": "nav-lot", "mode": "walk"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["target"]["node_type"] == "destination"


async def test_search(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/campuses/navtest/navigate/search",
        params={"query": "waypoint"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["destination_id"] == "nav-dest-via"


async def test_navigate_unknown_campus_returns_404(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/campuses/does-not-exist/navigate/route",
        params={"start": "a", "end": "b", "mode": "walk"},
    )

    assert response.status_code == 404
