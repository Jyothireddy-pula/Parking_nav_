from sqlalchemy import JSON, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

DESTINATION_CATEGORIES = (
    "academic_block",
    "administrative_building",
    "library",
    "hostel",
    "cafeteria",
    "auditorium",
    "sports_facility",
    "medical_facility",
    "parking_lot",
    "gate",
    "other",
)


class Destination(Base, TimestampMixin):
    __tablename__ = "destinations"

    destination_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    department_names: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    searchable_aliases: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    nearest_gates: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    nearest_parking_lots: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # REAL / EXTERNAL_MAP_REFERENCE / SAMPLE — see app.models.provenance.
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
