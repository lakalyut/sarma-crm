"""Главная страница (`/`) — снапшот по всему бизнесу сразу, все города,
один выбранный год (плашки года, не привычный месячный пикер — запрос
2026-09-12). Никаких прежних дашбордов не трогает: "Аналитика по регионам"
по-прежнему требует явного выбора региона и была и остаётся отдельной
страницей — здесь агрегат без выбора пользователя, поэтому вся логика
своя, не переиспользует dashboard_service._aggregate() буквально (тот
завязан на dims/город, здесь всегда "весь бизнес сразу").

ABC на этой странице — НОВЫЙ, отдельный от ручного `/admin/abc`
(`ProductAbcRating`) расчёт: правило 80/15/5 по фактическому весу продаж
(cumulative-share классификация, см. compute_abc_ranking). Не подменяет
ручной ABC-рейтинг нигде в остальном приложении (детализация клиента,
«Представленность SKU», лидерборд амбассадоров по-прежнему используют
ручной `ProductAbcRating`) — параллельная, самостоятельная метрика,
видна только здесь и на странице разреза по городам."""

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Product, Sale
from ..utils.dates import month_sort_key, parse_month
from .charts_service import sku_expr
from .sale_filters import build_sale_filters
from .sales_options_service import get_cities, get_months

ABC_CATEGORIES = ("A", "B", "C")


def get_available_years(db: Session) -> list[int]:
    """Список лет, за которые вообще есть продажи (по всем городам), по
    убыванию — под плашки года на главной. Год — через parse_month(), тот
    же парсер обоих форматов Sale.month, что и everywhere в проекте."""
    years: set[int] = set()
    for m in get_months(db):
        parsed = parse_month(m)
        if parsed:
            years.add(parsed[0])
    return sorted(years, reverse=True)


def _months_for_year(all_months: list[str], year: int) -> list[str]:
    """Месяцы конкретного года из общего списка, в хронологическом порядке
    (для графика — слева направо по времени, а не по убыванию, как хранит
    get_months(reverse=True))."""
    return sorted(
        (m for m in all_months if (parse_month(m) or (None,))[0] == year),
        key=month_sort_key,
    )


def _totals(db: Session, filters: list) -> dict:
    row = (
        db.query(
            func.coalesce(func.sum(Sale.weight), 0.0).label("weight"),
            func.count(func.distinct(Sale.client)).label("clients"),
            func.count(func.distinct(sku_expr())).label("unique_sku"),
        )
        .filter(*filters)
        .one()
    )
    return {
        "weight": float(row.weight or 0),
        "clients": int(row.clients or 0),
        "unique_sku": int(row.unique_sku or 0),
    }


def _delta(current: float, previous: float | None) -> dict:
    """Дельта год-к-году. previous=None или 0 — сравнивать не с чем (нет
    данных за прошлый год на те же месяцы) — direction="neutral", не "down"
    (0% не значит "упало", значит "не с чем сравнить"), pct=None.
    direction — те же три значения, что уже использует metric-delta.delta-up
    /.delta-down/.delta-neutral в charts.css, не свои имена."""
    if not previous:
        return {"pct": None, "direction": "neutral"}
    pct = (current - previous) / previous * 100
    direction = "up" if pct > 0.5 else ("down" if pct < -0.5 else "neutral")
    return {"pct": round(pct), "direction": direction}


def compute_abc_ranking(
    weight_by_product: dict[int, float], new_product_ids: set[int]
) -> dict[int, str]:
    """Правило 80/15/5 по кумулятивной доле веса. Новинки (new_product_ids)
    ПОЛНОСТЬЮ исключены — не участвуют ни в ранжировании, ни в базе для
    расчёта долей остальных (иначе свежий, ещё не раскрученный товар с
    маленьким весом искажал бы кумулятивный % устоявшегося ассортимента).
    Решение пользователя, 2026-09-12: у новинки в UI — бейдж NEW вместо
    буквы, ABC ей присваивают позже, когда она перестанет быть новинкой
    (тот же принцип, что уже был у aromas_new в лидерборде амбассадоров)."""
    established = sorted(
        (
            (pid, w)
            for pid, w in weight_by_product.items()
            if pid not in new_product_ids and w and w > 0
        ),
        key=lambda pair: -pair[1],
    )

    total = sum(w for _, w in established)
    ranking: dict[int, str] = {}
    if total <= 0:
        return ranking

    cumulative = 0.0
    for pid, w in established:
        cumulative += w
        share = cumulative / total
        if share <= 0.80:
            ranking[pid] = "A"
        elif share <= 0.95:
            ranking[pid] = "B"
        else:
            ranking[pid] = "C"
    return ranking


def _new_product_ids(db: Session) -> set[int]:
    return {pid for (pid,) in db.query(Product.id).filter(Product.is_new.is_(True))}


def get_home_overview(db: Session, year: int | None) -> dict:
    """Собирает всё для главной: KPI-карточки с дельтой год-к-году, график
    веса по месяцам года, топ городов по весу, топ вкусов по весу с
    расчётным ABC. Год не завершён — дельта считается за те же прожитые
    месяцы прошлого года (напр. янв-сен 2025 против янв-сен 2026), не за
    весь прошлый год целиком (решение пользователя, 2026-09-12)."""
    available_years = get_available_years(db)
    if not available_years:
        return {
            "available_years": [],
            "year": None,
            "has_data": False,
        }

    if year not in available_years:
        year = available_years[0]

    all_months = get_months(db)
    year_months = _months_for_year(all_months, year)
    elapsed_month_numbers = {parse_month(m)[1] for m in year_months}
    prev_months = [
        m
        for m in all_months
        if (parse_month(m) or (None, None))[0] == year - 1
        and (parse_month(m) or (None, None))[1] in elapsed_month_numbers
    ]

    cur_filters = build_sale_filters(months=year_months)
    prev_filters = build_sale_filters(months=prev_months) if prev_months else None

    cur_totals = _totals(db, cur_filters)
    prev_totals = (
        _totals(db, prev_filters)
        if prev_filters
        else {"weight": 0, "clients": 0, "unique_sku": 0}
    )

    metrics = {
        "weight": cur_totals["weight"],
        "clients": cur_totals["clients"],
        "unique_sku": cur_totals["unique_sku"],
        "weight_delta": _delta(cur_totals["weight"], prev_totals["weight"]),
        "clients_delta": _delta(cur_totals["clients"], prev_totals["clients"]),
    }

    # график — вес по месяцам года, хронологически
    weight_by_month = dict(
        db.query(Sale.month, func.sum(Sale.weight))
        .filter(Sale.month.in_(year_months))
        .group_by(Sale.month)
        .all()
        if year_months
        else []
    )
    chart = {
        "labels": [format_month_short_label(m) for m in year_months],
        "weight": [float(weight_by_month.get(m) or 0) for m in year_months],
    }

    # топ городов по весу
    city_rows = (
        db.query(Sale.city, func.sum(Sale.weight))
        .filter(Sale.month.in_(year_months))
        .group_by(Sale.city)
        .order_by(func.sum(Sale.weight).desc())
        .all()
        if year_months
        else []
    )
    total_city_weight = sum(float(w or 0) for _, w in city_rows) or 1.0
    top_cities = [
        {
            "city": city,
            "weight": float(w or 0),
            "share": round(float(w or 0) / total_city_weight * 100),
        }
        for city, w in city_rows
        if city
    ]

    # топ вкусов по весу + расчётный ABC (сопоставленные продажи, product_id
    # не NULL — сырые несопоставленные строки без canonical-названия сюда
    # не попадают, решение пользователя, тот же принцип, что в "Ревизии
    # номенклатуры": не смешивать сырое с каноническим)
    product_weight_rows = (
        db.query(Sale.product_id, func.sum(Sale.weight))
        .filter(Sale.month.in_(year_months), Sale.product_id.isnot(None))
        .group_by(Sale.product_id)
        .all()
        if year_months
        else []
    )
    weight_by_product = {pid: float(w or 0) for pid, w in product_weight_rows if pid}
    new_ids = _new_product_ids(db)
    ranking = compute_abc_ranking(weight_by_product, new_ids)

    products = (
        db.query(Product).filter(Product.id.in_(weight_by_product.keys())).all()
        if weight_by_product
        else []
    )
    top_flavors = sorted(
        (
            {
                "product_id": p.id,
                "flavor": p.flavor,
                "brand": p.brand,
                "weight": weight_by_product[p.id],
                "is_new": bool(p.is_new),
                "category": ranking.get(p.id),
            }
            for p in products
        ),
        key=lambda r: -r["weight"],
    )

    return {
        "available_years": available_years,
        "year": year,
        "has_data": True,
        "metrics": metrics,
        "chart": chart,
        "year_months": year_months,
        "top_cities": top_cities,
        "top_flavors": top_flavors,
    }


def format_month_short_label(month: str) -> str:
    # локальный, короткий формат под подписи оси графика (не через
    # app.templating.format_month_short — тот форматирует "Янв 2026",
    # здесь год и так один и тот же на всём графике, повторять не нужно)
    parsed = parse_month(month)
    if not parsed:
        return month
    names = [
        "Янв",
        "Фев",
        "Март",
        "Апр",
        "Май",
        "Июнь",
        "Июль",
        "Авг",
        "Сен",
        "Окт",
        "Ноя",
        "Дек",
    ]
    _, mon = parsed
    return names[mon - 1] if 1 <= mon <= 12 else month


def get_product_abc_by_city(db: Session, product_id: int, year: int) -> dict | None:
    """Разрез: тот же расчёт ABC (80/15/5 по весу, без новинок), но
    ПОРОЗДЕЛЬНО на каждый город — что покажет, если у товара, входящего в
    A по всему бизнесу сразу, есть города, где он едва продаётся (и был
    бы там C или вообще не продавался). Один запрос на все города сразу
    (group by city, product_id), не N+1 по городам."""
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return None

    all_months = get_months(db)
    year_months = _months_for_year(all_months, year)
    new_ids = _new_product_ids(db)

    rows = (
        db.query(Sale.city, Sale.product_id, func.sum(Sale.weight))
        .filter(Sale.month.in_(year_months), Sale.product_id.isnot(None))
        .group_by(Sale.city, Sale.product_id)
        .all()
        if year_months
        else []
    )

    by_city: dict[str, dict[int, float]] = defaultdict(dict)
    for city, pid, w in rows:
        if city and pid:
            by_city[city][pid] = float(w or 0)

    all_cities = get_cities(db)
    result_rows = []
    for city in all_cities:
        weights = by_city.get(city, {})
        ranking = compute_abc_ranking(weights, new_ids)
        weight = weights.get(product_id, 0.0)
        total = sum(weights.values()) or 1.0
        result_rows.append(
            {
                "city": city,
                "weight": weight,
                "share": round(weight / total * 100) if weight else 0,
                "category": (
                    "NEW"
                    if product_id in new_ids
                    else ranking.get(product_id) if weight > 0 else None
                ),
            }
        )

    result_rows.sort(key=lambda r: -r["weight"])

    return {
        "product": product,
        "year": year,
        "available_years": get_available_years(db),
        "rows": result_rows,
    }
