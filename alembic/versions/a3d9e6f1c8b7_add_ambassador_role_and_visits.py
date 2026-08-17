"""add ambassador role fields to users + visits/visit_products (горизонт 13, Этап 1)

Revision ID: a3d9e6f1c8b7
Revises: 0ff0c95eb616
Create Date: 2026-08-17 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "a3d9e6f1c8b7"
down_revision = "0ff0c95eb616"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table — не SQLite-специфичный хак, а портируемый способ добавить
    # constraint к существующей таблице: на Postgres это обычный ALTER TABLE, на
    # SQLite (нет ALTER ... ADD CONSTRAINT) alembic делает copy-and-move пересоздание
    # таблицы автоматически. Голый op.create_unique_constraint/op.create_foreign_key
    # падает на SQLite (проверено вживую на локальной main.db).
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("telegram_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("region_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("first_name", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("last_name", sa.String(), nullable=True))
        batch_op.create_unique_constraint("uq_users_telegram_id", ["telegram_id"])
        batch_op.create_foreign_key(
            "fk_users_region_id", "regions", ["region_id"], ["id"]
        )

    op.create_table(
        "visits",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ambassador_id", sa.Integer(), nullable=False),
        sa.Column("city", sa.String(), nullable=False),
        sa.Column("client", sa.String(), nullable=False),
        sa.Column("sale_type", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["ambassador_id"], ["users.id"]),
    )

    op.create_table(
        "visit_products",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("visit_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["visit_id"], ["visits.id"]),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.UniqueConstraint("visit_id", "product_id", name="uq_visit_product"),
    )


def downgrade() -> None:
    op.drop_table("visit_products")
    op.drop_table("visits")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("fk_users_region_id", type_="foreignkey")
        batch_op.drop_constraint("uq_users_telegram_id", type_="unique")
        batch_op.drop_column("last_name")
        batch_op.drop_column("first_name")
        batch_op.drop_column("region_id")
        batch_op.drop_column("telegram_id")
