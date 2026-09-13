"""Create cv_calibration_reports table (Module 5).

Revision ID: 0006_cv_calibration
Revises: 0005_ingestion
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_cv_calibration"
down_revision: str | None = "0005_ingestion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cv_calibration_reports",
        sa.Column("report_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("parking_lot_id", sa.String(64), nullable=False),
        sa.Column("sample_size", sa.Integer, nullable=False),
        sa.Column("mae", sa.Float, nullable=False),
        sa.Column("recommended_collection_method", sa.String(32), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_cv_calibration_reports_campus_id", "cv_calibration_reports", ["campus_id"])
    op.create_index("ix_cv_calibration_reports_parking_lot_id", "cv_calibration_reports", ["parking_lot_id"])


def downgrade() -> None:
    op.drop_table("cv_calibration_reports")
