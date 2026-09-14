import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from prediction.features import bucket_to_5min, build_features, feature_columns
from sqlalchemy.ext.asyncio import AsyncSession

from app.config_loader.schema import CampusConfigFile
from app.config_loader.upsert import upsert_campus_config
from app.schemas.ingestion import ObservationIn
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import DigitalTwinService
from app.services.ingestion import IngestionService
from app.services.prediction import FileModelRegistry, PredictionService
from app.services.risk import (
    CRITICAL,
    HIGH,
    LOW,
    MEDIUM,
    OVERFLOW_THRESHOLD_PCT,
    UNKNOWN,
    LotNotFoundError,
    RiskEngine,
    _band_ratio,
)

CAMPUS_ID = "risktest"
LOT_ID = "risk-lot"
GATE_ID = "risk-gate"
CAPACITY = 100  # clean percentages: occupied count == occupancy_pct

RISK_TEST_CONFIG: dict = {
    "campus_id": CAMPUS_ID,
    "name": "Risk Test Campus",
    "timezone": "Asia/Kolkata",
    "gates": [
        {
            "gate_id": GATE_ID,
            "name": "Risk Gate",
            "coordinates": {"lat": 0.0, "lng": 0.0},
            "capacity": 10,
            "status": "open",
            "provenance": "SAMPLE",
        },
    ],
    "parking_lots": [
        {
            "parking_lot_id": LOT_ID,
            "name": "Risk Lot",
            "status": "open",
            "total_capacity": CAPACITY,
            "usable_capacity": CAPACITY,
            "reserved_capacity": 0,
            "restricted_capacity": 0,
            "temporarily_unavailable_capacity": 0,
            "provenance": "SAMPLE",
        },
        {
            "parking_lot_id": "risk-lot-2",
            "name": "Risk Lot 2",
            "status": "open",
            "total_capacity": CAPACITY,
            "usable_capacity": CAPACITY,
            "reserved_capacity": 0,
            "restricted_capacity": 0,
            "temporarily_unavailable_capacity": 0,
            "provenance": "SAMPLE",
        },
    ],
    "destinations": [],
    "events": [],
    "roads": [],
}


class FakeFixedModel:
    """A prediction model that always returns fixed values, regardless of
    input -- lets tests pin exactly what Module 9 handed to Module 10
    without depending on a real model's training dynamics."""

    def __init__(self, point: float, lower: float, upper: float) -> None:
        self.point, self.lower, self.upper = point, lower, upper

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        return np.full(len(df), self.point)

    def predict_interval(
        self, df: pd.DataFrame, feature_cols: list[str], lower_q: float = 0.1, upper_q: float = 0.9
    ) -> tuple[np.ndarray, np.ndarray]:
        return np.full(len(df), self.lower), np.full(len(df), self.upper)


@pytest.fixture
async def risk_campus(db_session: AsyncSession) -> str:
    config = CampusConfigFile.model_validate(RISK_TEST_CONFIG)
    await upsert_campus_config(db_session, config)
    await DigitalTwinService().init_campus(db_session, CAMPUS_ID)
    return CAMPUS_ID


def _feature_cols() -> list[str]:
    ts = pd.date_range("2024-01-01", periods=60, freq="5min", tz="UTC")
    raw = pd.DataFrame({"lot_id": LOT_ID, "timestamp": ts, "occupied": [50.0] * 60, "capacity": CAPACITY})
    featured = build_features(bucket_to_5min(raw), horizon_minutes=15)
    return feature_columns(featured)


def _register_fixed_model(base_dir: Path, point: float, lower: float, upper: float, horizon: int = 15) -> None:
    cols = _feature_cols()
    model = FakeFixedModel(point, lower, upper)
    directory = base_dir / CAMPUS_ID / LOT_ID / str(horizon)
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, directory / "model.joblib")
    evaluation_payload = {
        "evaluation_id": "eval_risk_1",
        "dataset_label": "toy",
        "model_name": "fake",
        "model_version": "fake-v1",
        "dataset_version": "toy-v1",
        "preprocessing_version": "prep-v1",
        "feature_version": "feat-v1",
        "mae": 5.0,
        "rmse": 5.0,
        "sample_size": 60,
        "evaluation_start": datetime.now(timezone.utc).isoformat(),
        "evaluation_end": datetime.now(timezone.utc).isoformat(),
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "feature_cols": cols,
    }
    (directory / "evaluation.json").write_text(json.dumps(evaluation_payload), encoding="utf-8")


async def _seed_recent_observations(session: AsyncSession, lot_id: str = LOT_ID, occupied: int = 50) -> None:
    ingestion = IngestionService()
    now = datetime.now(timezone.utc)
    for i in range(8, -1, -1):
        await ingestion.ingest_one(
            session,
            CAMPUS_ID,
            ObservationIn(
                timestamp=now - timedelta(minutes=5 * i),
                parking_lot_id=lot_id,
                occupied_spaces=occupied,
                source_label="SYNTHETIC",
                collection_method="manual_count",
            ),
        )


def _engine(tmp_path: Path) -> RiskEngine:
    return RiskEngine(PredictionService(FileModelRegistry(tmp_path)))


# --- _band_ratio threshold boundaries ---


def test_band_ratio_boundaries() -> None:
    assert _band_ratio(0.0) == LOW
    assert _band_ratio(0.79) == LOW
    assert _band_ratio(0.8) == MEDIUM
    assert _band_ratio(0.99) == MEDIUM
    assert _band_ratio(1.0) == HIGH
    assert _band_ratio(1.14) == HIGH
    assert _band_ratio(1.15) == CRITICAL
    assert _band_ratio(5.0) == CRITICAL


# --- normal vs high-demand ---


async def test_normal_demand_scores_low_overflow_risk(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    _register_fixed_model(tmp_path, point=40.0, lower=35.0, upper=45.0)
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=40, source="manual", provenance="SYNTHETIC"
    )
    await _seed_recent_observations(db_session, occupied=40)

    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert result.overflow_risk.available is True
    assert result.overflow_risk.raw_value == pytest.approx(45.0)
    assert result.overflow_risk.level == LOW
    assert result.proactive_trigger.fired is False


async def test_high_demand_scores_high_or_critical_overflow_risk(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    _register_fixed_model(tmp_path, point=90.0, lower=85.0, upper=98.0)
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=85, source="manual", provenance="SYNTHETIC"
    )
    await _seed_recent_observations(db_session, occupied=85)

    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert result.overflow_risk.level in (HIGH, CRITICAL)
    assert result.proactive_trigger.fired is True


# --- is_proactive_trigger: fires on predicted, not current ---


async def test_proactive_trigger_fires_from_prediction_while_current_is_low(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    # current 72%, 15-min prediction 94% +/- 3% (upper bound 97%), threshold 90% -> fires now
    _register_fixed_model(tmp_path, point=94.0, lower=91.0, upper=97.0)
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=72, source="manual", provenance="SYNTHETIC"
    )
    await _seed_recent_observations(db_session, occupied=72)

    trigger = await _engine(tmp_path).is_proactive_trigger(db_session, CAMPUS_ID, LOT_ID)

    assert trigger.current_occupancy_pct == pytest.approx(72.0)
    assert trigger.predicted_upper_bound_pct == pytest.approx(97.0)
    assert trigger.threshold_pct == OVERFLOW_THRESHOLD_PCT
    assert trigger.fired is True


async def test_proactive_trigger_does_not_fire_when_current_and_prediction_both_low(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    _register_fixed_model(tmp_path, point=40.0, lower=35.0, upper=45.0)
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=40, source="manual", provenance="SYNTHETIC"
    )
    await _seed_recent_observations(db_session, occupied=40)

    trigger = await _engine(tmp_path).is_proactive_trigger(db_session, CAMPUS_ID, LOT_ID)

    assert trigger.fired is False


# --- wider uncertainty raises risk level ---


async def test_wider_prediction_uncertainty_raises_overflow_risk_level(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=80, source="manual", provenance="SYNTHETIC"
    )
    await _seed_recent_observations(db_session, occupied=80)

    narrow_dir = tmp_path / "narrow"
    _register_fixed_model(narrow_dir, point=88.0, lower=86.0, upper=92.0)
    narrow_result = await _engine(narrow_dir).assess(db_session, CAMPUS_ID, LOT_ID)

    wide_dir = tmp_path / "wide"
    _register_fixed_model(wide_dir, point=88.0, lower=70.0, upper=115.0)
    wide_result = await _engine(wide_dir).assess(db_session, CAMPUS_ID, LOT_ID)

    # Same point estimate, wider interval -> higher upper bound -> higher
    # (never lower) overflow risk score and level.
    assert wide_result.overflow_risk.score > narrow_result.overflow_risk.score
    levels_order = [LOW, MEDIUM, HIGH, CRITICAL]
    assert levels_order.index(wide_result.overflow_risk.level) >= levels_order.index(narrow_result.overflow_risk.level)
    assert wide_result.overflow_risk.level == CRITICAL


# --- closed-facility edge case ---


async def test_closed_lot_reports_low_overflow_risk_and_no_proactive_trigger(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=99, source="manual", provenance="SYNTHETIC", status="closed"
    )

    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert result.lot_status == "closed"
    assert result.overflow_risk.available is True
    assert result.overflow_risk.level == LOW
    assert "closed" in result.overflow_risk.reason
    assert result.proactive_trigger.fired is False
    assert result.prediction is None  # never called Module 9 for a closed lot


# --- stale / unavailable prediction is flagged, never silently scored ---


async def test_no_registered_model_flags_overflow_risk_as_unknown(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=50, source="manual", provenance="SYNTHETIC"
    )
    await _seed_recent_observations(db_session, occupied=50)

    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert result.overflow_risk.available is False
    assert result.overflow_risk.level == UNKNOWN
    assert result.overflow_risk.score is None
    assert "INTELLIGENCE_UNAVAILABLE" in result.overflow_risk.reason
    assert result.proactive_trigger.fired is False
    assert "INTELLIGENCE_UNAVAILABLE" in result.proactive_trigger.reason


async def test_stale_underlying_data_flags_overflow_risk_as_unknown_not_a_default(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    _register_fixed_model(tmp_path, point=50.0, lower=45.0, upper=55.0)
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=50, source="manual", provenance="SYNTHETIC"
    )
    # Observations exist, but they're all 2 hours old -- STALE per Module 3's freshness rule.
    ingestion = IngestionService()
    old_now = datetime.now(timezone.utc) - timedelta(hours=2)
    for i in range(8, -1, -1):
        await ingestion.ingest_one(
            db_session, CAMPUS_ID,
            ObservationIn(
                timestamp=old_now - timedelta(minutes=5 * i), parking_lot_id=LOT_ID, occupied_spaces=50,
                source_label="SYNTHETIC", collection_method="manual_count",
            ),
        )

    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert result.prediction is not None
    assert result.prediction.confidence == "DATA_STALE"
    assert result.overflow_risk.available is False
    assert result.overflow_risk.level == UNKNOWN
    assert "DATA_STALE" in result.overflow_risk.reason


# --- unknown lot / campus ---


async def test_unknown_lot_raises(db_session: AsyncSession, risk_campus: str, tmp_path: Path) -> None:
    with pytest.raises(LotNotFoundError):
        await _engine(tmp_path).assess(db_session, CAMPUS_ID, "does-not-exist")


async def test_unknown_campus_raises(db_session: AsyncSession, tmp_path: Path) -> None:
    with pytest.raises(CampusNotFoundError):
        await _engine(tmp_path).assess(db_session, "does-not-exist", LOT_ID)


# --- gate queue / road congestion / search risk ---


async def test_gate_queue_risk_unknown_with_no_observations(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=10, source="manual", provenance="SYNTHETIC"
    )
    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)
    assert result.gate_queue_risk.available is False
    assert result.gate_queue_risk.level == UNKNOWN


async def test_gate_queue_risk_scored_once_a_queue_is_observed(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=10, source="manual", provenance="SYNTHETIC"
    )
    await DigitalTwinService().update_gate(
        db_session, CAMPUS_ID, GATE_ID, queue=20, source="manual", provenance="SYNTHETIC"
    )

    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert result.gate_queue_risk.available is True
    assert result.gate_queue_risk.raw_value == 20.0
    assert result.gate_queue_risk.level in (HIGH, CRITICAL)


async def test_road_congestion_risk_is_unknown_because_nothing_populates_it_yet(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=10, source="manual", provenance="SYNTHETIC"
    )
    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)
    assert result.road_congestion_risk.available is False
    assert result.road_congestion_risk.level == UNKNOWN


async def test_search_risk_lower_when_alternative_lots_have_room(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    twin = DigitalTwinService()
    await twin.update_parking(db_session, CAMPUS_ID, LOT_ID, occupied=90, source="manual", provenance="SYNTHETIC")

    await twin.update_parking(
        db_session, CAMPUS_ID, "risk-lot-2", occupied=100, source="manual", provenance="SYNTHETIC"
    )
    no_alt_result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    await twin.update_parking(
        db_session, CAMPUS_ID, "risk-lot-2", occupied=10, source="manual", provenance="SYNTHETIC"
    )
    with_alt_result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert with_alt_result.search_risk.raw_value < no_alt_result.search_risk.raw_value


# --- combined network risk ---


async def test_combined_network_risk_excludes_and_reports_unavailable_dimensions(
    db_session: AsyncSession, risk_campus: str, tmp_path: Path
) -> None:
    await DigitalTwinService().update_parking(
        db_session, CAMPUS_ID, LOT_ID, occupied=50, source="manual", provenance="SYNTHETIC"
    )
    # No model registered -> overflow UNKNOWN; no gate queue/road data -> both UNKNOWN.
    # Only search_risk (current-state based) can be scored.
    result = await _engine(tmp_path).assess(db_session, CAMPUS_ID, LOT_ID)

    assert set(result.excluded_from_combined) == {"overflow", "gate_queue", "road_congestion"}
    assert result.combined_network_risk.available is True
    assert result.combined_network_risk.reason is not None
    assert "overflow" in result.combined_network_risk.reason
