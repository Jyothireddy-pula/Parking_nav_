"""Digital twin live state (Module 3). These tables hold the *current*
observed state of the campus, scoped by campus_id, derived from Module 1's
static config but never a substitute for it — capacities here are seeded
from config and are not the source of truth for what a lot's capacity is.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

OBSERVATION_SOURCES = ("manual", "cv_auto", "cv_verified", "simulation")
PROVENANCE_LABELS = ("REAL", "EXTERNAL", "SYNTHETIC", "SAMPLE", "COUNTERFACTUAL")
VEHICLE_STATES = ("approaching", "searching", "assigned", "parked", "leaving", "completed")


class CampusState(Base, TimestampMixin):
    __tablename__ = "campus_states"

    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), primary_key=True)
    active_scenario: Mapped[str] = mapped_column(String(64), nullable=False, default="normal")
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at_twin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ParkingState(Base, TimestampMixin):
    __tablename__ = "parking_states"

    parking_lot_id: Mapped[str] = mapped_column(ForeignKey("parking_lots.parking_lot_id"), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)

    # Mirrored from Module 1 config at init time; not independently editable here.
    total_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    usable_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    restricted_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    temporarily_unavailable_capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    occupied: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predicted_occupancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")

    observation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)


class GateState(Base, TimestampMixin):
    __tablename__ = "gate_states"

    gate_id: Mapped[str] = mapped_column(ForeignKey("gates.gate_id"), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)

    queue: Mapped[int | None] = mapped_column(Integer, nullable=True)
    throughput: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")

    observation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)


class RoadState(Base, TimestampMixin):
    __tablename__ = "road_states"

    road_id: Mapped[str] = mapped_column(ForeignKey("roads.road_id"), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)

    load: Mapped[float | None] = mapped_column(Float, nullable=True)
    congestion: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")

    observation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)


class VehicleState(Base, TimestampMixin):
    __tablename__ = "vehicle_states"

    vehicle_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)

    state: Mapped[str] = mapped_column(String(32), nullable=False)
    assigned_parking_lot_id: Mapped[str | None] = mapped_column(
        ForeignKey("parking_lots.parking_lot_id"), nullable=True
    )

    observation_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provenance: Mapped[str | None] = mapped_column(String(32), nullable=True)


class TwinSnapshot(Base, TimestampMixin):
    """A point-in-time capture of the full twin state, taken periodically
    (see DigitalTwinService.snapshot — intended to be called every 5
    minutes by an external scheduler; this module does not itself run one).
    """

    __tablename__ = "twin_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
