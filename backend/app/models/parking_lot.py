from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

PARKING_LOT_STATUSES = ("open", "closed", "restricted")


class ParkingLot(Base, TimestampMixin):
    __tablename__ = "parking_lots"

    parking_lot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    camera_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    camera_notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Walked perimeter (4+ [lat, lng] points) and center point from Module 1B's
    # GPS survey. Nullable: not every lot has been surveyed yet.
    center_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    center_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    geometry: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Capacity must come from a verified physical count (Module 1B/2), never
    # derived from map area.
    total_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    usable_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    restricted_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    temporarily_unavailable_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # REAL or SAMPLE only — never EXTERNAL_MAP_REFERENCE, since capacity can
    # never come from a map source (see app.models.provenance).
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
