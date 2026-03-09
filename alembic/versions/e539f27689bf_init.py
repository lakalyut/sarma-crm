"""init

Revision ID: e539f27689bf
Revises:
Create Date: 2026-02-27 18:22:54.883587
"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "e539f27689bf"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if "products" not in tables:
        op.create_table(
            "products",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.Column("brand", sa.String(), nullable=False),
            sa.Column("line", sa.String(), nullable=True),
            sa.Column("flavor", sa.String(), nullable=False),
            sa.Column("canonical_sku", sa.String(), nullable=False),
            sa.Column("canonical_name", sa.String(), nullable=False),
            sa.Column("default_weight_g", sa.Integer(), nullable=True),
            sa.Column("norm_brand", sa.String(), nullable=False),
            sa.Column("norm_flavor", sa.String(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if "sales" not in tables:
        op.create_table(
            "sales",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("city", sa.String(), nullable=True),
            sa.Column("month", sa.String(), nullable=True),
            sa.Column("type", sa.String(), nullable=True),
            sa.Column("client", sa.String(), nullable=True),
            sa.Column("raw_name", sa.String(), nullable=True),
            sa.Column("raw_sku", sa.String(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("sku", sa.String(), nullable=True),
            sa.Column("name", sa.String(), nullable=True),
            sa.Column("qty", sa.Float(), nullable=True),
            sa.Column("weight", sa.Float(), nullable=True),
            sa.Column("matched", sa.Boolean(), nullable=True),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    op.drop_table("sales")
    op.drop_table("products")
