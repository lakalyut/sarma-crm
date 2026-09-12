"""индекс sales.month для главной страницы (агрегаты по всем городам)

Revision ID: 1f09f136d9f6
Revises: f7be60371402
Create Date: 2026-09-13 00:09:29.306870

"""

from alembic import op

revision = "1f09f136d9f6"
down_revision = "f7be60371402"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Существующие ix_sales_city_month / ix_sales_city_client_type — оба
    # ведут с city, бесполезны для главной страницы (горизонт 17): она
    # впервые в проекте агрегирует sales БЕЗ фильтра по городу (весь
    # бизнес сразу), только по month.in_(...) — без этого индекса такие
    # запросы это full table scan.
    op.create_index("ix_sales_month", "sales", ["month"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_sales_month", table_name="sales")
