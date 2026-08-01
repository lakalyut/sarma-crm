"""add event_log (лента событий — пока только тип "import")

Revision ID: d4e8f2a6b1c9
Revises: c3f7a1d9e4b2
Create Date: 2026-08-01 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "d4e8f2a6b1c9"
down_revision = "c3f7a1d9e4b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "event_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("city", sa.String(), nullable=False),
        sa.Column("months", sa.String(), nullable=False),
        sa.Column("rows_imported", sa.Integer(), nullable=False),
        sa.Column("rows_unmatched", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("event_log")
