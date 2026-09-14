"""Create simulation_runs table (Module 7).

Revision ID: 0008_simulation
Revises: 0007_config_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_simulation"
down_revision: str | None = "0007_config_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "simulation_runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("campus_id", sa.String(64), sa.ForeignKey("campuses.campus_id"), nullable=False),
        sa.Column("scenario_id", sa.String(64), nullable=False),
        sa.Column("seed", sa.Integer, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_minutes", sa.Integer, nullable=False),
        sa.Column("metrics", sa.JSON, nullable=False),
        sa.Column("run_log", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_simulation_runs_campus_id", "simulation_runs", ["campus_id"])
    op.create_index("ix_simulation_runs_scenario_id", "simulation_runs", ["scenario_id"])


def downgrade() -> None:
    op.drop_table("simulation_runs")
