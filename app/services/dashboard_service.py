from sqlalchemy import case, func
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
    считается отдельным запросом на тех же dims + client, но сама сумма —
    подзапросом в SQL (SUM по sku_per_client), не Python-циклом. При широком
    выборе (например, выбраны сразу все макро-регионы) промежуточная
    (dims, client)-группировка может дать десятки тысяч строк — раньше все
    они по одной прилетали в Python и суммировались там же в словаре, это
    и было основным тормозом при выборе всех регионов разом (горизонт 12
    ROADMAP.md, доп. заход). Теперь наружу уходит уже готовая сумма на
    уровне dims — строк ровно столько же, сколько в base_rows.
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

    sku_per_client = (
        db.query(
            *[col.label(name) for name, col in dims],
            Sale.client.label("client"),
            func.count(func.distinct(sku_expr())).label("sku_count"),
        )
        .filter(*filters)
        .group_by(*group_cols, Sale.client)
        .subquery()
    )

    if dims:
        total_sku_cols = [sku_per_client.c[name] for name in labels]
        total_sku_rows = (
            db.query(
                *total_sku_cols,
                func.sum(sku_per_client.c.sku_count).label("total_sku"),
            )
            .group_by(*total_sku_cols)
            .all()
        )
    else:
        total_sku_rows = [
            db.query(func.sum(sku_per_client.c.sku_count).label("total_sku")).one()
        ]

    total_sku_map: dict[tuple, int] = {
        tuple(getattr(row, name) for name in labels): int(row.total_sku or 0)
        for row in total_sku_rows
    }

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


def get_regions_overview(
    db: Session,
    cities: list[str],
    months: list[str],
    city_to_region_name: dict[str, str] | None = None,
) -> dict:
    """Свод по регионам для страницы /analytics/regions: сетка город×месяц по всем
    метрикам каталога + итоги по городу (весь период), по месяцу (все
    выбранные города) и общий итог.

    city_to_region_name — города, входящие в выбранный макро-регион
    (справочник /admin/regions): их строки в SQL переименовываются в имя
    региона ДО group by, поэтому unique_clients/unique_sku на объединённую
    строку считаются честно (а не суммированием готовых per-город чисел,
    где клиент/SKU, встретившийся в нескольких городах региона, задвоился
    бы). Города вне city_to_region_name группируются как обычно, по себе.
    """
    filters = build_sale_filters(cities=cities, months=months)

    city_col = (
        case(city_to_region_name, value=Sale.city, else_=Sale.city)
        if city_to_region_name
        else Sale.city
    )

    grid = _aggregate(db, filters, [("city", city_col), ("month", Sale.month)])
    city_totals = _aggregate(db, filters, [("city", city_col)])
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
