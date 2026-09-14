from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ExperimentRun(Base, TimestampMixin):
    """Module 8: one experiment = a scenario run across a grid of allocation
    strategies x seeds. raw_results holds every individual (strategy, seed)
    run's metrics; aggregated holds mean/std-dev/95% CI per strategy per
    metric, computed only from raw_results — never entered by hand, never
    edited after the fact. Charts and comparisons are generated from this
    stored data, not recomputed by hand."""

    __tablename__ = "experiment_runs"

    experiment_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    scenario_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategies: Mapped[list] = mapped_column(JSON, nullable=False)
    seeds: Mapped[list] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_results: Mapped[list] = mapped_column(JSON, nullable=False)
    aggregated: Mapped[dict] = mapped_column(JSON, nullable=False)
