"""forecast_drivers

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-01

PRD 16.4 "What drives this forecast": TreeSHAP contributions of each feature group to the P50
forecast, written by the forecast job. Only the latest issue is kept (about 2,000 rows), so the
table stays small on the hosted free tier.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forecast_drivers",
        sa.Column("station_key", sa.BigInteger(), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_min", sa.Integer(), nullable=False),
        sa.Column("feature_group", sa.Text(), nullable=False),
        sa.Column("contribution", sa.REAL(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["station_key"], ["stations.station_key"]),
        sa.PrimaryKeyConstraint("station_key", "issued_at", "horizon_min", "feature_group"),
    )


def downgrade() -> None:
    op.drop_table("forecast_drivers")
