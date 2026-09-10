"""Горизонт 13.5 — вкладка «Анализ визита» на «Аналитике по клиентам»:
плоская таблица всех визитов выбранного региона (анкета визита целиком —
SKU по линейкам, человек на мероприятии, цель, комментарий) с фильтром по
периоду и клиентам."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Visit, VisitProduct
from ..services.ambassador_service import ambassador_display_name
from ..utils.dates import parse_month


def get_visit_analysis(
    db: Session,
    city: str | None,
    selected_months: list[str],
    selected_clients: list[str],
) -> list[dict]:
    if not city:
        return []

    query = db.query(Visit).filter(Visit.city == city)
    if selected_clients:
        query = query.filter(Visit.client.in_(selected_clients))

    visits = query.order_by(Visit.created_at.desc()).all()

    if selected_months:
        year_months = {parse_month(m) for m in selected_months}
        year_months.discard(None)
        visits = [
            v for v in visits if (v.created_at.year, v.created_at.month) in year_months
        ]

    if not visits:
        return []

    aromas_count = dict(
        db.query(VisitProduct.visit_id, func.count(VisitProduct.id))
        .filter(VisitProduct.visit_id.in_([v.id for v in visits]))
        .group_by(VisitProduct.visit_id)
        .all()
    )

    return [
        {
            "date": v.created_at.strftime("%d.%m.%Y"),
            "client": v.client,
            "sale_type": v.sale_type,
            "goal": (v.goal or "").strip() or "—",
            "comment": (v.comment or "").strip() or "—",
            "sku_classic": v.sku_classic,
            "sku_strong": v.sku_strong,
            "sku_light": v.sku_light,
            "people_count": v.people_count,
            "aromas_count": aromas_count.get(v.id, 0),
            "ambassador": ambassador_display_name(v.ambassador),
        }
        for v in visits
    ]
