"""«Здоровье клиентской базы» — статус клиента ЦЕЛИКОМ (не по отдельному
SKU, см. `build_client_sku_status` в `ambassadors_service.py`) за выбранный
период: заказывает ли клиент вообще, а не «взял ли он именно этот вкус».

Классификация — тот же позиционный принцип, что у `detect_sku_status`:
индекс месяца в `selected_months` (относительно ВЫБРАННОГО окна, не
календарной даты «сегодня» — продажи грузятся с опозданием на месяц, см.
CLAUDE.md), не переиспользуем саму функцию напрямую (список статусов и
приоритеты разошлись — на уровне SKU это лишний риск сломать отчёты
"Амбассадорский отчёт"/детализация клиента), но два статуса, которых у
SKU-версии нет:
- **slowing** («Замедляется») — в конце окна уже есть разрыв без продаж, но
  ещё короче `lost_months`: ранний сигнал раньше, чем клиент официально
  «потерян».
- **winback** («Вернулся») — где-то внутри окна был разрыв длиной
  `lost_months` и больше (то есть по факту клиент «уходил»), но к концу окна
  снова активен.
"""

from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale

DEFAULT_STATUS_SETTINGS = {
    "new_client_months": 2,
    "lost_months": 2,
    "unstable_gap_months": 1,
}

STATUS_LABELS = {
    "lost": "Потерян",
    "slowing": "Замедляется",
    "unstable": "Нестабильный",
    "winback": "Вернулся",
    "new": "Новый",
    "existing": "Активен",
    "empty": "Нет продаж",
}

# Порядок статусов по умолчанию — тревожные и «интересные» сигналы сверху,
# спокойные (existing) внизу. Тот же список задаёт и порядок status_counts.
STATUS_ORDER = ["lost", "slowing", "unstable", "winback", "new", "existing", "empty"]


def detect_client_status(
    months_data: list[float],
    status_settings: dict,
) -> tuple[str, str]:
    active_indexes = [index for index, value in enumerate(months_data) if value > 0]

    if not active_indexes:
        return "empty", STATUS_LABELS["empty"]

    new_client_months = int(status_settings.get("new_client_months", 2))
    lost_months = int(status_settings.get("lost_months", 2))
    unstable_gap_months = int(status_settings.get("unstable_gap_months", 1))

    first_active_index = active_indexes[0]
    last_active_index = active_indexes[-1]

    missing_months_at_end = len(months_data) - 1 - last_active_index

    max_gap_inside = 0
    current_gap = 0

    for index, value in enumerate(months_data):
        if index > last_active_index:
            break

        if value == 0:
            current_gap += 1
            max_gap_inside = max(max_gap_inside, current_gap)
        else:
            current_gap = 0

    months_from_first_sale_to_end = len(months_data) - first_active_index
    is_new = (
        first_active_index > 0 and months_from_first_sale_to_end <= new_client_months
    )

    if missing_months_at_end >= lost_months:
        return "lost", STATUS_LABELS["lost"]

    if is_new:
        return "new", STATUS_LABELS["new"]

    if max_gap_inside >= lost_months:
        return "winback", STATUS_LABELS["winback"]

    if missing_months_at_end > 0:
        return "slowing", STATUS_LABELS["slowing"]

    if max_gap_inside >= unstable_gap_months:
        return "unstable", STATUS_LABELS["unstable"]

    return "existing", STATUS_LABELS["existing"]


def build_client_health(
    db: Session,
    city: str,
    selected_months: list[str],
    status_settings: dict | None = None,
) -> dict:
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

    status_counts = dict.fromkeys(STATUS_ORDER, 0)
    rows = []

    for (client, sale_type), weight_by_month in weight_by_key.items():
        months_data = [round(weight_by_month.get(m, 0.0), 2) for m in selected_months]
        status, status_label = detect_client_status(months_data, status_settings)
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
