from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class CvCalibrationReport(Base, TimestampMixin):
    """Module 5: measured error of the CV occupancy classifier against
    Module 2's manual ground-truth counts, for one lot. This is the only
    thing that can promote a lot from cv_verified to cv_auto — see
    ml/cv/promotion.py."""

    __tablename__ = "cv_calibration_reports"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    parking_lot_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    mae: Mapped[float] = mapped_column(Float, nullable=False)
    recommended_collection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
