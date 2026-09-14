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
from app.services.optimization import PROFILES, GateNotFoundError, OptimizationEngine
from app.services.prediction import FileModelRegistry, PredictionService
from app.services.risk import RiskEngine

CAMPUS_ID = "opttest"
GATE_ID = "opt-gate"
LOT_A, LOT_B, LOT_C = "opt-lot-a", "opt-lot-b", "opt-lot-c"
CAPACITY = 100


def _lot(lot_id: str) -> dict:
    return {
        "parking_lot_id": lot_id,
        "name": lot_id,
        "status": "open",
        "total_capacity": CAPACITY,
        "usable_capacity": CAPACITY,
        "reserved_capacity": 0,
        "restricted_capacity": 0,
        "temporarily_unavailable_capacity": 0,
        "provenance": "SAMPLE",
    }


def _road(road_id: str, start: str, end: str, length: float, travel_time: float) -> dict:
    return {
        "road_id": road_id,
        "name": road_id,
        "start_node": start,
        "end_node": end,
        "length": length,
        "expected_travel_time": travel_time,
        "is_walkable": True,
        "is_driveable": True,
        "status": "open",
        "provenance": "SAMPLE",
        "geometry": [{"lat": 0.0, "lng": 0.0}, {"lat": 0.0005, "lng": 0.0005}, {"lat": 0.001, "lng": 0.001}],
    }


OPT_TEST_CONFIG: dict = {
    "campus_id": CAMPUS_ID,
    "name": "Optimization Test Campus",
    "timezone": "Asia/Kolkata",
    "gates": [
        {
            "gate_id": GATE_ID,
            "name": "Opt Gate",
            "coordinates": {"lat": 0.0, "lng": 0.0},
            "capacity": 10,
            "status": "open",
            "provenance": "SAMPLE",
        },
    ],
    "parking_lots": [_lot(LOT_A), _lot(LOT_B), _lot(LOT_C)],
    "destinations": [],
    "events": [],
    "roads": [
        _road("opt-road-a", GATE_ID, LOT_A, 50.0, 30.0),
        _road("opt-road-b", GATE_ID, LOT_B, 500.0, 300.0),
        _road("opt-road-c", GATE_ID, LOT_C, 200.0, 120.0),
    ],
}


class FakeFixedModel:
    def __init__(self, point: float, lower: float, upper: float) -> None:
        self.point, self.lower, self.upper = point, lower, upper

    def predict(self, df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
        return np.full(len(df), self.point)

    def predict_interval(
        self, df: pd.DataFrame, feature_cols: list[str], lower_q: float = 0.1, upper_q: float = 0.9
    ) -> tuple[np.ndarray, np.ndarray]:
        return np.full(len(df), self.lower), np.full(len(df), self.upper)


@pytest.fixture
async def opt_campus(db_session: AsyncSession) -> str:
    config = CampusConfigFile.model_validate(OPT_TEST_CONFIG)
    await upsert_campus_config(db_session, config)
    await DigitalTwinService().init_campus(db_session, CAMPUS_ID)
    return CAMPUS_ID


def _feature_cols() -> list[str]:
    ts = pd.date_range("2024-01-01", periods=60, freq="5min", tz="UTC")
    raw = pd.DataFrame({"lot_id": LOT_A, "timestamp": ts, "occupied": [50.0] * 60, "capacity": CAPACITY})
    featured = build_features(bucket_to_5min(raw), horizon_minutes=15)
    return feature_columns(featured)


def _register_fixed_model(base_dir: Path, lot_id: str, point: float, lower: float, upper: float) -> None:
    cols = _feature_cols()
    model = FakeFixedModel(point, lower, upper)
    directory = base_dir / CAMPUS_ID / lot_id / "15"
    directory.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, directory / "model.joblib")
    payload = {
        "evaluation_id": f"eval_{lot_id}",
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
    (directory / "evaluation.json").write_text(json.dumps(payload), encoding="utf-8")


def _engine(tmp_path: Path) -> OptimizationEngine:
    prediction = PredictionService(FileModelRegistry(tmp_path))
    return OptimizationEngine(prediction, RiskEngine(prediction))


async def _set_occupied(session: AsyncSession, lot_id: str, occupied: int | None, status: str = "open") -> None:
    if occupied is None:
        return
    await DigitalTwinService().update_parking(
        session, CAMPUS_ID, lot_id, occupied=occupied, source="manual", provenance="SYNTHETIC", status=status
    )
    if status != "open":
        return
    # Module 9's PredictionService needs real observation history to build
    # live features -- without this, every prediction silently falls back
    # to current-state, never exercising the registered (fake) model.
    ingestion = IngestionService()
    now = datetime.now(timezone.utc)
    for i in range(8, -1, -1):
        await ingestion.ingest_one(
            session, CAMPUS_ID,
            ObservationIn(
                timestamp=now - timedelta(minutes=5 * i), parking_lot_id=lot_id, occupied_spaces=occupied,
                source_label="SYNTHETIC", collection_method="manual_count",
            ),
        )


# --- hand-computed toy scenario with a known correct pick ---


async def test_hand_computed_toy_scenario_picks_the_correct_lot(
    db_session: AsyncSession, opt_campus: str, tmp_path: Path
) -> None:
    # Two feasible candidates, no gate queue (waiting_time term is 0 for
    # both -> contributes nothing to ranking, by design -- see module
    # docstring). Lot A: near (travel_time_s=30), predicted point=8/upper=10.
    # Lot B: far (travel_time_s=300), predicted point=90/upper=95.
    # avg predicted pct (of POINT estimates, used for utilization_imbalance)
    # = (8+90)/2 = 49.
    _register_fixed_model(tmp_path, LOT_A, point=8.0, lower=6.0, upper=10.0)
    _register_fixed_model(tmp_path, LOT_B, point=90.0, lower=85.0, upper=95.0)
    await _set_occupied(db_session, LOT_A, 8)
    await _set_occupied(db_session, LOT_B, 90)
    await _set_occupied(db_session, LOT_C, 100, status="closed")  # not a candidate at all

    result = await _engine(tmp_path).recommend(db_session, CAMPUS_ID, GATE_ID, profile="P2_BALANCED")

    assert result.feasible is True
    by_lot = {c.lot_id: c for c in result.all_candidates if c.feasible}
    a, b = by_lot[LOT_A], by_lot[LOT_B]
    assert a.prediction_source == "model"
    assert b.prediction_source == "model"

    # Hand-computed normalized terms (max-of-feasible-candidates normalization):
    # waiting_time: both 0 -> norm 0 for both.
    # queue_cost raw = overflow_risk.score = upper_pct/90: A=10/90=0.1111, B=95/90=1.0556 (max=1.0556)
    #   A_norm = 0.1111/1.0556 = 0.10526, B_norm = 1.0
    # search_travel raw = travel_time_s: A=30, B=300 (max=300) -> A_norm=0.1, B_norm=1.0
    # utilization_imbalance raw = |pct-avg|/100, avg=49: A=|8-49|/100=0.41; B=|90-49|/100=0.41
    #   max=0.41 -> A_norm=1.0, B_norm=1.0
    # overflow_penalty raw = max(0,pct-100)/100: both 0 -> norm 0 for both (max forced to 1.0)
    w = PROFILES["P2_BALANCED"]
    expected_a = w["w1"] * 0 + w["w2"] * 0.10526 + w["w3"] * 0.1 + w["w4"] * 1.0 + w["w5"] * 0
    expected_b = w["w1"] * 0 + w["w2"] * 1.0 + w["w3"] * 1.0 + w["w4"] * 1.0 + w["w5"] * 0

    assert a.objective_j == pytest.approx(expected_a, abs=1e-3)
    assert b.objective_j == pytest.approx(expected_b, abs=1e-3)
    assert expected_a < expected_b
    assert result.best.lot_id == LOT_A


# --- infeasible-but-cheaper never returned ---


async def test_infeasible_but_cheaper_candidate_is_never_returned(
    db_session: AsyncSession, opt_campus: str, tmp_path: Path
) -> None:
    # Lot A is nearest (cheapest travel) but full. Lot C is farther but
    # has room -- must be recommended instead, never A.
    _register_fixed_model(tmp_path, LOT_A, point=50.0, lower=45.0, upper=55.0)
    _register_fixed_model(tmp_path, LOT_C, point=50.0, lower=45.0, upper=55.0)
    await _set_occupied(db_session, LOT_A, 100)  # full
    await _set_occupied(db_session, LOT_B, 100, status="closed")
    await _set_occupied(db_session, LOT_C, 50)

    result = await _engine(tmp_path).recommend(db_session, CAMPUS_ID, GATE_ID)

    assert result.feasible is True
    assert result.best.lot_id == LOT_C
    assert all(c.lot_id != LOT_A for c in result.alternatives)
    infeasible = {c.lot_id: c for c in result.all_candidates if not c.feasible}
    assert infeasible[LOT_A].infeasible_reason == "lot is full"
    assert "closed" in infeasible[LOT_B].infeasible_reason


async def test_baseline_strategies_also_never_return_an_infeasible_candidate(
    db_session: AsyncSession, opt_campus: str, tmp_path: Path
) -> None:
    _register_fixed_model(tmp_path, LOT_C, point=50.0, lower=45.0, upper=55.0)
    await _set_occupied(db_session, LOT_A, 100)
    await _set_occupied(db_session, LOT_B, 100, status="closed")
    await _set_occupied(db_session, LOT_C, 50)

    engine = _engine(tmp_path)
    for strategy in ("first_available", "nearest_available", "prediction_only"):
        result = await engine.recommend_baseline(db_session, CAMPUS_ID, GATE_ID, strategy)
        assert result.best.lot_id == LOT_C, strategy


# --- overflow case handled, never an exception ---


async def test_no_feasible_lot_returns_documented_overflow_response(
    db_session: AsyncSession, opt_campus: str, tmp_path: Path
) -> None:
    await _set_occupied(db_session, LOT_A, 100)
    await _set_occupied(db_session, LOT_B, 100)
    await _set_occupied(db_session, LOT_C, 100)

    result = await _engine(tmp_path).recommend(db_session, CAMPUS_ID, GATE_ID)

    assert result.feasible is False
    assert result.best is None
    assert result.reason is not None
    assert len(result.all_candidates) == 3
    assert all(not c.feasible for c in result.all_candidates)


async def test_unknown_gate_raises(db_session: AsyncSession, opt_campus: str, tmp_path: Path) -> None:
    with pytest.raises(GateNotFoundError):
        await _engine(tmp_path).recommend(db_session, CAMPUS_ID, "does-not-exist")


async def test_unknown_campus_raises(db_session: AsyncSession, tmp_path: Path) -> None:
    with pytest.raises(CampusNotFoundError):
        await _engine(tmp_path).recommend(db_session, "does-not-exist", GATE_ID)


async def test_unknown_profile_raises(db_session: AsyncSession, opt_campus: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        await _engine(tmp_path).recommend(db_session, CAMPUS_ID, GATE_ID, profile="NOT_A_PROFILE")


# --- the three profiles disagree on a designed scenario ---


async def test_the_three_profiles_disagree(db_session: AsyncSession, opt_campus: str, tmp_path: Path) -> None:
    # Lot A: very near, predicted near-overflow (good for P1, bad for P3).
    # Lot B: very far, predicted nearly empty (bad for P1, good for P3).
    _register_fixed_model(tmp_path, LOT_A, point=88.0, lower=85.0, upper=92.0)
    _register_fixed_model(tmp_path, LOT_B, point=5.0, lower=3.0, upper=8.0)
    await _set_occupied(db_session, LOT_A, 88)
    await _set_occupied(db_session, LOT_B, 5)
    await _set_occupied(db_session, LOT_C, 100, status="closed")

    engine = _engine(tmp_path)
    picks = {
        profile: (await engine.recommend(db_session, CAMPUS_ID, GATE_ID, profile=profile)).best.lot_id
        for profile in PROFILES
    }

    assert picks["P1_MIN_WAITING"] == LOT_A
    assert picks["P3_MAX_UTILIZATION"] == LOT_B
    assert len(set(picks.values())) >= 2  # the profiles genuinely disagree


# --- compare(): all four strategies together ---


async def test_compare_runs_all_four_strategies(db_session: AsyncSession, opt_campus: str, tmp_path: Path) -> None:
    _register_fixed_model(tmp_path, LOT_A, point=50.0, lower=45.0, upper=55.0)
    _register_fixed_model(tmp_path, LOT_B, point=50.0, lower=45.0, upper=55.0)
    await _set_occupied(db_session, LOT_A, 50)
    await _set_occupied(db_session, LOT_B, 50)
    await _set_occupied(db_session, LOT_C, 100, status="closed")

    results = await _engine(tmp_path).compare(db_session, CAMPUS_ID, GATE_ID)

    assert set(results) == {"first_available", "nearest_available", "prediction_only", "optimizer"}
    assert all(r.feasible for r in results.values())


# --- time limit exceeded -> nearest-available fallback ---


async def test_time_limit_exceeded_falls_back_to_nearest_available(
    db_session: AsyncSession, opt_campus: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.optimization as optimization_module

    monkeypatch.setattr(optimization_module, "TIME_LIMIT_SECONDS", 0.0)
    _register_fixed_model(tmp_path, LOT_A, point=50.0, lower=45.0, upper=55.0)
    _register_fixed_model(tmp_path, LOT_B, point=10.0, lower=5.0, upper=15.0)
    await _set_occupied(db_session, LOT_A, 50)
    await _set_occupied(db_session, LOT_B, 10)
    await _set_occupied(db_session, LOT_C, 100, status="closed")

    result = await _engine(tmp_path).recommend(db_session, CAMPUS_ID, GATE_ID)

    assert result.feasible is True
    assert result.used_fallback == "time_limit_exceeded"
    assert result.reason is not None
    # Nearest by travel time -- LOT_A (30s) is nearer than LOT_B (300s),
    # regardless of predicted occupancy, since the fallback is pure nearest-available.
    assert result.best.lot_id == LOT_A


# --- determinism ---


async def test_recommend_is_deterministic_for_identical_inputs(
    db_session: AsyncSession, opt_campus: str, tmp_path: Path
) -> None:
    _register_fixed_model(tmp_path, LOT_A, point=50.0, lower=45.0, upper=55.0)
    _register_fixed_model(tmp_path, LOT_B, point=60.0, lower=55.0, upper=65.0)
    await _set_occupied(db_session, LOT_A, 50)
    await _set_occupied(db_session, LOT_B, 60)
    await _set_occupied(db_session, LOT_C, 100, status="closed")

    engine = _engine(tmp_path)
    result_a = await engine.recommend(db_session, CAMPUS_ID, GATE_ID)
    result_b = await engine.recommend(db_session, CAMPUS_ID, GATE_ID)

    assert result_a.best.lot_id == result_b.best.lot_id
    assert result_a.best.objective_j == pytest.approx(result_b.best.objective_j, abs=1e-9)
