"""Module 9 — stored predictions and the evaluation reports behind them.
Kept as two tables: an evaluation is produced once per (model, dataset,
horizon) training run; a prediction is produced once per POST /predict
call and references the evaluation that backed it (nullable, since an
INTELLIGENCE_UNAVAILABLE prediction has no model/evaluation behind it at
all -- and that absence must be visible, not papered over)."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

CONFIDENCE_LEVELS = ("HIGH", "MODERATE", "LOW", "DATA_STALE", "INTELLIGENCE_UNAVAILABLE")


class PredictionEvaluation(Base, TimestampMixin):
    __tablename__ = "prediction_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    dataset_label: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(128), nullable=False)
    preprocessing_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)

    mae: Mapped[float] = mapped_column(Float, nullable=False)
    rmse: Mapped[float] = mapped_column(Float, nullable=False)
    r2: Mapped[float | None] = mapped_column(Float, nullable=True)
    wape: Mapped[float | None] = mapped_column(Float, nullable=True)
    mape: Mapped[float | None] = mapped_column(Float, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)

    evaluation_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evaluation_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StoredPrediction(Base, TimestampMixin):
    __tablename__ = "predictions"

    prediction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    parking_lot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False)

    prediction_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    target_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    point_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    lower_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    upper_bound: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence: Mapped[str] = mapped_column(String(32), nullable=False)

    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dataset_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    preprocessing_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    feature_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    evaluation_id: Mapped[str | None] = mapped_column(
        ForeignKey("prediction_evaluations.evaluation_id"), nullable=True
    )
    # Which underlying feature/target values the point estimate came from --
    # never recomputed after the fact, stored as it was actually served.
    feature_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
