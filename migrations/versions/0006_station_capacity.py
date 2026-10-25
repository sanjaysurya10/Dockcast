"""station_capacity history

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-25

Owner decision 2026-10-25: capacity at the time of each observation (capacities changed over
time; using today's capacity for past rows is wrong and leaks future information). Stored as
change points (one row per station per change) instead of a column on ~20 M raw rows.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "station_capacity",
        sa.Column("station_key", sa.BigInteger(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("capacity >= 0", name="station_capacity_non_negative"),
        sa.ForeignKeyConstraint(["station_key"], ["stations.station_key"]),
        sa.PrimaryKeyConstraint("station_key", "valid_from"),
    )


def downgrade() -> None:
    op.drop_table("station_capacity")
