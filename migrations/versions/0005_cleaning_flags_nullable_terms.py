"""cleaning flags on station_status_15m; nullable calendar term flags

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25

PRD 9.3: per-bucket flags ``rebalance_flag``, ``capacity_mismatch`` and ``flatline_flag``
(thresholds in config/settings.toml [cleaning], tuned from reports/eda.md).
PRD 9.6 / owner decision 2026-10-25: term flags are NULL where no sourced term dates exist.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FLAGS = ("rebalance_flag", "capacity_mismatch", "flatline_flag")


def upgrade() -> None:
    for name in FLAGS:
        op.add_column(
            "station_status_15m",
            sa.Column(name, sa.Boolean(), server_default="false", nullable=False),
        )
    op.alter_column("calendar_days", "is_school_term", nullable=True)
    op.alter_column("calendar_days", "is_uni_term", nullable=True)


def downgrade() -> None:
    op.execute("UPDATE calendar_days SET is_school_term = false WHERE is_school_term IS NULL")
    op.execute("UPDATE calendar_days SET is_uni_term = false WHERE is_uni_term IS NULL")
    op.alter_column("calendar_days", "is_uni_term", nullable=False)
    op.alter_column("calendar_days", "is_school_term", nullable=False)
    for name in reversed(FLAGS):
        op.drop_column("station_status_15m", name)
