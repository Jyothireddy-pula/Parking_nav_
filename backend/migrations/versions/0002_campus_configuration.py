"""Create campus configuration tables (Module 1).

Revision ID: 0002_campus_configuration
Revises: 0001_foundation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_campus_configuration"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campuses",
        sa.Column("campus_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("active_configuration_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "gates",
        sa.Column("gate_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("capacity", sa.Integer, nullable=False),
        sa.Column(
            "status", sa.Enum("open", "closed", "restricted", name="gate_status", native_enum=False), nullable=False
        ),
        sa.Column("configuration_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gates_campus_id", "gates", ["campus_id"])

    op.create_table(
        "roads",
        sa.Column("road_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("start_node", sa.String(64), nullable=False),
        sa.Column("end_node", sa.String(64), nullable=False),
        sa.Column("length", sa.Float, nullable=False),
        sa.Column("expected_travel_time", sa.Float, nullable=False),
        sa.Column("is_walkable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_driveable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column(
            "status", sa.Enum("open", "closed", "restricted", name="road_status", native_enum=False), nullable=False
        ),
        sa.Column("geometry", sa.JSON, nullable=False),
        sa.Column("configuration_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_roads_campus_id", "roads", ["campus_id"])

    op.create_table(
        "parking_lots",
        sa.Column("parking_lot_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "status", sa.Enum("open", "closed", "restricted", name="parking_lot_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("camera_available", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("camera_notes", sa.String(2000), nullable=True),
        sa.Column("total_capacity", sa.Integer, nullable=False),
        sa.Column("usable_capacity", sa.Integer, nullable=False),
        sa.Column("reserved_capacity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("restricted_capacity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("temporarily_unavailable_capacity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("configuration_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_parking_lots_campus_id", "parking_lots", ["campus_id"])

    op.create_table(
        "destinations",
        sa.Column("destination_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "category",
            sa.Enum(
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
                name="destination_category",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("latitude", sa.Float, nullable=False),
        sa.Column("longitude", sa.Float, nullable=False),
        sa.Column("department_names", sa.JSON, nullable=False),
        sa.Column("searchable_aliases", sa.JSON, nullable=False),
        sa.Column("nearest_gates", sa.JSON, nullable=False),
        sa.Column("nearest_parking_lots", sa.JSON, nullable=False),
        sa.Column("configuration_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_destinations_campus_id", "destinations", ["campus_id"])

    op.create_table(
        "events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expected_demand_multiplier", sa.Float, nullable=False),
        sa.Column("affected_zones", sa.JSON, nullable=False),
        sa.Column(
            "status",
            sa.Enum("scheduled", "active", "completed", "cancelled", name="event_status", native_enum=False),
            nullable=False,
        ),
        sa.Column("configuration_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_campus_id", "events", ["campus_id"])

    op.create_table(
        "route_edges",
        sa.Column("route_edge_id", sa.String(160), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("road_id", sa.String(64), sa.ForeignKey("roads.road_id"), nullable=False),
        sa.Column("from_node", sa.String(64), nullable=False),
        sa.Column("to_node", sa.String(64), nullable=False),
        sa.Column("mode", sa.Enum("walk", "drive", name="route_edge_mode", native_enum=False), nullable=False),
        sa.Column("distance", sa.Float, nullable=False),
        sa.Column("travel_time", sa.Float, nullable=False),
        sa.Column("configuration_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_route_edges_campus_id", "route_edges", ["campus_id"])
    op.create_index("ix_route_edges_road_id", "route_edges", ["road_id"])
    op.create_index("ix_route_edges_from_node", "route_edges", ["from_node"])
    op.create_index("ix_route_edges_to_node", "route_edges", ["to_node"])


def downgrade() -> None:
    op.drop_table("route_edges")
    op.drop_table("events")
    op.drop_table("destinations")
    op.drop_table("parking_lots")
    op.drop_table("roads")
    op.drop_table("gates")
    op.drop_table("campuses")
