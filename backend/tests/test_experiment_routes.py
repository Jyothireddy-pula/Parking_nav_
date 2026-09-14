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

SCENARIO_BODY = {
    "scenario_id": "route-test-scenario",
    "campus_id": "sample",
    "name": "Route test scenario",
    "duration_minutes": 10,
    "seed": 0,
    "arrival_rate_profile": [
        {"gate_id": "sample-gate-main", "start_minute": 0, "end_minute": 10, "vehicles_per_minute": 0.3}
    ],
}


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


async def test_create_experiment(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/experiments",
        json={"scenario": SCENARIO_BODY, "strategies": ["first_available", "nearest_available"], "seeds": [1, 2]},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["experiment_id"].startswith("exp_")
    assert body["seeds"] == [1, 2]
    assert set(body["aggregated"]) == {"first_available", "nearest_available"}
    assert len(body["raw_results"]) == 4  # 2 strategies x 2 seeds


async def test_create_experiment_unknown_strategy_returns_422(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/experiments",
        json={"scenario": SCENARIO_BODY, "strategies": ["not-a-strategy"], "seeds": [1]},
    )

    assert response.status_code == 422


async def test_create_experiment_unknown_campus_returns_404(client: AsyncClient) -> None:
    body = {**SCENARIO_BODY, "campus_id": "does-not-exist"}
    response = await client.post(
        "/api/v1/experiments",
        json={"scenario": body, "strategies": ["first_available"], "seeds": [1]},
    )

    assert response.status_code == 404


async def test_get_experiment(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/v1/experiments",
        json={"scenario": SCENARIO_BODY, "strategies": ["first_available"], "seeds": [1]},
    )
    experiment_id = create_response.json()["experiment_id"]

    response = await client.get(f"/api/v1/experiments/{experiment_id}")

    assert response.status_code == 200
    assert response.json()["experiment_id"] == experiment_id


async def test_get_experiment_not_found_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/experiments/does-not-exist")

    assert response.status_code == 404
    assert set(response.json()) == {"error", "detail", "status_code"}


async def test_compare_experiment(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/v1/experiments",
        json={"scenario": SCENARIO_BODY, "strategies": ["first_available", "nearest_available"], "seeds": [1, 2]},
    )
    experiment_id = create_response.json()["experiment_id"]

    response = await client.get(f"/api/v1/experiments/{experiment_id}/compare")

    assert response.status_code == 200
    body = response.json()
    assert "vehicles_total" in body["by_metric"]
    assert set(body["by_metric"]["vehicles_total"]) == {"first_available", "nearest_available"}


async def test_export_experiment_returns_csv(client: AsyncClient) -> None:
    create_response = await client.post(
        "/api/v1/experiments",
        json={"scenario": SCENARIO_BODY, "strategies": ["first_available"], "seeds": [1, 2]},
    )
    experiment_id = create_response.json()["experiment_id"]

    response = await client.get(f"/api/v1/experiments/{experiment_id}/export")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert lines[0].startswith("strategy,seed,run_id,")
    assert len(lines) == 1 + 2  # header + 2 raw results
