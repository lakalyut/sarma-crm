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
    if not city or not selected_months:
        return {"clients": []}

    year_months = {parse_month(m) for m in selected_months}
    year_months.discard(None)
    if not year_months:
        return {"clients": []}

    visit_query = db.query(Visit).filter(Visit.city == city)
    if selected_clients:
        visit_query = visit_query.filter(Visit.client.in_(selected_clients))

    visits = [
        v
        for v in visit_query.all()
        if (v.created_at.year, v.created_at.month) in year_months
    ]
    if not visits:
        return {"clients": []}

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
            {"brand": product.brand, "flavor": product.flavor, "ambassadors": set()},
        )
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
        aromas = sorted(
            (
                {
                    "brand": entry["brand"],
                    "flavor": entry["flavor"],
                    "ordered": product_id in ordered_ids,
                    "ambassadors": sorted(entry["ambassadors"]),
                }
                for product_id, entry in client_aromas.items()
            ),
            key=lambda a: a["flavor"],
        )
        clients_result.append({"name": client, "aromas": aromas})

    return {"clients": clients_result}
