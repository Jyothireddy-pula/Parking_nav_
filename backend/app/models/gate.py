from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

GATE_STATUSES = ("open", "closed", "restricted")


class Gate(Base, TimestampMixin):
    __tablename__ = "gates"

    gate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    # REAL / EXTERNAL_MAP_REFERENCE / SAMPLE — see app.models.provenance.
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
