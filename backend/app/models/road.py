from sqlalchemy import JSON, Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

ROAD_STATUSES = ("open", "closed", "restricted")


class Road(Base, TimestampMixin):
    __tablename__ = "roads"

    road_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    start_node: Mapped[str] = mapped_column(String(64), nullable=False)
    end_node: Mapped[str] = mapped_column(String(64), nullable=False)
    length: Mapped[float] = mapped_column(Float, nullable=False)
    expected_travel_time: Mapped[float] = mapped_column(Float, nullable=False)
    is_walkable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_driveable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    # Ordered [lat, lng] points forming the real walked/driven path (provenance
    # REAL) or a digitized path pulled from a map source pending walk
    # verification (provenance EXTERNAL_MAP_REFERENCE). Must contain more than
    # the two endpoint coordinates — see Module 1B's GPS survey output.
    geometry: Mapped[list] = mapped_column(JSON, nullable=False)
    # REAL / EXTERNAL_MAP_REFERENCE / SAMPLE — see app.models.provenance.
    provenance: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
