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


async def test_post_single_observation(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/campuses/sample/observations",
        json={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parking_lot_id": "sample-lot-1",
            "occupied_spaces": 10,
            "source_label": "REAL",
            "collection_method": "manual_count",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["parking_lot_id"] == "sample-lot-1"
    assert body["occupied_spaces"] == 10


async def test_post_single_observation_rejected_returns_422_with_error_contract(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/campuses/sample/observations",
        json={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parking_lot_id": "sample-lot-1",
            "occupied_spaces": -5,
            "source_label": "REAL",
            "collection_method": "manual_count",
        },
    )

    assert response.status_code == 422
    assert set(response.json()) == {"error", "detail", "status_code"}


async def test_post_observation_unknown_campus_returns_404(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/campuses/does-not-exist/observations",
        json={
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parking_lot_id": "sample-lot-1",
            "occupied_spaces": 10,
            "source_label": "REAL",
            "collection_method": "manual_count",
        },
    )

    assert response.status_code == 404


async def test_bulk_csv_upload(client: AsyncClient) -> None:
    now = datetime.now(timezone.utc).isoformat()
    csv_text = (
        "timestamp,gate_id,vehicle_count,parking_lot_id,occupied_spaces,event_type,event_intensity,"
        "notes,source_label,collection_method\n"
        f"{now},,,sample-lot-1,20,,,,REAL,manual_count\n"
        f"{now},,,sample-lot-1,99999,,,,REAL,manual_count\n"
    )

    response = await client.post(
        "/api/v1/campuses/sample/observations/bulk-csv",
        files={"file": ("observations.csv", csv_text, "text/csv")},
        data={"csv_format": "unified"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_rows"] == 2
    assert body["accepted_rows"] == 1
    assert body["rejected_rows"] == 1
    assert len(body["rejected"]) == 1
    assert "exceeds" in body["rejected"][0]["reason"]


async def test_cv_batch(client: AsyncClient) -> None:
    now = datetime.now(timezone.utc).isoformat()
    response = await client.post(
        "/api/v1/campuses/sample/observations/cv-batch",
        json=[
            {
                "timestamp": now,
                "parking_lot_id": "sample-lot-1",
                "occupied_spaces": 12,
                "source_label": "REAL",
                "collection_method": "cv_auto",
            }
        ],
    )

    assert response.status_code == 200
    body = response.json()
    assert body["accepted_rows"] == 1
    assert body["submitted_via"] == "cv_batch"


async def test_get_observations(client: AsyncClient) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await client.post(
        "/api/v1/campuses/sample/observations",
        json={
            "timestamp": now,
            "parking_lot_id": "sample-lot-1",
            "occupied_spaces": 7,
            "source_label": "REAL",
            "collection_method": "manual_count",
        },
    )

    response = await client.get("/api/v1/campuses/sample/observations")

    assert response.status_code == 200
    assert len(response.json()) == 1


async def test_quality_report(client: AsyncClient) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await client.post(
        "/api/v1/campuses/sample/observations",
        json={
            "timestamp": now,
            "parking_lot_id": "sample-lot-1",
            "occupied_spaces": 7,
            "source_label": "REAL",
            "collection_method": "manual_count",
        },
    )
    await client.post(
        "/api/v1/campuses/sample/observations",
        json={
            "timestamp": now,
            "parking_lot_id": "sample-lot-1",
            "occupied_spaces": -1,
            "source_label": "REAL",
            "collection_method": "manual_count",
        },
    )
    await client.post(
        "/api/v1/campuses/sample/observations",
        json={
            "timestamp": now,
            "gate_id": "sample-gate-main",
            "source_label": "REAL",
            "collection_method": "manual_count",
        },
    )

    response = await client.get("/api/v1/campuses/sample/observations/quality-report")

    assert response.status_code == 200
    body = response.json()
    assert body["raw_total"] == 3
    assert body["accepted_total"] == 1
    assert body["rejected_total"] == 2
    assert body["missing_fields"]["rejected_due_to_missing_required_field"] == 1
    assert body["missing_fields"]["accepted_missing_notes"] == 1
    assert body["coverage"]["parking_lots_total"] == 1
    assert body["coverage"]["parking_lots_with_observations"] == 1
