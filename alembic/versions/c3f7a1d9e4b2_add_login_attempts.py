"""add login_attempts (rate-limit на /auth/login по email)

Revision ID: c3f7a1d9e4b2
Revises: 9b4e2a7f6c1d
Create Date: 2026-08-01 00:00:00.000000

"""

import sqlalchemy as sa

from alembic import op

revision = "c3f7a1d9e4b2"
down_revision = "9b4e2a7f6c1d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_login_attempts_email", "login_attempts", ["email"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_login_attempts_email", table_name="login_attempts")
    op.drop_table("login_attempts")
