import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import pandas as pd
import pytest
from prediction.features import bucket_to_5min, build_features, feature_columns
from prediction.models.historical_average import HistoricalAverageModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.loader import load_campus_config_file
from app.config_loader.upsert import upsert_campus_config
from app.models.prediction import StoredPrediction
from app.schemas.ingestion import ObservationIn
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import DigitalTwinService
from app.services.ingestion import IngestionService
from app.services.prediction import (
    DATA_STALE,
    HIGH,
    INTELLIGENCE_UNAVAILABLE,
    FileModelRegistry,
    PredictionService,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CAMPUS_PATH = REPO_ROOT / "configs" / "campuses" / "sample.yaml"
LOT_ID = "sample-lot-1"
CAMPUS_ID = "sample"


@pytest.fixture
async def sample_campus(db_session: AsyncSession) -> str:
    config = load_campus_config_file(SAMPLE_CAMPUS_PATH)
    await upsert_campus_config(db_session, config)
    await DigitalTwinService().init_campus(db_session, config.campus_id)
    return config.campus_id


def _train_toy_historical_average_model() -> tuple[HistoricalAverageModel, list[str], dict]:
    rng_ts = pd.date_range("2024-01-01", periods=400, freq="5min", tz="UTC")
    occupied = [30 + (i % 12) for i in range(400)]
    raw = pd.DataFrame({"lot_id": LOT_ID, "timestamp": rng_ts, "occupied": occupied, "capacity": 90})
    bucketed = bucket_to_5min(raw)
    featured = build_features(bucketed, horizon_minutes=15)
    cols = feature_columns(featured)

    model = HistoricalAverageModel()
    model.fit(featured, cols)

    predictions = model.predict(featured, cols)
    mae = float((predictions - featured["target"]).abs().mean())
    evaluation_payload = {
        "evaluation_id": "eval_toy_1",
        "dataset_label": "toy_synthetic",
        "model_name": "historical_average",
        "model_version": "hist_avg-v1",
        "dataset_version": "toy-v1",
        "preprocessing_version": "prep-v1",
        "feature_version": "feat-v1",
        "mae": mae,
        "rmse": mae,
        "sample_size": len(featured),
        "evaluation_start": featured["asof_ts"].min().isoformat(),
        "evaluation_end": featured["asof_ts"].max().isoformat(),
        "trained_at": datetime.now(timezone.utc).isoformat(),
    }
    return model, cols, evaluation_payload


def _register_toy_model(base_dir: Path, campus_id: str, lot_id: str, horizon: int) -> None:
    model, cols, evaluation_payload = _train_toy_historical_average_model()
    directory = base_dir / campus_id / lot_id / str(horizon)
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, directory / "model.joblib")
    (directory / "evaluation.json").write_text(
        json.dumps({**evaluation_payload, "feature_cols": cols}), encoding="utf-8"
    )


async def _seed_recent_observations(session: AsyncSession, minutes_ago_start: int = 40) -> None:
    ingestion = IngestionService()
    now = datetime.now(timezone.utc)
    for i in range(minutes_ago_start // 5, -1, -1):
        ts = now - timedelta(minutes=5 * i)
        await ingestion.ingest_one(
            session,
            CAMPUS_ID,
            ObservationIn(
                timestamp=ts,
                parking_lot_id=LOT_ID,
                occupied_spaces=40 + i,
                source_label="SYNTHETIC",
                collection_method="manual_count",
            ),
        )


# --- INTELLIGENCE_UNAVAILABLE ---


async def test_no_registered_model_returns_intelligence_unavailable(
    db_session: AsyncSession, sample_campus: str, tmp_path: Path
) -> None:
    service = PredictionService(FileModelRegistry(tmp_path))

    result = await service.predict(db_session, CAMPUS_ID, LOT_ID, 15)

    assert result.confidence == INTELLIGENCE_UNAVAILABLE
    assert result.point_estimate is None
    assert result.lower_bound is None
    assert result.upper_bound is None


async def test_registered_model_but_no_observation_history_returns_intelligence_unavailable(
    db_session: AsyncSession, sample_campus: str, tmp_path: Path
) -> None:
    _register_toy_model(tmp_path, CAMPUS_ID, LOT_ID, 15)
    service = PredictionService(FileModelRegistry(tmp_path))

    result = await service.predict(db_session, CAMPUS_ID, LOT_ID, 15)

    assert result.confidence == INTELLIGENCE_UNAVAILABLE
    assert result.point_estimate is None


async def test_unknown_campus_raises(db_session: AsyncSession, tmp_path: Path) -> None:
    service = PredictionService(FileModelRegistry(tmp_path))
    with pytest.raises(CampusNotFoundError):
        await service.predict(db_session, "does-not-exist", LOT_ID, 15)


# --- happy path ---


async def test_predict_with_enough_history_returns_a_bounded_estimate_and_updates_twin(
    db_session: AsyncSession, sample_campus: str, tmp_path: Path
) -> None:
    _register_toy_model(tmp_path, CAMPUS_ID, LOT_ID, 15)
    await _seed_recent_observations(db_session)
    service = PredictionService(FileModelRegistry(tmp_path))

    result = await service.predict(db_session, CAMPUS_ID, LOT_ID, 15)

    assert result.point_estimate is not None
    assert result.lower_bound is not None
    assert result.upper_bound is not None
    assert result.lower_bound <= result.point_estimate <= result.upper_bound
    assert result.confidence in (HIGH, "MODERATE", "LOW")
    assert result.model_version == "hist_avg-v1"

    twin = DigitalTwinService()
    state = await twin.get_parking_state(db_session, CAMPUS_ID, LOT_ID)
    assert state["predicted_occupancy"] == pytest.approx(result.point_estimate)

    stored = await db_session.get(StoredPrediction, result.prediction_id)
    assert stored is not None
    assert stored.confidence == result.confidence
    assert stored.evaluation_id == "eval_toy_1"


async def test_predict_with_stale_history_returns_data_stale(
    db_session: AsyncSession, sample_campus: str, tmp_path: Path
) -> None:
    _register_toy_model(tmp_path, CAMPUS_ID, LOT_ID, 15)
    ingestion = IngestionService()
    old_now = datetime.now(timezone.utc) - timedelta(hours=2)
    for i in range(8, -1, -1):
        ts = old_now - timedelta(minutes=5 * i)
        await ingestion.ingest_one(
            db_session,
            CAMPUS_ID,
            ObservationIn(
                timestamp=ts,
                parking_lot_id=LOT_ID,
                occupied_spaces=40 + i,
                source_label="SYNTHETIC",
                collection_method="manual_count",
            ),
        )
    service = PredictionService(FileModelRegistry(tmp_path))

    result = await service.predict(db_session, CAMPUS_ID, LOT_ID, 15)

    assert result.confidence == DATA_STALE
    assert result.point_estimate is not None  # still computed, just caveated


async def test_predict_horizon_target_timestamp_matches_horizon(
    db_session: AsyncSession, sample_campus: str, tmp_path: Path
) -> None:
    _register_toy_model(tmp_path, CAMPUS_ID, LOT_ID, 15)
    await _seed_recent_observations(db_session)
    service = PredictionService(FileModelRegistry(tmp_path))

    result = await service.predict(db_session, CAMPUS_ID, LOT_ID, 15)

    delta = result.target_timestamp - result.prediction_timestamp
    assert delta == timedelta(minutes=15)
