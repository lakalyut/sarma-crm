"""Release announcements and persistent Telegram delivery queue."""

import sqlalchemy as sa

from alembic import op

revision = "a812d74c6e90"
down_revision = "1f09f136d9f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("telegram_chat_id", sa.BigInteger()))
    op.add_column(
        "users",
        sa.Column(
            "updates_enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )
    op.create_table(
        "release_updates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("release_key", sa.String(120), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("audience", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "update_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "update_id",
            sa.Integer(),
            sa.ForeignKey("release_updates.id"),
            nullable=False,
        ),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient", sa.String(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.String(300)),
        sa.Column("attempted_at", sa.DateTime(timezone=True)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("update_id", "telegram_id", name="uq_update_recipient"),
    )
    op.create_index("ix_update_deliveries_status", "update_deliveries", ["status"])


def downgrade():
    op.drop_table("update_deliveries")
    op.drop_table("release_updates")
    op.drop_column("users", "updates_enabled")
    op.drop_column("users", "telegram_chat_id")
