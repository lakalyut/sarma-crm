"""Assigned analytics cities for brand ambassadors."""

import sqlalchemy as sa

from alembic import op

revision = "c0418fa39d2b"
down_revision = "b920e5d183a7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_cities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("city", sa.String(), nullable=False),
        sa.UniqueConstraint("user_id", "city", name="uq_user_city"),
    )


def downgrade():
    op.drop_table("user_cities")
