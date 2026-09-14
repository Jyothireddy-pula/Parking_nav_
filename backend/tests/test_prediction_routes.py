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


async def test_predict_with_no_trained_model_returns_intelligence_unavailable(client: AsyncClient) -> None:
    # The shipped FileModelRegistry points at a directory with no trained
    # artifacts in this test environment -- the honest, expected state.
    response = await client.post(
        "/api/v1/predict",
        json={"campus_id": "sample", "parking_lot_id": "sample-lot-1", "horizon_minutes": 15},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["confidence"] == "INTELLIGENCE_UNAVAILABLE"
    assert body["point_estimate"] is None
    assert body["lower_bound"] is None
    assert body["upper_bound"] is None


async def test_predict_invalid_horizon_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/predict",
        json={"campus_id": "sample", "parking_lot_id": "sample-lot-1", "horizon_minutes": 45},
    )

    assert response.status_code == 422


async def test_predict_unknown_campus_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/predict",
        json={"campus_id": "does-not-exist", "parking_lot_id": "sample-lot-1", "horizon_minutes": 15},
    )

    assert response.status_code == 404
    assert set(response.json()) == {"error", "detail", "status_code"}
