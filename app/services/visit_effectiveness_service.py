"""Горизонт 13, Этап 5 — «Эффективность визита»: сверка ароматов,
продемонстрированных амбассадорами (Visit/VisitProduct), с тем, что клиент
заказал в том же периоде (Sale)."""

from sqlalchemy.orm import Session

from ..models import Product, Sale, Visit, VisitProduct
from ..utils.dates import parse_month


def build_visit_effectiveness_report(
    db: Session,
    city: str | None,
    selected_months: list[str],
    selected_clients: list[str],
) -> dict:
    empty = {"clients": [], "months_without_sales": []}
    if not city or not selected_months:
        return empty

    year_months = {parse_month(m) for m in selected_months}
    year_months.discard(None)
    if not year_months:
        return empty

    visit_query = db.query(Visit).filter(Visit.city == city)
    if selected_clients:
        visit_query = visit_query.filter(Visit.client.in_(selected_clients))

    visits = [
        v
        for v in visit_query.all()
        if (v.created_at.year, v.created_at.month) in year_months
    ]
    if not visits:
        return empty

    # Месяцы выборки, где визиты есть, а продаж ещё нет: продажи приходят
    # на месяц позже (сентябрьские грузят в октябре). Без этой пометки все
    # ароматы за такой месяц покажутся «не заказан» — хотя причина в том,
    # что сверять пока не с чем. Роут потом сведёт аналитику сам, когда
    # продажи подъедут.
    visit_ym = {(v.created_at.year, v.created_at.month) for v in visits}
    sale_ym = {
        parse_month(row[0])
        for row in db.query(Sale.month)
        .filter(Sale.city == city, Sale.month.in_(selected_months))
        .distinct()
    }
    sale_ym.discard(None)
    months_without_sales = [
        f"{y:04d}-{m:02d}-01" for (y, m) in sorted(visit_ym - sale_ym)
    ]

    visit_by_id = {v.id: v for v in visits}

    clients_to_show = (
        list(selected_clients)
        if selected_clients
        else sorted({v.client for v in visits})
    )

    visit_products = (
        db.query(VisitProduct, Product)
        .join(Product, Product.id == VisitProduct.product_id)
        .filter(VisitProduct.visit_id.in_(visit_by_id.keys()))
        .all()
    )

    aromas_by_client: dict[str, dict[int, dict]] = {c: {} for c in clients_to_show}
    for visit_product, product in visit_products:
        visit = visit_by_id[visit_product.visit_id]
        client_aromas = aromas_by_client.get(visit.client)
        if client_aromas is None:
            continue

        entry = client_aromas.setdefault(
            product.id,
            {
                "brand": product.brand,
                "flavor": product.flavor,
                "ambassadors": set(),
                "shown_ym": set(),
            },
        )
        entry["shown_ym"].add((visit.created_at.year, visit.created_at.month))
        ambassador = visit.ambassador
        if ambassador:
            name = f"{ambassador.first_name or ''} {ambassador.last_name or ''}".strip()
            name = name or ambassador.email
        else:
            name = "—"
        entry["ambassadors"].add(name)

    ordered_by_client: dict[str, set[int]] = {}
    if clients_to_show:
        order_rows = (
            db.query(Sale.client, Sale.product_id)
            .filter(
                Sale.city == city,
                Sale.client.in_(clients_to_show),
                Sale.month.in_(selected_months),
                Sale.product_id.isnot(None),
            )
            .all()
        )
        for client, product_id in order_rows:
            ordered_by_client.setdefault(client, set()).add(product_id)

    clients_result = []
    for client in clients_to_show:
        client_aromas = aromas_by_client.get(client, {})
        if not client_aromas:
            continue

        ordered_ids = ordered_by_client.get(client, set())
        aromas = []
        for product_id, entry in client_aromas.items():
            if not (entry["shown_ym"] & sale_ym):
                # аромат показан только в месяц(ы) без загруженных продаж —
                # сверять не с чем, статус «ждём продажи», не «не заказан»
                status = "pending"
            elif product_id in ordered_ids:
                status = "ordered"
            else:
                status = "not_ordered"
            aromas.append(
                {
                    "brand": entry["brand"],
                    "flavor": entry["flavor"],
                    "status": status,
                    "ambassadors": sorted(entry["ambassadors"]),
                }
            )
        aromas.sort(key=lambda a: a["flavor"])
        clients_result.append({"name": client, "aromas": aromas})

    return {
        "clients": clients_result,
        "months_without_sales": months_without_sales,
    }
