"""Ревизия типов точек — некоторые регионы не присылают «тип точки»
(HoReCa/Розница/...) в исходных данных; пользователь проставляет его вручную
по эвристике (средний вес заказа). Эвристика не идеальна и может дать разный
результат от месяца к месяцу — один и тот же клиент попадает то в один тип,
то в другой, хотя реально это одна и та же точка.

В отличие от «Ревизии номенклатуры» ([nomenclature_review_service.py](nomenclature_review_service.py))
здесь нет эталона (`Product.canonical_sku`), с которым можно свериться —
`Sale.type`/`Sale.client` не копии чего-либо, это единственный источник.
Значит это не «сверка с эталоном», а «дать пользователю решить, что считать
правильным, и массово применить решение» — детект находит кандидатов и
предлагает дефолт (самый частый тип по числу строк), но финальный выбор и
подтверждение — всегда за пользователем, автослияния нет.

Как и в ревизии номенклатуры — считаем только SQL-агрегатами (GROUP BY),
без материализации `sales` в ORM (авария 2026-09-10, см. CLAUDE.md), и чиним
одним `UPDATE` на клиента, не циклом по строкам."""

from collections import defaultdict

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from ..models import Sale
from ..utils.dates import parse_month


def get_review_cities(db: Session) -> list[str]:
    """Города с продажами для фильтра ревизии."""
    return sorted(city for (city,) in db.query(Sale.city).distinct() if city and city.strip())


def get_type_drift_groups(db: Session, city: str | None = None) -> list[dict]:
    """(город, клиент), у которых `Sale.type` принимает больше одного
    значения за всю историю — кандидаты на выравнивание. Один SQL-запрос;
    строк в результате — по числу уникальных (город, клиент, тип, месяц),
    а не по числу продаж."""
    query = db.query(
        Sale.city,
        Sale.client,
        Sale.type,
        Sale.month,
        func.count(Sale.id).label("cnt"),
    )
    if city:
        query = query.filter(Sale.city == city)
    rows = query.group_by(Sale.city, Sale.client, Sale.type, Sale.month).all()

    # Сохраняем `type=None` как есть (не подменяем плейсхолдером) — регионы,
    # которые вообще не присылают тип, дают именно NULL, это тоже «версия»
    # типа, которую надо показать и куда-то выровнять, а не потерять при
    # группировке.
    by_client: dict[tuple[str, str], dict[str | None, int]] = defaultdict(dict)
    latest_by_client: dict[tuple[str, str], tuple[tuple[int, int], set[str | None]]] = {}
    for row in rows:
        city = row.city or "—"
        client = row.client or "—"
        key = (city, client)
        counts = by_client[key]
        counts[row.type] = counts.get(row.type, 0) + row.cnt

        # Sale.month — период продаж, а не время ручного исправления. Данные
        # хранятся и в ISO, и в русском формате: сравниваем разобранные месяцы.
        period = parse_month(row.month)
        if period:
            previous = latest_by_client.get(key)
            if previous is None or period > previous[0]:
                latest_by_client[key] = (period, {row.type})
            elif period == previous[0]:
                previous[1].add(row.type)

    groups = []
    for (city, client), counts_by_type in by_client.items():
        if len(counts_by_type) <= 1:
            continue

        # Дефолт-подсказка — только среди РЕАЛЬНЫХ значений типа: NULL сам
        # по себе не может быть «правильным» выбором (это как раз то, что
        # чиним), даже если формально встречается чаще всего.
        non_null_counts = {t: c for t, c in counts_by_type.items() if t}
        if not non_null_counts:
            continue

        default_type = max(non_null_counts.items(), key=lambda kv: kv[1])[0]
        total_rows = sum(counts_by_type.values())
        latest = latest_by_client.get((city, client))

        groups.append(
            {
                "city": city,
                "client": client,
                "types": sorted(
                    counts_by_type.items(), key=lambda kv: -kv[1]
                ),  # [(type|None, count), ...] по убыванию строк
                "type_options": sorted(
                    non_null_counts.items(), key=lambda kv: -kv[1]
                ),  # то же самое, но только реальные значения — для выбора
                "total_rows": total_rows,
                "default_type": default_type,
                "latest_month": f"{latest[0][0]:04d}-{latest[0][1]:02d}-01" if latest else None,
                "latest_types": sorted(latest[1], key=lambda t: (t is None, t or ""))
                if latest
                else [],
            }
        )

    groups.sort(key=lambda g: (-g["total_rows"], g["city"], g["client"]))
    return groups


def resync_client_type(db: Session, city: str, client: str, correct_type: str) -> int:
    """Один `UPDATE` — все продажи (город, клиент) получают единый тип.
    `correct_type` — всегда непустая строка (UI предлагает на выбор только
    `type_options`, без NULL-варианта — см. `get_type_drift_groups`).
    `Sale.type.is_(None)` в условии отдельно — NULL-safe сравнение, обычный
    `type != X` в SQL не включает строки с NULL (та же ловушка, что уже была
    в `nomenclature_review_service`)."""
    res = db.execute(
        update(Sale)
        .where(
            Sale.city == city,
            Sale.client == client,
            Sale.type.is_(None) | (Sale.type != correct_type),
        )
        .values(type=correct_type)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return res.rowcount or 0
