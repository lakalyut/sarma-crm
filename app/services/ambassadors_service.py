from collections import defaultdict

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Sale
from ..utils.dates import month_sort_key


def sku_expr():
    return func.coalesce(Sale.sku, Sale.raw_sku, Sale.name, Sale.raw_name)


def normalize_selected_months(
    selected_months: list[str],
    all_months: list[str],
) -> list[str]:
    selected = [m for m in selected_months if m in all_months]

    if selected:
        return sorted(selected, key=month_sort_key)

    return sorted(all_months, key=month_sort_key)


def detect_sku_status(
    months_data: list[float],
    selected_months: list[str],
    status_settings: dict,
) -> tuple[str, str]:
    active_indexes = [index for index, value in enumerate(months_data) if value > 0]

    if not active_indexes:
        return "empty", "Нет продаж"

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

    is_new_for_client = (
        first_active_index > 0 and months_from_first_sale_to_end <= new_client_months
    )

    if missing_months_at_end >= lost_months:
        return "lost", "Пропал"

    if is_new_for_client:
        first_month = selected_months[first_active_index]
        return "new", f"Новый у клиента с {first_month}"

    if max_gap_inside >= unstable_gap_months:
        return "unstable", "Нестабильный"

    return "existing", "Был с начала"


def build_ambassadors_report(
    db: Session,
    selected_city: str,
    selected_months: list[str],
    selected_clients: list[str],
    selected_new_skus: list[str] | None = None,
    status_settings: dict | None = None,
) -> dict:
    report = {"months": [], "clients": []}

    selected_new_skus = selected_new_skus or []
    selected_new_skus_set = set(selected_new_skus)

    status_settings = status_settings or {
        "new_client_months": 2,
        "lost_months": 2,
        "unstable_gap_months": 1,
    }

    if not selected_city or not selected_months or not selected_clients:
        return report

    sales_rows = (
        db.query(
            Sale.client,
            Sale.month,
            Sale.weight,
            sku_expr().label("sku_key"),
        )
        .filter(
            Sale.city == selected_city,
            Sale.month.in_(selected_months),
            Sale.client.in_(selected_clients),
        )
        .all()
    )

    unique_sku_by_client_month = defaultdict(lambda: defaultdict(set))
    weight_by_client_month = defaultdict(lambda: defaultdict(float))
    sku_weight_by_client = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    unique_sku_total_by_client = defaultdict(set)
    weight_total_by_client = defaultdict(float)

    for row in sales_rows:
        client = row.client or "Без клиента"
        month = row.month or ""
        weight = float(row.weight or 0)
        sku_key_value = (row.sku_key or "").strip()

        weight_by_client_month[client][month] += weight
        weight_total_by_client[client] += weight

        if sku_key_value:
            unique_sku_by_client_month[client][month].add(sku_key_value)
            unique_sku_total_by_client[client].add(sku_key_value)
            sku_weight_by_client[client][sku_key_value][month] += weight

    for client in selected_clients:
        sku_summary = []
        weight_summary = []

        for month in selected_months:
            sku_summary.append(
                len(unique_sku_by_client_month[client].get(month, set()))
            )
            weight_summary.append(
                round(weight_by_client_month[client].get(month, 0.0), 2)
            )

        sku_details = []
        client_skus = sorted(sku_weight_by_client[client].keys())

        for sku_name in client_skus:
            months_data = []
            total = 0.0
            first_month = None

            for month in selected_months:
                value = round(sku_weight_by_client[client][sku_name].get(month, 0.0), 2)

                if value > 0 and first_month is None:
                    first_month = month

                months_data.append(value)
                total += value

            status, status_label = detect_sku_status(
                months_data=months_data,
                selected_months=selected_months,
                status_settings=status_settings,
            )

            sku_details.append(
                {
                    "sku": sku_name,
                    "months_data": months_data,
                    "total": round(total, 2),
                    "first_month": first_month,
                    "status": status,
                    "status_label": status_label,
                    "is_assortment_new": sku_name in selected_new_skus_set,
                    "is_new": status == "new",
                    "is_lost": status == "lost",
                }
            )

        report["clients"].append(
            {
                "name": client,
                "sku_total": sum(sku_summary),
                "unique_sku_total": len(unique_sku_total_by_client[client]),
                "weight_total": round(weight_total_by_client[client], 2),
                "expanded": False,
                "summary": {
                    "sku": sku_summary,
                    "weight": weight_summary,
                },
                "sku_details": sku_details,
            }
        )

    report["months"] = selected_months
    return report
