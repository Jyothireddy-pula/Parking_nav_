"""Add provenance to gates/roads/parking_lots/destinations.

Every stored campus-config value must carry exactly one provenance
label (REAL / EXTERNAL_MAP_REFERENCE / SAMPLE) — this was previously
untracked at the entity level. Existing rows are backfilled as SAMPLE,
matching the only data that existed before this migration (the
fabricated `sample` campus).

Revision ID: 0007_config_provenance
Revises: 0006_cv_calibration
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_config_provenance"
down_revision: str | None = "0006_cv_calibration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PROVENANCE_ENUM = sa.Enum(
    "REAL", "EXTERNAL_MAP_REFERENCE", "SAMPLE", name="config_provenance", native_enum=False
)

TABLES = ("gates", "roads", "parking_lots", "destinations")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("provenance", PROVENANCE_ENUM, nullable=True))
        op.execute(f"UPDATE {table} SET provenance = 'SAMPLE' WHERE provenance IS NULL")
        with op.batch_alter_table(table) as batch_op:
            batch_op.alter_column("provenance", nullable=False)


def downgrade() -> None:
    for table in TABLES:
        op.drop_column(table, "provenance")
