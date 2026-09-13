from sqlalchemy import Boolean, ForeignKey, Integer, String
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

    # Capacity must come from a verified physical count (Module 1B/2), never
    # derived from map area.
    total_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    usable_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    restricted_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    temporarily_unavailable_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
