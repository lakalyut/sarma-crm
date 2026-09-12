"""users telegram_id integer to biginteger

Revision ID: f7be60371402
Revises: 67216350be73
Create Date: 2026-09-12 16:46:00.788603

"""

import sqlalchemy as sa

from alembic import op

revision = "f7be60371402"
down_revision = "67216350be73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table — портируемо и на Postgres (обычный ALTER TABLE ... TYPE),
    # и на SQLite (copy-and-move пересоздание таблицы), см. прецедент в
    # a3d9e6f1c8b7_add_ambassador_role_and_visits.py.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "telegram_id",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "telegram_id",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
