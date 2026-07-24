"""откат split_by дашборда

Revision ID: 55b44a79ebea
Revises: 014a951cae12
Create Date: 2026-07-24 12:18:08.968181

"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "55b44a79ebea"
down_revision = "014a951cae12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("dashboards")}

    if "split_by" in columns:
        op.drop_column("dashboards", "split_by")


def downgrade() -> None:
    op.add_column(
        "dashboards",
        sa.Column("split_by", sa.String(), nullable=False, server_default="city"),
    )
