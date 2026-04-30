from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale
from ..templating import templates
from ..utils.dates import month_sort_key


def sku_expr():
    return func.coalesce(Sale.sku, Sale.raw_sku, Sale.name, Sale.raw_name)


def format_month_label(month: str) -> str:
    return templates.env.filters["format_month"](month)


def get_charts_metrics_data(
    db: Session,
    filters: list,
    group: str = "total",
) -> dict:
    if group == "type":
        return _get_metrics_by_type(db=db, filters=filters)

    return _get_total_metrics(db=db, filters=filters)


def _get_metrics_by_type(db: Session, filters: list) -> dict:
    q = db.query(
        Sale.month.label("month"),
        Sale.type.label("series"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(sku_expr())).label("unique_sku"),
        func.count(func.distinct(Sale.client)).label("unique_clients"),
    )

    if filters:
        q = q.filter(*filters)

    q = q.group_by(Sale.month, Sale.type).order_by(Sale.month, Sale.type)
    rows = q.all()

    month_list = sorted({r.month for r in rows if r.month}, key=month_sort_key)
    labels = [format_month_label(m) for m in month_list]

    series_names = sorted({r.series for r in rows if r.series})

    data_map = {
        series_name: {
            month: {
                "qty": 0,
                "weight": 0,
                "unique_sku": 0,
                "unique_clients": 0,
            }
            for month in month_list
        }
        for series_name in series_names
    }

    for r in rows:
        if not r.month or not r.series:
            continue

        data_map[r.series][r.month] = {
            "qty": float(r.qty or 0),
            "weight": float(r.weight or 0),
            "unique_sku": int(r.unique_sku or 0),
            "unique_clients": int(r.unique_clients or 0),
        }

    series = []

    for series_name in series_names:
        series.append(
            {
                "name": series_name,
                "qty": [data_map[series_name][m]["qty"] for m in month_list],
                "weight": [data_map[series_name][m]["weight"] for m in month_list],
                "unique_sku": [
                    data_map[series_name][m]["unique_sku"] for m in month_list
                ],
                "unique_clients": [
                    data_map[series_name][m]["unique_clients"] for m in month_list
                ],
            }
        )

    return {
        "labels": labels,
        "series": series,
    }


def _get_total_metrics(db: Session, filters: list) -> dict:
    by_type_q = db.query(
        Sale.month.label("month"),
        Sale.type.label("type"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(sku_expr())).label("unique_sku"),
        func.count(func.distinct(Sale.client)).label("unique_clients"),
    )

    totals_q = db.query(
        Sale.month.label("month"),
        func.sum(Sale.qty).label("qty"),
        func.sum(Sale.weight).label("weight"),
        func.count(func.distinct(sku_expr())).label("unique_sku"),
        func.count(func.distinct(Sale.client)).label("unique_clients"),
    )

    total_sku_q = db.query(
        Sale.month.label("month"),
        Sale.type.label("type"),
        Sale.client.label("client"),
        func.count(func.distinct(sku_expr())).label("sku_count"),
    )

    if filters:
        by_type_q = by_type_q.filter(*filters)
        totals_q = totals_q.filter(*filters)
        total_sku_q = total_sku_q.filter(*filters)

    by_type_rows = by_type_q.group_by(Sale.month, Sale.type).all()
    total_rows = totals_q.group_by(Sale.month).all()

    total_sku_rows = total_sku_q.group_by(
        Sale.month,
        Sale.type,
        Sale.client,
    ).all()

    month_list = sorted(
        {r.month for r in by_type_rows if r.month}
        | {r.month for r in total_rows if r.month}
        | {r.month for r in total_sku_rows if r.month},
        key=month_sort_key,
    )

    type_list = sorted({r.type for r in by_type_rows if r.type})
    labels = [format_month_label(m) for m in month_list]

    data = {
        month: {
            "qty": 0,
            "weight": 0,
            "unique_sku": 0,
            "unique_clients": 0,
            "total_sku": 0,
            "types": {
                point_type: {
                    "qty": 0,
                    "weight": 0,
                    "unique_sku": 0,
                    "clients": 0,
                    "total_sku": 0,
                }
                for point_type in type_list
            },
        }
        for month in month_list
    }

    for row in total_rows:
        if not row.month or row.month not in data:
            continue

        data[row.month]["qty"] = float(row.qty or 0)
        data[row.month]["weight"] = float(row.weight or 0)
        data[row.month]["unique_sku"] = int(row.unique_sku or 0)
        data[row.month]["unique_clients"] = int(row.unique_clients or 0)

    for row in by_type_rows:
        if not row.month or not row.type:
            continue

        data[row.month]["types"][row.type]["qty"] = float(row.qty or 0)
        data[row.month]["types"][row.type]["weight"] = float(row.weight or 0)
        data[row.month]["types"][row.type]["unique_sku"] = int(row.unique_sku or 0)
        data[row.month]["types"][row.type]["clients"] = int(row.unique_clients or 0)

    for row in total_sku_rows:
        if not row.month or row.month not in data:
            continue

        sku_count = int(row.sku_count or 0)

        data[row.month]["total_sku"] += sku_count

        if row.type and row.type in data[row.month]["types"]:
            data[row.month]["types"][row.type]["total_sku"] += sku_count

    series = [
        {
            "name": "Итого",
            "qty": [data[m]["qty"] for m in month_list],
            "weight": [data[m]["weight"] for m in month_list],
            "weight_by_type": {
                t: [data[m]["types"][t]["weight"] for m in month_list]
                for t in type_list
            },
            "unique_sku": [data[m]["unique_sku"] for m in month_list],
            "total_sku": [data[m]["total_sku"] for m in month_list],
            "unique_clients": [data[m]["unique_clients"] for m in month_list],
            "sku_per_client": [
                (
                    data[m]["total_sku"] / data[m]["unique_clients"]
                    if data[m]["unique_clients"]
                    else 0
                )
                for m in month_list
            ],
            "clients_by_type": {
                t: [data[m]["types"][t]["clients"] for m in month_list]
                for t in type_list
            },
            "sku_by_type": {
                t: [data[m]["types"][t]["unique_sku"] for m in month_list]
                for t in type_list
            },
            "total_sku_by_type": {
                t: [data[m]["types"][t]["total_sku"] for m in month_list]
                for t in type_list
            },
            "sku_per_client_by_type": {
                t: [
                    (
                        data[m]["types"][t]["total_sku"]
                        / data[m]["types"][t]["clients"]
                        if data[m]["types"][t]["clients"]
                        else 0
                    )
                    for m in month_list
                ]
                for t in type_list
            },
        }
    ]

    return {
        "labels": labels,
        "series": series,
    }
