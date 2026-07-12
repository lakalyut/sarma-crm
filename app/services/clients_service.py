from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale
from ..utils.dates import month_sort_key


def get_clients_summary_data(
    db: Session,
    filters: list,
) -> dict:
    q = db.query(
        Sale.type.label("type"),
        Sale.client.label("client"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(Sale.sku)).label("sku_count"),
    )

    if filters:
        q = q.filter(*filters)

    q = q.group_by(Sale.type, Sale.client).order_by(Sale.type, Sale.client)
    rows = q.all()

    client_q = db.query(func.count(func.distinct(Sale.client)))
    sku_q = db.query(func.count(func.distinct(Sale.sku)))

    sums_q = db.query(
        func.sum(Sale.qty).label("qty_sum"),
        func.sum(Sale.weight).label("weight_sum"),
    )

    if filters:
        client_q = client_q.filter(*filters)
        sku_q = sku_q.filter(*filters)
        sums_q = sums_q.filter(*filters)

    unique_clients = int(client_q.scalar() or 0)
    unique_sku = int(sku_q.scalar() or 0)

    sums = sums_q.one()
    total_qty = float(sums.qty_sum or 0)
    total_weight = float(sums.weight_sum or 0)

    total_sku = int(sum(r.sku_count or 0 for r in rows)) if rows else 0

    type_cards = []
    if rows:
        type_counts = defaultdict(int)

        for row in rows:
            point_type = row.type or "—"
            type_counts[point_type] += 1

        type_cards = [
            {"type": point_type, "clients": count}
            for point_type, count in type_counts.items()
        ]
        type_cards.sort(key=lambda x: str(x["type"]))

    summary = {
        "unique_clients": unique_clients,
        "total_qty": total_qty,
        "total_weight": total_weight,
        "unique_sku": unique_sku,
        "total_sku": total_sku,
        "sku_per_client": (
            float(total_sku) / unique_clients if unique_clients else 0.0
        ),
    }

    monthly_by_client = _get_monthly_by_client(db=db, filters=filters)

    return {
        "rows": rows,
        "summary": summary,
        "type_cards": type_cards,
        "monthly_by_client": monthly_by_client,
    }


def _get_monthly_by_client(db: Session, filters: list) -> dict:
    q = db.query(
        Sale.type.label("type"),
        Sale.client.label("client"),
        Sale.month.label("month"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(Sale.sku)).label("sku_count"),
    )

    if filters:
        q = q.filter(*filters)

    q = q.group_by(Sale.type, Sale.client, Sale.month)
    rows = q.all()

    monthly_by_client = defaultdict(list)
    for row in rows:
        if not row.month:
            continue

        key = f"{row.type}|{row.client}"
        monthly_by_client[key].append(
            {
                "month": row.month,
                "qty": float(row.qty or 0),
                "weight": float(row.weight or 0),
                "sku_count": int(row.sku_count or 0),
            }
        )

    for months in monthly_by_client.values():
        months.sort(key=lambda m: month_sort_key(m["month"]))

    return dict(monthly_by_client)


def get_client_detail_data(
    db: Session,
    city: str,
    client: str,
    sale_type: str,
    months: list[str] | None = None,
    matched: str | None = None,
) -> dict:
    q = db.query(
        Sale.name.label("name"),
        Sale.sku.label("sku"),
        func.max(Sale.product_id).label("product_id"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
    ).filter(
        Sale.city == city,
        Sale.client == client,
        Sale.type == sale_type,
    )

    if months:
        q = q.filter(Sale.month.in_(months))

    if matched == "1":
        q = q.filter(Sale.matched.is_(True))
    elif matched == "0":
        q = q.filter(Sale.matched.is_(False))

    q = q.group_by(Sale.name, Sale.sku).order_by(Sale.name)
    rows = q.all()

    summary = None

    if rows:
        summary = {
            "nomenclatures": len(rows),
            "unique_sku": len({row.sku for row in rows if row.sku}),
            "total_qty": float(sum(row.qty or 0 for row in rows)),
            "total_weight": float(sum(row.weight or 0 for row in rows)),
        }

    monthly_q = db.query(
        Sale.month.label("month"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(Sale.sku)).label("sku_count"),
    ).filter(
        Sale.city == city,
        Sale.client == client,
        Sale.type == sale_type,
    )

    if months:
        monthly_q = monthly_q.filter(Sale.month.in_(months))

    if matched == "1":
        monthly_q = monthly_q.filter(Sale.matched.is_(True))
    elif matched == "0":
        monthly_q = monthly_q.filter(Sale.matched.is_(False))

    monthly_q = monthly_q.group_by(Sale.month)
    monthly_rows = monthly_q.all()

    monthly = sorted(
        (
            {
                "month": row.month,
                "qty": float(row.qty or 0),
                "weight": float(row.weight or 0),
                "sku_count": int(row.sku_count or 0),
            }
            for row in monthly_rows
            if row.month
        ),
        key=lambda m: month_sort_key(m["month"]),
    )

    return {
        "rows": rows,
        "summary": summary,
        "monthly": monthly,
    }
