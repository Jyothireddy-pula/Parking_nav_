"""Create prediction_evaluations and predictions tables (Module 9).

Revision ID: 0010_prediction
Revises: 0009_experiments
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_prediction"
down_revision: str | None = "0009_experiments"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prediction_evaluations",
        sa.Column("evaluation_id", sa.String(64), primary_key=True),
        sa.Column("dataset_label", sa.String(128), nullable=False),
        sa.Column("model_name", sa.String(64), nullable=False),
        sa.Column("horizon_minutes", sa.Integer, nullable=False),
        sa.Column("model_version", sa.String(64), nullable=False),
        sa.Column("dataset_version", sa.String(128), nullable=False),
        sa.Column("preprocessing_version", sa.String(64), nullable=False),
        sa.Column("feature_version", sa.String(64), nullable=False),
        sa.Column("mae", sa.Float, nullable=False),
        sa.Column("rmse", sa.Float, nullable=False),
        sa.Column("r2", sa.Float, nullable=True),
        sa.Column("wape", sa.Float, nullable=True),
        sa.Column("mape", sa.Float, nullable=True),
        sa.Column("sample_size", sa.Integer, nullable=False),
        sa.Column("evaluation_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evaluation_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_prediction_evaluations_dataset_label", "prediction_evaluations", ["dataset_label"])

    op.create_table(
        "predictions",
        sa.Column("prediction_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("parking_lot_id", sa.String(64), nullable=False),
        sa.Column("horizon_minutes", sa.Integer, nullable=False),
        sa.Column("prediction_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("point_estimate", sa.Float, nullable=True),
        sa.Column("lower_bound", sa.Float, nullable=True),
        sa.Column("upper_bound", sa.Float, nullable=True),
        sa.Column("confidence", sa.String(32), nullable=False),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("dataset_version", sa.String(128), nullable=True),
        sa.Column("preprocessing_version", sa.String(64), nullable=True),
        sa.Column("feature_version", sa.String(64), nullable=True),
        sa.Column(
            "evaluation_id", sa.String(64), sa.ForeignKey("prediction_evaluations.evaluation_id"), nullable=True
        ),
        sa.Column("feature_snapshot", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_predictions_campus_id", "predictions", ["campus_id"])
    op.create_index("ix_predictions_parking_lot_id", "predictions", ["parking_lot_id"])


def downgrade() -> None:
    op.drop_table("predictions")
    op.drop_table("prediction_evaluations")
