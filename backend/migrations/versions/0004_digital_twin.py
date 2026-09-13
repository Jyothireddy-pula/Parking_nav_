"""Create digital twin live-state tables (Module 3).

Revision ID: 0004_digital_twin
Revises: 0003_parking_lot_geometry
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_digital_twin"
down_revision: str | None = "0003_parking_lot_geometry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "campus_states",
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), primary_key=True),
        sa.Column("active_scenario", sa.String(64), nullable=False, server_default="normal"),
        sa.Column("config_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("updated_at_twin", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "parking_states",
        sa.Column("parking_lot_id", sa.String(64), sa.ForeignKey("parking_lots.parking_lot_id"), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("total_capacity", sa.Integer, nullable=False),
        sa.Column("usable_capacity", sa.Integer, nullable=False),
        sa.Column("reserved_capacity", sa.Integer, nullable=False),
        sa.Column("restricted_capacity", sa.Integer, nullable=False),
        sa.Column("temporarily_unavailable_capacity", sa.Integer, nullable=False),
        sa.Column("occupied", sa.Integer, nullable=True),
        sa.Column("predicted_occupancy", sa.Float, nullable=True),
        sa.Column(
            "status", sa.Enum("open", "closed", "restricted", name="parking_state_status", native_enum=False),
            nullable=False, server_default="open",
        ),
        sa.Column("observation_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingestion_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "cv_auto", "cv_verified", "simulation", name="observation_source", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "provenance",
            sa.Enum(
                "REAL", "EXTERNAL", "SYNTHETIC", "SAMPLE", "COUNTERFACTUAL",
                name="provenance_label", native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_parking_states_campus_id", "parking_states", ["campus_id"])

    op.create_table(
        "gate_states",
        sa.Column("gate_id", sa.String(64), sa.ForeignKey("gates.gate_id"), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("queue", sa.Integer, nullable=True),
        sa.Column("throughput", sa.Float, nullable=True),
        sa.Column(
            "status", sa.Enum("open", "closed", "restricted", name="gate_state_status", native_enum=False),
            nullable=False, server_default="open",
        ),
        sa.Column("observation_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingestion_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "cv_auto", "cv_verified", "simulation", name="observation_source", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "provenance",
            sa.Enum(
                "REAL", "EXTERNAL", "SYNTHETIC", "SAMPLE", "COUNTERFACTUAL",
                name="provenance_label", native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_gate_states_campus_id", "gate_states", ["campus_id"])

    op.create_table(
        "road_states",
        sa.Column("road_id", sa.String(64), sa.ForeignKey("roads.road_id"), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("load", sa.Float, nullable=True),
        sa.Column("congestion", sa.String(32), nullable=True),
        sa.Column(
            "status", sa.Enum("open", "closed", "restricted", name="road_state_status", native_enum=False),
            nullable=False, server_default="open",
        ),
        sa.Column("observation_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingestion_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "cv_auto", "cv_verified", "simulation", name="observation_source", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "provenance",
            sa.Enum(
                "REAL", "EXTERNAL", "SYNTHETIC", "SAMPLE", "COUNTERFACTUAL",
                name="provenance_label", native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_road_states_campus_id", "road_states", ["campus_id"])

    op.create_table(
        "vehicle_states",
        sa.Column("vehicle_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "approaching", "searching", "assigned", "parked", "leaving", "completed",
                name="vehicle_state_enum", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "assigned_parking_lot_id", sa.String(64), sa.ForeignKey("parking_lots.parking_lot_id"), nullable=True
        ),
        sa.Column("observation_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ingestion_timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.Enum("manual", "cv_auto", "cv_verified", "simulation", name="observation_source", native_enum=False),
            nullable=True,
        ),
        sa.Column(
            "provenance",
            sa.Enum(
                "REAL", "EXTERNAL", "SYNTHETIC", "SAMPLE", "COUNTERFACTUAL",
                name="provenance_label", native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vehicle_states_campus_id", "vehicle_states", ["campus_id"])

    op.create_table(
        "twin_snapshots",
        sa.Column("snapshot_id", sa.String(160), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_twin_snapshots_campus_id", "twin_snapshots", ["campus_id"])
    op.create_index("ix_twin_snapshots_taken_at", "twin_snapshots", ["taken_at"])


def downgrade() -> None:
    op.drop_table("twin_snapshots")
    op.drop_table("vehicle_states")
    op.drop_table("road_states")
    op.drop_table("gate_states")
    op.drop_table("parking_states")
    op.drop_table("campus_states")
