"""drop dashboards (виджет-конструктор заменён фиксированной страницей аналитики по регионам)

Revision ID: 7a1f2c9d5b3e
Revises: 55b44a79ebea
Create Date: 2026-07-24 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "7a1f2c9d5b3e"
down_revision = "55b44a79ebea"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_table("dashboard_widgets")
    op.drop_table("dashboards")


def downgrade() -> None:
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
