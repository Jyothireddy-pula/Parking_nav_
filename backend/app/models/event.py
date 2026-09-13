from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

EVENT_STATUSES = ("scheduled", "active", "completed", "cancelled")


class Event(Base, TimestampMixin):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # An explicit ASSUMPTION/configuration parameter — never a measured fact
    # unless backed by real observations.
    expected_demand_multiplier: Mapped[float] = mapped_column(Float, nullable=False)
    affected_zones: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="scheduled")
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
