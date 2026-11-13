"""Persist global analytics thresholds."""

import sqlalchemy as sa

from alembic import op

revision = "74bd61cb9021"
down_revision = "2c7d50ef94ab"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "analytics_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("values", sa.JSON(), nullable=False),
    )
    op.execute(
        sa.table(
            "analytics_settings",
            sa.column("id", sa.Integer),
            sa.column("values", sa.JSON),
        )
        .insert()
        .values([{"id": 1, "values": {}}, {"id": 2, "values": {}}])
    )


def downgrade():
    op.drop_table("analytics_settings")
