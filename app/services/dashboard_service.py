from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale
from ..utils.dates import month_sort_key
from .charts_service import format_month_label, sku_expr
from .sale_filters import build_sale_filters

METRIC_CATALOG = [
    {"key": "weight", "label": "Вес", "kind": "float", "unit": "кг"},
    {"key": "qty", "label": "Количество", "kind": "float", "unit": ""},
    {"key": "unique_clients", "label": "Клиенты", "kind": "int", "unit": ""},
    {"key": "total_sku", "label": "Всего SKU", "kind": "int", "unit": ""},
    {"key": "unique_sku", "label": "Уникальных SKU", "kind": "int", "unit": ""},
    {"key": "sku_per_client", "label": "SKU на клиента", "kind": "float", "unit": ""},
]

METRIC_MAP = {m["key"]: m for m in METRIC_CATALOG}


def _aggregate(db: Session, filters: list, dims: list[tuple[str, object]]) -> dict:
    """Считает все метрики каталога, сгруппированные по dims (city/month/оба/ничего).

    total_sku — сумма по клиентам количества различных SKU у каждого (не
    сворачивается из готовой (city, month)-сетки простым суммированием, иначе
    задвоятся клиенты, повторившиеся в нескольких месяцах/городах) — поэтому
    считается отдельным запросом на тех же dims + client.
    """
    group_cols = [col for _, col in dims]
    labels = [name for name, _ in dims]

    base_rows = (
        db.query(
            *[col.label(name) for name, col in dims],
            func.sum(Sale.qty).label("qty"),
            func.sum(Sale.weight).label("weight"),
            func.count(func.distinct(sku_expr())).label("unique_sku"),
            func.count(func.distinct(Sale.client)).label("unique_clients"),
        )
        .filter(*filters)
        .group_by(*group_cols)
        .all()
        if dims
        else [
            db.query(
                func.sum(Sale.qty).label("qty"),
                func.sum(Sale.weight).label("weight"),
                func.count(func.distinct(sku_expr())).label("unique_sku"),
                func.count(func.distinct(Sale.client)).label("unique_clients"),
            )
            .filter(*filters)
            .one()
        ]
    )

    sku_rows = (
        db.query(
            *[col.label(name) for name, col in dims],
            Sale.client.label("client"),
            func.count(func.distinct(sku_expr())).label("sku_count"),
        )
        .filter(*filters)
        .group_by(*group_cols, Sale.client)
        .all()
    )

    total_sku_map: dict[tuple, int] = {}
    for row in sku_rows:
        key = tuple(getattr(row, name) for name in labels)
        total_sku_map[key] = total_sku_map.get(key, 0) + int(row.sku_count or 0)

    result: dict[tuple, dict] = {}
    for row in base_rows:
        key = tuple(getattr(row, name) for name in labels)
        unique_clients = int(row.unique_clients or 0)
        total_sku = total_sku_map.get(key, 0)
        result[key] = {
            "qty": float(row.qty or 0),
            "weight": float(row.weight or 0),
            "unique_sku": int(row.unique_sku or 0),
            "unique_clients": unique_clients,
            "total_sku": total_sku,
            "sku_per_client": (total_sku / unique_clients) if unique_clients else 0,
        }

    return result


def get_regions_overview(db: Session, cities: list[str], months: list[str]) -> dict:
    """Свод по регионам для страницы /dashboard: сетка город×месяц по всем
    метрикам каталога + итоги по городу (весь период), по месяцу (все
    выбранные города) и общий итог."""
    filters = build_sale_filters(cities=cities, months=months)

    grid = _aggregate(db, filters, [("city", Sale.city), ("month", Sale.month)])
    city_totals = _aggregate(db, filters, [("city", Sale.city)])
    month_totals = _aggregate(db, filters, [("month", Sale.month)])
    grand = _aggregate(db, filters, [])

    city_list = sorted(
        {city for (city, _month) in grid.keys() if city},
        key=lambda city: -city_totals.get((city,), {}).get("weight", 0),
    )
    month_list = sorted(
        {month for (_city, month) in grid.keys() if month}, key=month_sort_key
    )
    month_labels = [format_month_label(m) for m in month_list]

    metrics = {}
    for meta in METRIC_CATALOG:
        key = meta["key"]
        metrics[key] = {
            "label": meta["label"],
            "kind": meta["kind"],
            "unit": meta["unit"],
            "grid": {
                city: [grid.get((city, month), {}).get(key, 0) for month in month_list]
                for city in city_list
            },
            "city_totals": {
                city: city_totals.get((city,), {}).get(key, 0) for city in city_list
            },
            "month_totals": [
                month_totals.get((month,), {}).get(key, 0) for month in month_list
            ],
            "grand": grand.get((), {}).get(key, 0),
        }

    return {
        "cities": city_list,
        "months": month_list,
        "month_labels": month_labels,
        "metrics": metrics,
    }
