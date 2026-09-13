"""Module 4 — data ingestion. observations_raw is immutable/append-only:
nothing here is ever updated or deleted, even for rows that turn out to be
invalid — that's what observations_rejected is for. Validated data lives in
observations. None of these tables use foreign keys on gate_id/
parking_lot_id: unknown/garbage IDs are an expected input (that's exactly
what the "unknown ID" rejection path exercises), and historical
observations must survive a config entity being renamed or removed later.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

SOURCE_LABELS = ("REAL", "EXTERNAL", "SYNTHETIC", "SAMPLE")
COLLECTION_METHODS = ("manual_count", "cv_auto", "cv_verified", "simulator")


class IngestionBatch(Base, TimestampMixin):
    __tablename__ = "ingestion_batches"

    batch_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    submitted_via: Mapped[str] = mapped_column(String(32), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    accepted_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class _ObservationColumns:
    """Column set shared by observations_raw/observations/observations_rejected."""

    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    gate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    vehicle_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parking_lot_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    occupied_spaces: Mapped[int | None] = mapped_column(Integer, nullable=True)
    event_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_intensity: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    source_label: Mapped[str] = mapped_column(String(32), nullable=False)
    collection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    batch_id: Mapped[str | None] = mapped_column(ForeignKey("ingestion_batches.batch_id"), nullable=True)


class ObservationRaw(_ObservationColumns, Base, TimestampMixin):
    """Immutable, append-only record of exactly what was submitted —
    including rows that later get rejected. Never updated, never deleted."""

    __tablename__ = "observations_raw"

    raw_id: Mapped[str] = mapped_column(String(64), primary_key=True)


class Observation(_ObservationColumns, Base, TimestampMixin):
    __tablename__ = "observations"

    observation_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    raw_id: Mapped[str] = mapped_column(ForeignKey("observations_raw.raw_id"), nullable=False)
    data_quality_flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)


class ObservationRejected(_ObservationColumns, Base, TimestampMixin):
    __tablename__ = "observations_rejected"

    rejection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    raw_id: Mapped[str] = mapped_column(ForeignKey("observations_raw.raw_id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(2000), nullable=False)
