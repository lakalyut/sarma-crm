"""add dashboard split_by

Revision ID: 014a951cae12
Revises: 916bcb4199a2
Create Date: 2026-07-21 22:34:13.255068

"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "014a951cae12"
down_revision = "916bcb4199a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("dashboards")}

    if "split_by" not in columns:
        op.add_column(
            "dashboards",
            sa.Column("split_by", sa.String(), nullable=False, server_default="city"),
        )


def downgrade() -> None:
    op.drop_column("dashboards", "split_by")
