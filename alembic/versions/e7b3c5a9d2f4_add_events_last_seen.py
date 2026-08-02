"""add users.events_last_seen_at (бейдж непрочитанных на "Ленте")

Revision ID: e7b3c5a9d2f4
Revises: d4e8f2a6b1c9
Create Date: 2026-08-02 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "e7b3c5a9d2f4"
down_revision = "d4e8f2a6b1c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("events_last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "events_last_seen_at")
