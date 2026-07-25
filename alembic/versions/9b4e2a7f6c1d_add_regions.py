"""add regions (макро-регионы: город → регион, справочник для «Аналитики по регионам»)

Revision ID: 9b4e2a7f6c1d
Revises: 7a1f2c9d5b3e
Create Date: 2026-07-25 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "9b4e2a7f6c1d"
down_revision = "7a1f2c9d5b3e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "regions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "city_regions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("city", sa.String(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["region_id"], ["regions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("city"),
    )


def downgrade() -> None:
    op.drop_table("city_regions")
    op.drop_table("regions")
