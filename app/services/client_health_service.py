"""«Здоровье клиентской базы» — статус клиента ЦЕЛИКОМ (не по отдельному
SKU, см. `build_client_sku_status` в `ambassadors_service.py`) за выбранный
период: заказывает ли клиент вообще, а не «взял ли он именно этот вкус».

Классификация — тот же позиционный принцип, что у `detect_sku_status`:
индекс месяца в `selected_months` (относительно ВЫБРАННОГО окна, не
календарной даты «сегодня» — продажи грузятся с опозданием на месяц, см.
CLAUDE.md), не переиспользуем саму функцию напрямую (список статусов и
приоритеты разошлись — на уровне SKU это лишний риск сломать отчёты
"Амбассадорский отчёт"/детализация клиента), но статусы всего 4 — столько
же, сколько у SKU-версии (New/Lost/Unstable/Existing), специально ради
единообразия.

**История:** первая версия (2026-09-11) заводила 6 статусов — отдельно
"slowing" (хвостовой разрыв короче `lost_months`) и "winback" (был разрыв
длиной `lost_months`+ внутри окна, но клиент снова активен). По фидбеку
пользователя («смущает такое большое количество статусов») слиты в один
"unstable" — сама подсказка (`_status_reason`) при наведении по-прежнему
называет конкретную причину (хвостовой разрыв или разрыв внутри периода),
просто это больше не отдельный статус/цвет плашки.
"""

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale
from ..templating import format_month
from ..utils.dates import month_sort_key

DEFAULT_STATUS_SETTINGS = {
    "new_client_months": 2,
    "lost_months": 2,
    "unstable_gap_months": 1,
}

STATUS_LABELS = {
    "lost": "Потерян",
    "unstable": "Нестабильный",
    "new": "Новый",
    "existing": "Активен",
    "empty": "Нет продаж",
}

# Порядок статусов по умолчанию — тревожные сигналы сверху, спокойные
# (existing) внизу. Тот же список задаёт и порядок status_counts.
STATUS_ORDER = ["lost", "unstable", "new", "existing", "empty"]


def detect_client_status(
    months_data: list[float],
    status_settings: dict,
    is_new: bool | None = None,
) -> tuple[str, str, dict]:
    """Возвращает (status, label, details). `details` — сырые позиционные
    сигналы (индексы, не готовый текст) — из них `_status_reason()` ниже
    собирает подсказку для тултипа на плашке; тестам/другим вызывающим
    достаточно первых двух элементов.

    `is_new` — можно передать готовым (так делает `build_client_health`, см.
    её докстринг: «Новый» проверяется по ПОЛНОЙ истории города, не по
    короткому `months_data`-окну). Если не передан (`None`) — считается по
    самому `months_data`, как раньше: первая продажа не с начала массива И
    попала в последние `new_client_months`. Это годится только когда
    `months_data` и есть «весь период» (изолированный вызов/тесты) — при
    коротком окне (квартал) так пропускаются клиенты, чья самая первая
    продажа в жизни пришлась ровно на 1-й месяц ЭТОГО окна: массив не может
    отличить «появился прямо тут» от «был всегда, окно просто не видит
    более раннюю историю» (баг/фидбек пользователя, 2026-09-11)."""
    active_indexes = [index for index, value in enumerate(months_data) if value > 0]

    if not active_indexes:
        return "empty", STATUS_LABELS["empty"], {}

    new_client_months = int(status_settings.get("new_client_months", 2))
    lost_months = int(status_settings.get("lost_months", 2))
    unstable_gap_months = int(status_settings.get("unstable_gap_months", 1))

    first_active_index = active_indexes[0]
    last_active_index = active_indexes[-1]

    missing_months_at_end = len(months_data) - 1 - last_active_index

    max_gap_inside = 0
    max_gap_start_index = None
    max_gap_end_index = None
    current_gap = 0
    current_gap_start_index = None

    for index, value in enumerate(months_data):
        if index < first_active_index:
            # Месяцы ДО первой продажи клиента — точки ещё не существовало,
            # это не разрыв в её закупках. Без этой отсечки цикл считал
            # весь «стаж отсутствия» перед открытием точки одним огромным
            # разрывом (баг, поймали 2026-09-11: точка открылась в середине
            # общей истории города, торгует без единого пропуска с самого
            # открытия — но получала «Нестабильный» из-за месяцев, когда её
            # физически не было).
            continue

        if index > last_active_index:
            break

        if value == 0:
            if current_gap == 0:
                current_gap_start_index = index
            current_gap += 1
            if current_gap > max_gap_inside:
                max_gap_inside = current_gap
                max_gap_start_index = current_gap_start_index
                max_gap_end_index = index
        else:
            current_gap = 0

    if is_new is None:
        months_from_first_sale_to_end = len(months_data) - first_active_index
        is_new = (
            first_active_index > 0
            and months_from_first_sale_to_end <= new_client_months
        )

    details = {
        "first_active_index": first_active_index,
        "last_active_index": last_active_index,
        "missing_months_at_end": missing_months_at_end,
        "max_gap_inside": max_gap_inside,
        "max_gap_start_index": max_gap_start_index,
        "max_gap_end_index": max_gap_end_index,
    }

    if missing_months_at_end >= lost_months:
        return "lost", STATUS_LABELS["lost"], details

    if is_new:
        return "new", STATUS_LABELS["new"], details

    # Любая нестабильность короче "потерян" — хвостовой разрыв (ещё не
    # дотянул до lost_months) или разрыв внутри периода (был перебой,
    # сейчас снова покупает) — один статус "Нестабильный", причину уточняет
    # _status_reason() в подсказке на плашке, не отдельным цветом.
    if missing_months_at_end > 0 or max_gap_inside >= unstable_gap_months:
        return "unstable", STATUS_LABELS["unstable"], details

    return "existing", STATUS_LABELS["existing"], details


def _status_reason(
    status: str,
    details: dict,
    selected_months: list[str],
    status_settings: dict,
) -> str:
    """Человекочитаемая причина статуса — для `title` (нативный тултип по
    наведению) на плашке статуса, и на «Клиентах», и на вкладке «Здоровье
    базы»."""

    def month_at(index: int | None) -> str:
        if index is None or not (0 <= index < len(selected_months)):
            return "—"
        return format_month(selected_months[index])

    def gap_range() -> str:
        start = month_at(details.get("max_gap_start_index"))
        end = month_at(details.get("max_gap_end_index"))
        return start if start == end else f"{start} – {end}"

    if status == "empty":
        return "Нет продаж за выбранный период"

    if status == "lost":
        return (
            f"Нет продаж {details['missing_months_at_end']} мес. подряд — "
            f"последняя покупка была в {month_at(details['last_active_index'])}"
        )

    if status == "new":
        # true_first_month — настоящая первая продажа по ВСЕЙ истории города
        # (см. build_client_health), может лежать раньше окна (details['first_
        # active_index'] тогда указывал бы на первый видимый в окне месяц, не
        # на настоящую первую продажу) — предпочитаем её, если она известна.
        true_first_month = details.get("true_first_month")
        first_label = (
            format_month(true_first_month)
            if true_first_month
            else month_at(details["first_active_index"])
        )
        return (
            f"Первая продажа — {first_label}, "
            f"это последние {status_settings.get('new_client_months', 2)} мес. периода"
        )

    if status == "unstable":
        # Хвостовой разрыв (клиент замолчал недавно, но ещё не "потерян") —
        # более срочный сигнал, чем разрыв где-то в середине периода,
        # поэтому если есть оба — говорим про хвостовой.
        if details["missing_months_at_end"] > 0:
            return (
                f"Нет продаж последние {details['missing_months_at_end']} мес. — "
                f"последняя покупка была в {month_at(details['last_active_index'])}"
            )
        return (
            f"Был перерыв без продаж {gap_range()} "
            f"({details['max_gap_inside']} мес.) внутри периода, затем снова покупки"
        )

    return (
        "Стабильные продажи весь период, без перерывов от "
        f"{status_settings.get('unstable_gap_months', 1)} мес."
    )


def build_client_health(
    db: Session,
    city: str,
    selected_months: list[str],
    status_settings: dict | None = None,
) -> dict:
    """`selected_months` — короткое окно (квартал по умолчанию, не вся
    история города — запрос пользователя, 2026-09-11). Это окно годится для
    «Потерян»/«Нестабильный» (смотрим на недавние разрывы), но НЕ годится
    само по себе для «Новый» — короткий массив не может отличить «появился
    прямо в начале окна» от «был всегда, окно просто не видит более раннюю
    историю» (баг/фидбек пользователя, 2026-09-11). Поэтому здесь отдельно,
    без фильтра по `selected_months`, тянется ПОЛНАЯ история города —
    `history_rows` даёт и список всех известных (клиент, тип точки) пар (для
    случая «ноль продаж в окне, но клиент точно существует — это Потерян, не
    нет данных»), и по каждой паре — её настоящую первую продажу когда-либо
    (для честного «Новый»), и список всех месяцев города вообще (чтобы мерить
    «давность» первой продажи в реальных, не window-относительных, шагах)."""
    status_settings = status_settings or DEFAULT_STATUS_SETTINGS

    empty_result: dict = {
        "months": selected_months,
        "rows": [],
        "status_counts": dict.fromkeys(STATUS_ORDER, 0),
    }

    if not city or not selected_months:
        return empty_result

    sales_rows = (
        db.query(
            Sale.client,
            Sale.type,
            Sale.month,
            func.sum(Sale.weight).label("weight"),
        )
        .filter(Sale.city == city, Sale.month.in_(selected_months))
        .group_by(Sale.client, Sale.type, Sale.month)
        .all()
    )

    weight_by_key: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )

    for row in sales_rows:
        client = row.client or "Без клиента"
        sale_type = row.type or "—"
        weight_by_key[(client, sale_type)][row.month] += float(row.weight or 0)

    history_rows = (
        db.query(Sale.client, Sale.type, Sale.month)
        .filter(Sale.city == city)
        .distinct()
        .all()
    )

    months_by_key: dict[tuple[str, str], set[str]] = defaultdict(set)
    all_known_months: set[str] = set()

    for row in history_rows:
        client = row.client or "Без клиента"
        sale_type = row.type or "—"
        key = (client, sale_type)
        weight_by_key[key]  # noqa: B018 — просто создать ключ, даже без продаж в окне
        if row.month:
            months_by_key[key].add(row.month)
            all_known_months.add(row.month)

    sorted_known_months = sorted(all_known_months, key=month_sort_key)
    window_end_month = max(selected_months, key=month_sort_key)

    def _new_signal(key: tuple[str, str]) -> tuple[bool, str | None]:
        """(is_new по полной истории, настоящий месяц первой продажи)."""
        months_ever = months_by_key.get(key)
        if (
            not months_ever
            or not sorted_known_months
            or window_end_month not in sorted_known_months
        ):
            return False, None

        true_first_month = min(months_ever, key=month_sort_key)
        if true_first_month not in sorted_known_months:
            return False, true_first_month

        if true_first_month == sorted_known_months[0]:
            # Их первая продажа совпадает с самым первым известным месяцем
            # города вообще — доказать «раньше их точно не было» нечем
            # (данных «до этого» просто нет), поэтому не считаем «Новый»,
            # как и раньше не считали, если первая продажа была в начале
            # массива (тот же принцип, перенесённый с окна на всю историю).
            return False, true_first_month

        # +1 — считаем месяцы ОТ первой продажи ДО конца окна включительно
        # (тот же смысл, что months_from_first_sale_to_end в
        # detect_client_status: разница индексов даёт число шагов МЕЖДУ
        # месяцами, а не число месяцев «от и до»).
        months_since_first_sale = (
            sorted_known_months.index(window_end_month)
            - sorted_known_months.index(true_first_month)
            + 1
        )
        new_client_months = int(status_settings.get("new_client_months", 2))
        return 0 < months_since_first_sale <= new_client_months, true_first_month

    status_counts = dict.fromkeys(STATUS_ORDER, 0)
    rows = []

    for key, weight_by_month in weight_by_key.items():
        client, sale_type = key
        months_data = [round(weight_by_month.get(m, 0.0), 2) for m in selected_months]
        is_new, true_first_month = _new_signal(key)
        status, status_label, details = detect_client_status(
            months_data, status_settings, is_new=is_new
        )

        if status == "empty":
            # Ноль продаж во ВСЁМ окне, но пара (клиент, тип точки) известна
            # по городу целиком (см. history_rows выше) — значит покупали
            # раньше, за пределами окна. Это не «нет данных», это «Потерян».
            status, status_label = "lost", STATUS_LABELS["lost"]
            status_reason = "Нет продаж за весь выбранный период"
        else:
            if true_first_month:
                details["true_first_month"] = true_first_month
            status_reason = _status_reason(
                status, details, selected_months, status_settings
            )
        status_counts[status] += 1

        first_month = next(
            (m for m, v in zip(selected_months, months_data, strict=False) if v > 0),
            None,
        )
        last_month = next(
            (
                m
                for m, v in zip(
                    reversed(selected_months), reversed(months_data), strict=False
                )
                if v > 0
            ),
            None,
        )

        rows.append(
            {
                "client": client,
                "sale_type": sale_type,
                "status": status,
                "status_label": status_label,
                "status_reason": status_reason,
                "weight_total": round(sum(months_data), 2),
                "months_data": months_data,
                "first_month": first_month,
                "last_month": last_month,
            }
        )

    rows.sort(
        key=lambda r: (
            STATUS_ORDER.index(r["status"]),
            r["client"].lower(),
            r["sale_type"] or "",
        )
    )

    return {
        "months": selected_months,
        "rows": rows,
        "status_counts": status_counts,
    }
