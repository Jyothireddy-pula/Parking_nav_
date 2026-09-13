"""Add walked perimeter/center geometry to parking lots (Module 1B).

Revision ID: 0003_parking_lot_geometry
Revises: 0002_campus_configuration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_parking_lot_geometry"
down_revision: str | None = "0002_campus_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("parking_lots", sa.Column("center_latitude", sa.Float, nullable=True))
    op.add_column("parking_lots", sa.Column("center_longitude", sa.Float, nullable=True))
    op.add_column("parking_lots", sa.Column("geometry", sa.JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("parking_lots", "geometry")
    op.drop_column("parking_lots", "center_longitude")
    op.drop_column("parking_lots", "center_latitude")
