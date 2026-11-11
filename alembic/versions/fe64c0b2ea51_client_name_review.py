"""Remember reviewed client names within a city."""

import sqlalchemy as sa

from alembic import op

revision = "fe64c0b2ea51"
down_revision = "c0418fa39d2b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "client_name_aliases",
        sa.Column("city", sa.String(), primary_key=True),
        sa.Column("source_name", sa.String(), primary_key=True),
        sa.Column("canonical_name", sa.String(), nullable=False),
    )
    op.create_table(
        "client_name_dismissals",
        sa.Column("city", sa.String(), primary_key=True),
        sa.Column("first_name", sa.String(), primary_key=True),
        sa.Column("second_name", sa.String(), primary_key=True),
    )


def downgrade():
    op.drop_table("client_name_dismissals")
    op.drop_table("client_name_aliases")
