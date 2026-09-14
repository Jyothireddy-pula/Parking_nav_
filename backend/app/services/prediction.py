"""Module 9 — serves stored/trained prediction models at request time.
Never decides anything (no allocation, no routing) -- it only forecasts a
future occupancy value, with an explicit confidence label, and writes that
forecast into Module 3's digital twin. If no trained model exists for a
(campus, lot, horizon), or there isn't enough recent real data to build the
model's input features, this returns INTELLIGENCE_UNAVAILABLE rather than
guessing -- never a fabricated number.

Imports `ml/prediction`'s feature-building code lazily (inside
_build_live_features), which requires the ml package (parkingnavx-ml) to
be pip-installed in the same environment as the backend -- true for this
repo's shared .venv, same assumption simulation/run.py and
prediction/train_real.py already make about the monorepo layout.
"""

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import joblib
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingestion import Observation
from app.models.prediction import PredictionEvaluation, StoredPrediction
from app.repositories.campus_config import CampusConfigRepository
from app.repositories.twin import TwinRepository
from app.services.campus_config import CampusNotFoundError
from app.services.digital_twin import DigitalTwinService, EntityNotFoundError
from app.services.freshness import STALE, UNKNOWN, compute_freshness

logger = logging.getLogger(__name__)

HIGH_MAE_FRACTION = 0.10  # mae / usable_capacity below this -> HIGH
MODERATE_MAE_FRACTION = 0.25  # below this -> MODERATE, else LOW
# Documented starting thresholds (same pattern as Module 5's CV promotion
# rule), not validated against real VIT-AP error yet -- see docs/PREDICTION.md.

# Buckets of recent observation history fetched to build "as-of-now"
# features. 3 hours comfortably covers the 6-bucket (30-min) rolling
# window plus the longest lag (occupancy_lag_6) with room for gaps.
LIVE_HISTORY_LOOKBACK = timedelta(hours=3)

HIGH = "HIGH"
MODERATE = "MODERATE"
LOW = "LOW"
DATA_STALE = "DATA_STALE"
INTELLIGENCE_UNAVAILABLE = "INTELLIGENCE_UNAVAILABLE"


@dataclass
class RegisteredModel:
    model: object
    feature_cols: list[str]
    evaluation: PredictionEvaluation


class ModelRegistry(Protocol):
    def get(self, campus_id: str, lot_id: str, horizon_minutes: int) -> RegisteredModel | None: ...


class FileModelRegistry:
    """Loads a joblib-pickled model + evaluation.json from
    {base_dir}/{campus_id}/{lot_id}/{horizon_minutes}/. Written by a
    training run (ml/prediction/train_external.py, prediction/train_real.py)
    -- this class only ever reads what training already produced and
    evaluated, never trains anything itself."""

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._cache: dict[tuple, RegisteredModel | None] = {}

    def get(self, campus_id: str, lot_id: str, horizon_minutes: int) -> RegisteredModel | None:
        key = (campus_id, lot_id, horizon_minutes)
        if key in self._cache:
            return self._cache[key]

        directory = self._base_dir / campus_id / lot_id / str(horizon_minutes)
        model_path = directory / "model.joblib"
        eval_path = directory / "evaluation.json"
        if not model_path.exists() or not eval_path.exists():
            self._cache[key] = None
            return None

        model = joblib.load(model_path)
        payload = json.loads(eval_path.read_text(encoding="utf-8"))
        evaluation = PredictionEvaluation(
            evaluation_id=payload["evaluation_id"],
            dataset_label=payload["dataset_label"],
            model_name=payload["model_name"],
            horizon_minutes=horizon_minutes,
            model_version=payload["model_version"],
            dataset_version=payload["dataset_version"],
            preprocessing_version=payload["preprocessing_version"],
            feature_version=payload["feature_version"],
            mae=payload["mae"],
            rmse=payload["rmse"],
            r2=payload.get("r2"),
            wape=payload.get("wape"),
            mape=payload.get("mape"),
            sample_size=payload["sample_size"],
            evaluation_start=datetime.fromisoformat(payload["evaluation_start"]),
            evaluation_end=datetime.fromisoformat(payload["evaluation_end"]),
            trained_at=datetime.fromisoformat(payload["trained_at"]),
        )
        registered = RegisteredModel(model=model, feature_cols=payload["feature_cols"], evaluation=evaluation)
        self._cache[key] = registered
        return registered


@dataclass
class PredictionResult:
    prediction_id: str
    campus_id: str
    parking_lot_id: str
    horizon_minutes: int
    prediction_timestamp: datetime
    target_timestamp: datetime
    point_estimate: float | None
    lower_bound: float | None
    upper_bound: float | None
    model_version: str | None
    confidence: str


class PredictionService:
    def __init__(
        self,
        registry: ModelRegistry,
        config_repository: CampusConfigRepository | None = None,
        twin_service: DigitalTwinService | None = None,
    ) -> None:
        self._registry = registry
        self._config = config_repository or CampusConfigRepository()
        self._twin = twin_service or DigitalTwinService()
        self._twin_repository = TwinRepository()

    async def predict(
        self, session: AsyncSession, campus_id: str, parking_lot_id: str, horizon_minutes: int
    ) -> PredictionResult:
        campus = await self._config.get_campus(session, campus_id)
        if campus is None:
            raise CampusNotFoundError(campus_id)

        now = datetime.now(timezone.utc)
        target_ts = now + timedelta(minutes=horizon_minutes)
        prediction_id = f"pred_{uuid.uuid4().hex}"

        registered = self._registry.get(campus_id, parking_lot_id, horizon_minutes)
        if registered is None:
            return await self._store(
                session, prediction_id, campus_id, parking_lot_id, horizon_minutes, now, target_ts,
                None, None, None, None, INTELLIGENCE_UNAVAILABLE, None, {},
            )

        features_row, latest_observation_ts = await self._build_live_features(
            session, campus_id, parking_lot_id, horizon_minutes, registered.feature_cols
        )
        if features_row is None:
            return await self._store(
                session, prediction_id, campus_id, parking_lot_id, horizon_minutes, now, target_ts,
                None, None, None, registered.evaluation.model_version, INTELLIGENCE_UNAVAILABLE,
                registered.evaluation.evaluation_id, {},
            )

        import pandas as pd  # local import: only needed on this path

        df = pd.DataFrame([features_row])
        point = float(registered.model.predict(df, registered.feature_cols)[0])
        lower_arr, upper_arr = registered.model.predict_interval(df, registered.feature_cols)
        lower, upper = float(lower_arr[0]), float(upper_arr[0])

        freshness = compute_freshness(latest_observation_ts, "parking", now)
        capacity = await self._twin_capacity(session, campus_id, parking_lot_id)
        confidence = self._confidence(registered.evaluation, capacity, freshness)

        result = await self._store(
            session, prediction_id, campus_id, parking_lot_id, horizon_minutes, now, target_ts,
            point, lower, upper, registered.evaluation.model_version, confidence,
            registered.evaluation.evaluation_id, features_row,
        )

        try:
            await self._twin.set_predicted_occupancy(session, campus_id, parking_lot_id, point)
        except EntityNotFoundError:
            logger.warning(
                "prediction twin sync skipped: unknown lot", extra={"campus_id": campus_id, "lot_id": parking_lot_id}
            )
        return result

    @staticmethod
    def _confidence(evaluation: PredictionEvaluation, capacity: float | None, freshness: str) -> str:
        """Explicit, documented starting policy (same shape as Module 5's
        CV promotion threshold) -- not yet validated against real VIT-AP
        error, since no real evaluation exists to validate it against.
        Stale/unknown underlying data always wins over the model's own
        historical accuracy: a great model fed old data is not a confident
        prediction."""

        if freshness in (STALE, UNKNOWN):
            return DATA_STALE
        if not capacity or capacity <= 0:
            return MODERATE
        mae_fraction = evaluation.mae / capacity
        if mae_fraction < HIGH_MAE_FRACTION:
            return HIGH
        if mae_fraction < MODERATE_MAE_FRACTION:
            return MODERATE
        return LOW

    async def _build_live_features(
        self, session: AsyncSession, campus_id: str, lot_id: str, horizon_minutes: int, feature_cols: list[str]
    ) -> tuple[dict | None, datetime | None]:
        from prediction.datasets.real_observations import from_observation_rows
        from prediction.features import bucket_to_5min, build_features

        twin_row = await self._twin_capacity(session, campus_id, lot_id)
        if twin_row is None:
            return None, None

        since = datetime.now(timezone.utc) - LIVE_HISTORY_LOOKBACK
        result = await session.execute(
            select(Observation)
            .where(
                Observation.campus_id == campus_id,
                Observation.parking_lot_id == lot_id,
                Observation.occupied_spaces.is_not(None),
                Observation.timestamp >= since,
            )
            .order_by(Observation.timestamp.asc())
        )
        rows = [
            {
                "parking_lot_id": lot_id,
                "timestamp": obs.timestamp,
                "occupied_spaces": obs.occupied_spaces,
                "capacity": twin_row,
            }
            for obs in result.scalars().all()
        ]
        if not rows:
            return None, None

        raw_df = from_observation_rows(rows)
        bucketed = bucket_to_5min(raw_df)
        featured = build_features(bucketed, horizon_minutes, require_target=False)
        if featured.empty:
            return None, None

        last = featured.iloc[-1]
        missing = [c for c in feature_cols if c not in last.index]
        if missing:
            # The registered model expects a feature this dataset can't
            # currently supply (e.g. gate_inflow with no gate data live) --
            # refuse to substitute a zero for it.
            return None, None
        row = {c: last[c] for c in [*feature_cols, "hour", "day_of_week"]}
        row["lot_id"] = last["lot_id"]
        return row, rows[-1]["timestamp"]

    async def _twin_capacity(self, session: AsyncSession, campus_id: str, lot_id: str) -> float | None:
        state = await self._twin_repository.get_parking_state(session, lot_id)
        if state is None or state.campus_id != campus_id:
            return None
        return float(state.usable_capacity)

    async def _store(
        self,
        session: AsyncSession,
        prediction_id: str,
        campus_id: str,
        parking_lot_id: str,
        horizon_minutes: int,
        prediction_timestamp: datetime,
        target_timestamp: datetime,
        point_estimate: float | None,
        lower_bound: float | None,
        upper_bound: float | None,
        model_version: str | None,
        confidence: str,
        evaluation_id: str | None,
        feature_snapshot: dict,
    ) -> PredictionResult:
        row = StoredPrediction(
            prediction_id=prediction_id,
            campus_id=campus_id,
            parking_lot_id=parking_lot_id,
            horizon_minutes=horizon_minutes,
            prediction_timestamp=prediction_timestamp,
            target_timestamp=target_timestamp,
            point_estimate=point_estimate,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            confidence=confidence,
            model_version=model_version,
            dataset_version=None,
            preprocessing_version=None,
            feature_version=None,
            evaluation_id=evaluation_id,
            feature_snapshot={k: (v if not hasattr(v, "item") else v.item()) for k, v in feature_snapshot.items()},
        )
        session.add(row)
        await session.commit()
        return PredictionResult(
            prediction_id=prediction_id,
            campus_id=campus_id,
            parking_lot_id=parking_lot_id,
            horizon_minutes=horizon_minutes,
            prediction_timestamp=prediction_timestamp,
            target_timestamp=target_timestamp,
            point_estimate=point_estimate,
            lower_bound=lower_bound,
            upper_bound=upper_bound,
            model_version=model_version,
            confidence=confidence,
        )
