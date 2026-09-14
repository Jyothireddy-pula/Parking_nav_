from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class SimulationRun(Base, TimestampMixin):
    """Module 7: one execution of a scenario. metrics/run_log are always
    derived from a SYNTHETIC scenario — never presented as a real
    observation, no matter how realistic the numbers look."""

    __tablename__ = "simulation_runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    metrics: Mapped[dict] = mapped_column(JSON, nullable=False)
    run_log: Mapped[list] = mapped_column(JSON, nullable=False)
