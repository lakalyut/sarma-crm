"""Горизонт 13, Этап 4 — лидерборд амбассадоров.

Один сервис на два веб-фронтенда (/leaderboard и /ambassador/leaderboard —
вкладка в Telegram-мини-аппе фильтр по месяцам пока не получила, см.
ROADMAP.md) — без фильтра по региону, это агрегированная статистика, не
список клиентов конкретного региона (той чувствительности, из-за которой на
Этапе 3 резали клиентов по региону амбассадора, здесь нет).

Месяц берётся из Visit.created_at (настоящий datetime, не Sale.month) —
в отличие от Sale, тут нет унаследованного двух-форматного наследия, формат
всегда один и тот же ISO 'YYYY-MM-01', потому что колонку заполняет только
код этого проекта, не сторонний импорт."""

from sqlalchemy.orm import Session

from ..auth_models import User
from ..models import AbcSegment, Product, ProductAbcRating, Visit, VisitProduct
from ..utils.dates import month_sort_key, parse_month
from .abc_service import guess_default_segment


def get_leaderboard_months(db: Session) -> list[str]:
    rows = db.query(Visit.created_at).all()
    months = {row[0].strftime("%Y-%m-01") for row in rows if row[0]}
    return sorted(months, key=month_sort_key, reverse=True)


def get_leaderboard(
    db: Session, selected_months: list[str] | None = None
) -> list[dict]:
    ambassadors = db.query(User).filter(User.role == "ambassador").all()
    if not ambassadors:
        return []

    ambassador_ids = [a.id for a in ambassadors]

    segments = db.query(AbcSegment).order_by(AbcSegment.sort_order, AbcSegment.id).all()
    rating_by_segment: dict[int, dict[int, str]] = {}
    for rating in db.query(ProductAbcRating).all():
        rating_by_segment.setdefault(rating.segment_id, {})[
            rating.product_id
        ] = rating.category

    visits = db.query(Visit).filter(Visit.ambassador_id.in_(ambassador_ids)).all()
    if selected_months:
        wanted = {parse_month(m) for m in selected_months}
        wanted.discard(None)
        visits = [
            v for v in visits if (v.created_at.year, v.created_at.month) in wanted
        ]
    visit_by_id = {v.id: v for v in visits}

    visit_products = (
        db.query(VisitProduct, Product)
        .join(Product, Product.id == VisitProduct.product_id)
        .filter(VisitProduct.visit_id.in_(visit_by_id.keys()))
        .all()
        if visit_by_id
        else []
    )

    stats = {a.id: {"visits": 0, "category_a": 0, "aromas": set()} for a in ambassadors}
    for visit in visits:
        stats[visit.ambassador_id]["visits"] += 1

    segment_id_by_type: dict[str, int | None] = {}

    def guessed_segment_id(sale_type: str) -> int | None:
        if sale_type not in segment_id_by_type:
            segment = guess_default_segment(segments, sale_type)
            segment_id_by_type[sale_type] = segment.id if segment else None
        return segment_id_by_type[sale_type]

    for visit_product, product in visit_products:
        visit = visit_by_id[visit_product.visit_id]
        row = stats[visit.ambassador_id]
        row["aromas"].add(product.flavor)

        segment_id = guessed_segment_id(visit.sale_type)
        if segment_id is not None:
            category = rating_by_segment.get(segment_id, {}).get(product.id)
            if category == "A":
                row["category_a"] += 1

    rows = []
    for ambassador in ambassadors:
        row = stats[ambassador.id]
        name = f"{ambassador.first_name or ''} {ambassador.last_name or ''}".strip()
        rows.append(
            {
                "ambassador": name or ambassador.email,
                "region": ambassador.region.name if ambassador.region else "—",
                "visits": row["visits"],
                "category_a": row["category_a"],
                "aromas": sorted(row["aromas"]),
            }
        )

    rows.sort(key=lambda r: (-r["visits"], -r["category_a"]))
    return rows
