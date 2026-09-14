"""Create experiment_runs table (Module 8).

Revision ID: 0009_experiments
Revises: 0008_simulation
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_experiments"
down_revision: str | None = "0008_simulation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "experiment_runs",
        sa.Column("experiment_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("strategies", sa.JSON, nullable=False),
        sa.Column("seeds", sa.JSON, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_results", sa.JSON, nullable=False),
        sa.Column("aggregated", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_experiment_runs_campus_id", "experiment_runs", ["campus_id"])
    op.create_index("ix_experiment_runs_scenario_id", "experiment_runs", ["scenario_id"])


def downgrade() -> None:
    op.drop_table("experiment_runs")
