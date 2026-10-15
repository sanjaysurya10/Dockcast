"""data_gaps table

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_gaps",
        sa.Column("gap_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("gap_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_before", sa.Text(), nullable=False),
        sa.Column("source_after", sa.Text(), nullable=False),
        sa.Column("duration_s", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("gap_start"),
    )


def downgrade() -> None:
    op.drop_table("data_gaps")
