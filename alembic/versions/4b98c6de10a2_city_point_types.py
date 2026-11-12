"""Remember original sales types and city-specific point type mappings."""

import sqlalchemy as sa

from alembic import op

revision = "4b98c6de10a2"
down_revision = "fe64c0b2ea51"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sales", sa.Column("raw_point_type", sa.String()))
    op.create_table(
        "city_point_type_mappings",
        sa.Column("city", sa.String(), primary_key=True),
        sa.Column("source_type", sa.String(), primary_key=True),
        sa.Column("target_type", sa.String(), nullable=False),
    )


def downgrade():
    op.drop_table("city_point_type_mappings")
    op.drop_column("sales", "raw_point_type")
