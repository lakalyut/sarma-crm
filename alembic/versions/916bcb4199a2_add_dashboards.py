"""add dashboards

Revision ID: 916bcb4199a2
Revises: 3342622ecff8
Create Date: 2026-07-21 20:23:33.634831

"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "916bcb4199a2"
down_revision = "3342622ecff8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "dashboards" not in tables:
        op.create_table(
            "dashboards",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("is_default", sa.Boolean(), nullable=False),
            sa.Column("cities", sa.JSON(), nullable=False),
            sa.Column("clients", sa.JSON(), nullable=False),
            sa.Column("months", sa.JSON(), nullable=False),
            sa.Column("compare_mode", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    if "dashboard_widgets" not in tables:
        op.create_table(
            "dashboard_widgets",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("dashboard_id", sa.Integer(), nullable=False),
            sa.Column("metric", sa.String(), nullable=False),
            sa.Column("widget_type", sa.String(), nullable=False),
            sa.Column("chart_kind", sa.String(), nullable=True),
            sa.Column("grid_x", sa.Integer(), nullable=False),
            sa.Column("grid_y", sa.Integer(), nullable=False),
            sa.Column("grid_w", sa.Integer(), nullable=False),
            sa.Column("grid_h", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["dashboard_id"], ["dashboards.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    op.drop_table("dashboard_widgets")
    op.drop_table("dashboards")
