"""replace User.region_id with User.city (горизонт 13, амбассадор привязан к
городу, не к макро-региону — того же уровня сущность, что Sale.city/Visit.city)

Revision ID: f275937bb327
Revises: a3d9e6f1c8b7
Create Date: 2026-08-18 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "f275937bb327"
down_revision = "a3d9e6f1c8b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("city", sa.String(), nullable=True))
        batch_op.drop_constraint("fk_users_region_id", type_="foreignkey")
        batch_op.drop_column("region_id")


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("region_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_users_region_id", "regions", ["region_id"], ["id"]
        )
        batch_op.drop_column("city")
