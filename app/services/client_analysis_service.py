from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale
from .abc_service import get_abc_badges_for_clients
from .sale_filters import build_sale_filters


def get_types_rollup(
    db: Session,
    city: str,
    months: list[str] | None = None,
    clients: list[str] | None = None,
) -> list[dict]:
    filters = build_sale_filters(city=city, months=months, clients=clients)

    totals_rows = (
        db.query(
            Sale.type.label("type"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
            func.count(func.distinct(Sale.sku)).label("sku_count"),
        )
        .filter(*filters)
        .group_by(Sale.type)
        .all()
    )

    monthly_rows = (
        db.query(
            Sale.type.label("type"),
            Sale.month.label("month"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
            func.count(func.distinct(Sale.sku)).label("sku_count"),
        )
        .filter(*filters)
        .group_by(Sale.type, Sale.month)
        .all()
    )

    months_by_type = defaultdict(dict)
    for row in monthly_rows:
        if not row.month:
            continue

        months_by_type[row.type or "—"][row.month] = {
            "qty": float(row.qty or 0),
            "weight": float(row.weight or 0),
            "sku_count": int(row.sku_count or 0),
        }

    result = [
        {
            "type": row.type or "—",
            "months": months_by_type.get(row.type or "—", {}),
            "total": {
                "qty": float(row.qty or 0),
                "weight": float(row.weight or 0),
                "sku_count": int(row.sku_count or 0),
            },
        }
        for row in totals_rows
    ]
    result.sort(key=lambda r: r["total"]["weight"], reverse=True)
    return result


def get_clients_rollup(
    db: Session,
    city: str,
    sale_type: str,
    months: list[str] | None = None,
    clients: list[str] | None = None,
    segment_id: int | None = None,
) -> list[dict]:
    filters = build_sale_filters(
        city=city, sale_type=sale_type, months=months, clients=clients
    )

    totals_rows = (
        db.query(
            Sale.client.label("client"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
            func.count(func.distinct(Sale.sku)).label("sku_count"),
        )
        .filter(*filters)
        .group_by(Sale.client)
        .all()
    )

    monthly_rows = (
        db.query(
            Sale.client.label("client"),
            Sale.month.label("month"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
            func.count(func.distinct(Sale.sku)).label("sku_count"),
        )
        .filter(*filters)
        .group_by(Sale.client, Sale.month)
        .all()
    )

    months_by_client = defaultdict(dict)
    for row in monthly_rows:
        if not row.month:
            continue

        months_by_client[row.client or "—"][row.month] = {
            "qty": float(row.qty or 0),
            "weight": float(row.weight or 0),
            "sku_count": int(row.sku_count or 0),
        }

    client_names = [row.client or "—" for row in totals_rows]

    abc_badges = {}
    if segment_id:
        abc_badges = get_abc_badges_for_clients(
            db,
            city=city,
            sale_type=sale_type,
            clients=client_names,
            segment_id=segment_id,
        )

    result = [
        {
            "client": row.client or "—",
            "months": months_by_client.get(row.client or "—", {}),
            "total": {
                "qty": float(row.qty or 0),
                "weight": float(row.weight or 0),
                "sku_count": int(row.sku_count or 0),
            },
            "abc": abc_badges.get(row.client or "—", {}),
        }
        for row in totals_rows
    ]
    result.sort(key=lambda r: r["total"]["weight"], reverse=True)
    return result


def get_nomenclature_rollup(
    db: Session,
    city: str,
    client: str,
    sale_type: str,
    months: list[str] | None = None,
) -> list[dict]:
    filters = build_sale_filters(
        city=city, client=client, sale_type=sale_type, months=months
    )

    totals_rows = (
        db.query(
            Sale.name.label("name"),
            Sale.sku.label("sku"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
        )
        .filter(*filters)
        .group_by(Sale.name, Sale.sku)
        .all()
    )

    monthly_rows = (
        db.query(
            Sale.name.label("name"),
            Sale.sku.label("sku"),
            Sale.month.label("month"),
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
        )
        .filter(*filters)
        .group_by(Sale.name, Sale.sku, Sale.month)
        .all()
    )

    months_by_nomenclature = defaultdict(dict)
    for row in monthly_rows:
        if not row.month:
            continue

        months_by_nomenclature[(row.name, row.sku)][row.month] = {
            "qty": float(row.qty or 0),
            "weight": float(row.weight or 0),
        }

    result = [
        {
            "name": row.name,
            "sku": row.sku,
            "months": months_by_nomenclature.get((row.name, row.sku), {}),
            "total": {
                "qty": float(row.qty or 0),
                "weight": float(row.weight or 0),
            },
        }
        for row in totals_rows
    ]
    result.sort(key=lambda r: r["total"]["weight"], reverse=True)
    return result
