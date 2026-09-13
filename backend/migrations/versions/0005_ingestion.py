"""Create data ingestion tables (Module 4).

Revision ID: 0005_ingestion
Revises: 0004_digital_twin
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_ingestion"
down_revision: str | None = "0004_digital_twin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _observation_columns() -> list[sa.Column]:
    return [
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gate_id", sa.String(64), nullable=True),
        sa.Column("vehicle_count", sa.Integer, nullable=True),
        sa.Column("parking_lot_id", sa.String(64), nullable=True),
        sa.Column("occupied_spaces", sa.Integer, nullable=True),
        sa.Column("event_type", sa.String(64), nullable=True),
        sa.Column("event_intensity", sa.Float, nullable=True),
        sa.Column("notes", sa.String(2000), nullable=True),
        sa.Column(
            "source_label",
            sa.Enum("REAL", "EXTERNAL", "SYNTHETIC", "SAMPLE", name="ingestion_source_label", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "collection_method",
            sa.Enum(
                "manual_count", "cv_auto", "cv_verified", "simulator",
                name="collection_method", native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("batch_id", sa.String(64), sa.ForeignKey("ingestion_batches.batch_id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "ingestion_batches",
        sa.Column("batch_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("submitted_via", sa.String(32), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("total_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("accepted_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("rejected_rows", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ingestion_batches_campus_id", "ingestion_batches", ["campus_id"])

    op.create_table(
        "observations_raw",
        sa.Column("raw_id", sa.String(64), primary_key=True),
        *_observation_columns(),
    )
    op.create_index("ix_observations_raw_campus_id", "observations_raw", ["campus_id"])
    op.create_index("ix_observations_raw_timestamp", "observations_raw", ["timestamp"])

    op.create_table(
        "observations",
        sa.Column("observation_id", sa.String(64), primary_key=True),
        sa.Column("raw_id", sa.String(64), sa.ForeignKey("observations_raw.raw_id"), nullable=False),
        sa.Column("data_quality_flags", sa.JSON, nullable=False),
        *_observation_columns(),
    )
    op.create_index("ix_observations_campus_id", "observations", ["campus_id"])
    op.create_index("ix_observations_timestamp", "observations", ["timestamp"])

    op.create_table(
        "observations_rejected",
        sa.Column("rejection_id", sa.String(64), primary_key=True),
        sa.Column("raw_id", sa.String(64), sa.ForeignKey("observations_raw.raw_id"), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        *_observation_columns(),
    )
    op.create_index("ix_observations_rejected_campus_id", "observations_rejected", ["campus_id"])


def downgrade() -> None:
    op.drop_table("observations_rejected")
    op.drop_table("observations")
    op.drop_table("observations_raw")
    op.drop_table("ingestion_batches")
