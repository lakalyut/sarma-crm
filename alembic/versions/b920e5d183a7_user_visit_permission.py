"""Separate real-visit permission for analytical users."""

import sqlalchemy as sa

from alembic import op

revision = "b920e5d183a7"
down_revision = "a812d74c6e90"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users",
        sa.Column(
            "can_create_visits", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade():
    op.drop_column("users", "can_create_visits")
