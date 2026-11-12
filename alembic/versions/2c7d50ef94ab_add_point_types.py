"""Store additional point types."""

import sqlalchemy as sa

from alembic import op

revision = "2c7d50ef94ab"
down_revision = "4b98c6de10a2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "point_types",
        sa.Column("name_key", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
    )


def downgrade():
    op.drop_table("point_types")
