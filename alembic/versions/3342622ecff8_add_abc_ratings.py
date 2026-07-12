"""add abc ratings

Revision ID: 3342622ecff8
Revises: 02188a8a23d7
Create Date: 2026-07-12 00:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy import inspect

from alembic import op

revision = "3342622ecff8"
down_revision = "02188a8a23d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    columns = {c["name"] for c in inspector.get_columns("products")}

    if "is_new" not in columns:
        op.add_column(
            "products",
            sa.Column(
                "is_new", sa.Boolean(), nullable=False, server_default=sa.false()
            ),
        )

    if "abc_segments" not in tables:
        op.create_table(
            "abc_segments",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("name"),
        )

    if "product_abc_ratings" not in tables:
        op.create_table(
            "product_abc_ratings",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("product_id", sa.Integer(), nullable=False),
            sa.Column("segment_id", sa.Integer(), nullable=False),
            sa.Column("category", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
            sa.ForeignKeyConstraint(["segment_id"], ["abc_segments.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "product_id", "segment_id", name="uq_product_abc_segment"
            ),
        )


def downgrade() -> None:
    op.drop_table("product_abc_ratings")
    op.drop_table("abc_segments")
    op.drop_column("products", "is_new")
