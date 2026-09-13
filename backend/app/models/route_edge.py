from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

ROUTE_EDGE_MODES = ("walk", "drive")


class RouteEdge(Base, TimestampMixin):
    """A directed, traversable graph edge between two nodes (gates, parking
    lots, or destinations), materialized from a road's connectivity and
    directionality during config load. This is the routable graph Module 1
    validates for orphan nodes; later modules score paths over it.
    """

    __tablename__ = "route_edges"

    route_edge_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    campus_id: Mapped[str] = mapped_column(ForeignKey("campuses.campus_id"), nullable=False, index=True)
    road_id: Mapped[str] = mapped_column(ForeignKey("roads.road_id"), nullable=False, index=True)
    from_node: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    to_node: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    mode: Mapped[str] = mapped_column(String(16), nullable=False)
    distance: Mapped[float] = mapped_column(Float, nullable=False)
    travel_time: Mapped[float] = mapped_column(Float, nullable=False)
    configuration_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
